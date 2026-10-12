"""Installed compile/prepare/execute acceptance. Synthetic allocation, no science."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import signal
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import qraft
from qraft.api import CanonicalController, RunPreparer, RunPreparationRequest, WorkflowCompiler, write_workflow_lock
from qraft.contracts import CapabilityDescriptor, CapabilityKind, ContractVersion, PluginDescriptor, EXECUTION_REQUEST, EXECUTION_EVIDENCE
from qraft.core import TechnicalValidation
from qraft.execution.controller_files import read_controller_json
from qraft.execution.controller_processes import PidfdSignals, ProcessIdentity, process_identity
from qraft.execution.srun_launcher import StepOutcome


CONTROLLER = "consumer.controller.hf1"
OTHER = "consumer.synthetic.siesta"


class Capability:
    def __init__(self, mode):
        self.mode = mode
        self.contexts = []

    def inspect_input(self, path):
        return path.read_text()

    def validate_input(self, inspected, **kwargs):
        return SimpleNamespace(status="PASS")

    def prepare_task(self, inspected, workspace, **kwargs):
        destination = workspace / "prepared.txt"
        kwargs["filesystem"].write_text(destination, inspected)
        return destination

    def build_command(self, input_path, **kwargs):
        if "controller_entrypoint" not in kwargs:
            return ("synthetic-siesta-only",)
        self.contexts.append(kwargs)
        executable = str(kwargs["controller_entrypoint"])
        if self.mode == "wrong-command":
            executable = "/not-the-installed-controller"
        return (executable, "--qraft-reservation", kwargs["controller_reservation_path"],
                "--mode", self.mode if self.mode != "wrong-command" else "runtime")

    def parse_output(self, lines, **kwargs):
        return "".join(lines)

    def discover_artifacts(self, workspace, **kwargs):
        return ()

    def classify_result(self, parsed, **kwargs):
        return TechnicalValidation("PASS", "SYNTHETIC_ONLY", (), {})


class OtherLauncher:
    def __init__(self):
        self.controller = None
        self.launches = []

    def launch(self, spec):
        runtime = self.controller.runtime
        assert "a-controller" not in runtime.coordinator.active_task_ids, "exclusive host reused before closure"
        self.launches.append(spec.task_id)
        spec.stdout_path.write_bytes(b"synthetic-only\n")
        spec.stderr_path.write_bytes(b"")
        return StepOutcome(spec.task_id, spec.attempt_id, (spec.executable,), 0, .01, False)

    def terminate_all(self, **kwargs):
        return ()


def prepare(root):
    source = root / "source"
    source.mkdir(parents=True)
    (source / "plan.json").write_bytes(b'{"scientific_policy":"synthetic-only"}\n')
    (source / "input.fdf").write_bytes(b"SystemLabel synthetic\n")
    tasks = []
    for name, capability, path in (("a-controller", CONTROLLER, "plan.json"), ("z-siesta", OTHER, "input.fdf")):
        tasks.append({"task_id": name, "kind": "calculation", "capability": capability,
                      "inputs": [{"name": "input", "source": path, "destination": path,
                                  "media_type": "application/json" if path.endswith("json") else "text/plain"}],
                      "outputs": [], "resources": {"nodes": 1, "mpi_processes": 1,
                      "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 1}})
    definition = source / "workflow.json"
    definition.write_text(json.dumps({"schema_version": "1.0", "workflow_id": "installed-controller",
                                      "project_id": "synthetic-fixture", "tasks": tasks}))
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid, compilation.diagnostics
    lock = source / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    profile = source / "profile.json"
    profile.write_text(json.dumps({
        "schema_version": "1.0", "profile_id": "synthetic", "target": "slurm",
        "slurm": {"partition": "synthetic", "account": None, "qos": None},
        "allocation": {"nodes": 1, "total_cpus": 8, "cpus_per_task": 1,
                       "memory": "1G", "walltime": "00:05:00", "max_parallel_steps": 2,
                       "shutdown_margin_seconds": 10, "termination_grace_seconds": 1},
        "runtime": {"module_commands": [], "siesta_executable": "never-executed-siesta",
                    "executable_arguments": [], "exclusive": True, "environment": {},
                    "launcher": {"kind": "openmpi", "command": ["/never-executed/mpirun"],
                                 "arguments": [], "bootstrap": "", "processes_per_node": 8}},
        "task_policy": {"max_attempts": 3, "require_scf_converged": True},
    }))

    def adapter(task, *, artifacts, resolved_sources, protected, **context):
        binding = task.inputs[0]
        artifact = artifacts[binding.external_artifact_id]
        relative = "protected/" + task.task_id + "/" + binding.destination
        protected[relative] = resolved_sources[artifact.artifact_id]
        record = {"task_id": task.task_id, "kind": "controller" if task.capability_id == CONTROLLER else "siesta",
                  "input": relative, "input_hashes": {relative: artifact.sha256},
                  "input_destinations": {relative: binding.destination}, "required_artifacts": [],
                  "optional_artifacts": [], "depends_on": [], "transfers": [],
                  "mpi_processes": 1, "cpus_per_process": 1, "nodes": 0,
                  "estimated_runtime_seconds": 1, "max_attempts": 3}
        if task.capability_id == CONTROLLER:
            record.update(capability_id=task.capability_id, reservation={"nodes": 1,
                          "inner_launcher": "openmpi", "inner_processes_per_node": 4,
                          "inner_cpus_per_process": 1, "max_concurrent_inner_launches": 1})
        return record

    result = RunPreparer(task_adapters={CONTROLLER: adapter, OTHER: adapter}).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=source, execution_profile=profile,
        output_root=root / "output", run_id="synthetic-controller"))
    assert not result.submission_performed and not result.execution_authorized
    return Path(result.package_path)


def controller(root, mode, *, observed_cpus="8", distribution="qraft-test-controller"):
    capability = Capability(mode)
    def register(registry):
        descriptor = CapabilityDescriptor(CONTROLLER, CapabilityKind.EXECUTABLE, "1.0.0",
            (EXECUTION_REQUEST,), (EXECUTION_EVIDENCE,), metadata={"qraft.controller": {
                "schema_version": "1.0", "distribution": distribution,
                "entrypoint": "qraft-test-controller", "inner_launchers": ["openmpi"], "resume": "NONE"}})
        other = CapabilityDescriptor(OTHER, CapabilityKind.EXECUTABLE, "1.0.0",
                                     (EXECUTION_REQUEST,), (EXECUTION_EVIDENCE,))
        registry.register(PluginDescriptor("consumer.runtime.plugin", "1.0.0", ContractVersion(1, 0),
                          (descriptor, other), "installed-test"), {CONTROLLER: capability, OTHER: Capability("other")})
    launcher = OtherLauncher()
    instance = CanonicalController.from_file(root / "campaign.yaml", launcher=launcher,
        register_capabilities=register, capability_bindings={"a-controller": CONTROLLER, "z-siesta": OTHER},
        environment={"SLURM_JOB_ID": "synthetic-only", "SLURM_SUBMIT_DIR": str(root),
                     "SLURM_JOB_END_TIME": str(time.time() + 300), "SLURM_NNODES": "1",
                     "SLURM_NTASKS": "8", "SLURM_CPUS_PER_TASK": "1", "SLURM_JOB_CPUS_PER_NODE": observed_cpus})
    # Only external MPI/placement observations are synthetic. Admission probes,
    # installed console, supervisor, leases and evidence run without replacements.
    instance._validate_runtime_compatibility = lambda: None
    instance._validate_runtime_placement = lambda: setattr(instance, "_validated_hosts", ("localhost",))
    launcher.controller = instance
    return instance, capability, launcher


def run_stopped(instance, *, kill_supervisor=False):
    ready = instance.root / "work/a-controller/attempt-0001/.qraft/runtime-controller-ready.json"
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(instance.run, install_signal_handlers=False)
        deadline = time.monotonic() + 15
        while not ready.exists():
            if future.done():
                raise AssertionError((future.result(), instance.runtime._state))
            if time.monotonic() > deadline:
                instance.shutdown.request("SIGTERM")
                raise AssertionError("controller did not reach its ready barrier")
            time.sleep(.01)
        lease = instance.runtime.coordinator
        assert lease.active_task_ids == ("a-controller",)
        assert lease.used_cpus == 8 and lease.used_nodes == 1
        if kill_supervisor:
            descriptor = read_controller_json(ready.with_name("controller-reservation.json"))
            PidfdSignals().signal_identity(ProcessIdentity(**descriptor["containment"]["supervisor"]), signal.SIGKILL)
        else:
            instance.shutdown.request("SIGTERM")
        assert future.result(timeout=15).value == "INTERRUPTED"
    if not kill_supervisor:
        instance.runtime.coordinator.assert_released()
    else:
        assert instance.runtime.coordinator.used_cpus == 8
        assert instance.runtime.coordinator.active_task_ids == ("a-controller",)
        return process_identity(read_controller_json(ready)["pid"])


def main():
    assert sys.flags.isolated and "PYTHONPATH" not in os.environ
    assert Path(qraft.__file__).is_relative_to(Path(sys.prefix))
    if len(sys.argv) == 3 and sys.argv[1] == "--crash-child":
        instance, _, _ = controller(Path(sys.argv[2]), "runtime-resume")
        instance.run(install_signal_handlers=False)
        raise AssertionError("the parent's crash barrier was not exercised")
    if os.name == "nt":
        with tempfile.TemporaryDirectory(prefix="qraft-windows-controller-") as directory:
            try:
                prepare(Path(directory))
            except ValueError as exc:
                assert "CONTROLLER_REQUIRES_POSIX" in str(exc), str(exc)
            else:
                raise AssertionError("Windows prepared a POSIX controller package")
            assert not (Path(directory) / "output").exists()
        print(json.dumps({"compiled_controller_runtime": "CONTROLLER_REQUIRES_POSIX", "scientific_job": False}))
        return
    with tempfile.TemporaryDirectory(prefix="qraft-compiled-controller-") as temporary:
        base = Path(temporary)
        root = prepare(base / "success")
        instance, capability, other = controller(root, "runtime")
        assert instance.run(install_signal_handlers=False).value == "COMPLETED", instance.runtime._state
        assert instance.result.peak_cpus == 8 and other.launches == ["z-siesta"]
        instance.runtime.coordinator.assert_released()
        descriptor = read_controller_json(root / "work/a-controller/attempt-0001/.qraft/controller-reservation.json")
        assert descriptor["reserved"]["runtime_cpus"] == 8 and descriptor["reserved"]["min_cpus"] == 4
        assert descriptor["reserved"]["hosts"] == ["localhost"]
        assert capability.contexts[0]["controller_prior_ledgers"] == ()
        for mode, expected in (("runtime-resume", "COMPLETED"), ("runtime-refuse", "BLOCKED")):
            root = prepare(base / mode)
            first, _, _ = controller(root, mode)
            run_stopped(first)
            second, cap, _ = controller(root, mode)
            assert second.run(install_signal_handlers=False).value == expected, second.runtime._state
            second.runtime.coordinator.assert_released()
            descriptor = read_controller_json(root / "work/a-controller/attempt-0002/.qraft/controller-reservation.json")
            assert descriptor["previous_attempt"]["closure"] == "CLOSED"
            assert descriptor["previous_attempt"]["attempt_id"] == "attempt-0001"
            assert len(cap.contexts[0]["controller_prior_ledgers"]) == 1
            if mode == "runtime-refuse":
                assert second.result.attempts["a-controller"].exit_code == 75
                assert second.result.attempts["a-controller"].result.execution_state == "BLOCKED"
        for mode in ("wrong-command", "runtime-badledger"):
            root = prepare(base / mode)
            instance, _, _ = controller(root, mode)
            assert instance.run(install_signal_handlers=False).value != "COMPLETED"
            instance.runtime.coordinator.assert_released()
            if mode == "wrong-command":
                assert not (root / "controller-state").exists()
            else:
                assert instance.result.attempts["a-controller"].result.technical_validation.classification == "CONTROLLER_LEDGER_INCONSISTENT"
        for name, cpu, distribution, code in (
            ("bad-observation", "7", "qraft-test-controller", "CONTROLLER_ALLOCATION_MISMATCH"),
            ("absent-entrypoint", "8", "nonexistent-test-controller", "CONTROLLER_ENTRYPOINT_MISSING"),
        ):
            root = prepare(base / name)
            instance, _, _ = controller(root, "runtime", observed_cpus=cpu, distribution=distribution)
            try:
                instance.run(install_signal_handlers=False)
            except ValueError as exc:
                assert code in str(exc), str(exc)
            else:
                raise AssertionError("invalid admission was accepted")
            assert not (root / "work").exists() and not (root / "controller-state").exists()
        root = prepare(base / "without-pidfd")
        instance, _, _ = controller(root, "runtime")
        with patch("qraft.execution.controller_admission.PidfdSignals", side_effect=ValueError("unavailable")):
            try:
                instance.run(install_signal_handlers=False)
            except ValueError as exc:
                assert "CONTROLLER_CONTAINMENT_UNAVAILABLE" in str(exc)
            else:
                raise AssertionError("controller ran without pidfd containment")
        assert not (root / "work").exists()
        root = prepare(base / "killed-supervisor")
        first, _, other = controller(root, "runtime-resume")
        orphan = run_stopped(first, kill_supervisor=True)
        try:
            assert not other.launches
            second, _, other = controller(root, "runtime-resume")
            assert second.run(install_signal_handlers=False).value == "INTERRUPTED"
            assert second.runtime._state["tasks"]["a-controller"]["status"] == "BLOCKED"
            assert second.runtime._state["tasks"]["a-controller"]["reason"] == "CONTROLLER_PREVIOUS_OWNER_ALIVE"
            assert second.runtime.coordinator.used_cpus == 8 and not other.launches
        finally:
            # Only the test's own previously recorded child is cleaned up. This
            # does not manufacture CLOSED or authorize a resume of its state.
            PidfdSignals().signal_identity(orphan, signal.SIGTERM)
        root = prepare(base / "killed-runtime")
        ready = root / "work/a-controller/attempt-0001/.qraft/runtime-controller-ready.json"
        with (base / "crashed-runtime.log").open("wb") as log:
            parent = subprocess.Popen([sys.executable, "-I", __file__, "--crash-child", str(root)],
                                      cwd=base, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            parent_identity = process_identity(parent.pid)
            supervisor = None
            try:
                deadline = time.monotonic() + 15
                while not ready.exists():
                    assert parent.poll() is None, (base / "crashed-runtime.log").read_text()
                    if time.monotonic() > deadline:
                        raise AssertionError("runtime crash fixture did not reach its own ready barrier")
                    time.sleep(.01)
                descriptor = read_controller_json(ready.with_name("controller-reservation.json"))
                supervisor = ProcessIdentity(**descriptor["containment"]["supervisor"])
                PidfdSignals().signal_identity(parent_identity, signal.SIGKILL)
                parent.wait(timeout=5)
                second, _, other = controller(root, "runtime-resume")
                assert second.run(install_signal_handlers=False).value == "INTERRUPTED"
                assert second.runtime._state["tasks"]["a-controller"]["reason"] == "CONTROLLER_PREVIOUS_OWNER_ALIVE"
                assert second.runtime.coordinator.used_cpus == 8 and not other.launches
            finally:
                if supervisor:
                    PidfdSignals().signal_identity(supervisor, signal.SIGTERM)
                    deadline = time.monotonic() + 15
                    while not ready.with_name("controller-closure.json").exists():
                        if time.monotonic() > deadline:
                            raise AssertionError("owned supervisor failed to close after parent crash")
                        time.sleep(.01)
                if parent.poll() is None:
                    parent.terminate()
                    parent.wait(timeout=5)
        # Its original supervisor sealed native state independently of the dead
        # runtime. The next invocation may now resume; it never starts afresh.
        third, _, _ = controller(root, "runtime-resume")
        assert third.run(install_signal_handlers=False).value == "COMPLETED", third.runtime._state
        third.runtime.coordinator.assert_released()
        print(json.dumps({"compiled_prepared_runtime": True, "peak_cpus": 8,
                          "exclusive_host": True, "closure_before_release": True,
                          "resume_closed": True, "resume_75_blocked": True,
                          "wrong_executable_veto": True, "ledger_veto": True,
                          "admission_before_reservation": True, "unknown_closure_retains_lease": True,
                          "new_invocation_preserves_unresolved_host": True,
                          "runtime_crash_blocks_until_native_closed": True, "scientific_job": False}))


if __name__ == "__main__":
    main()
