from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from qraft.contracts import (
    EXECUTION_EVIDENCE,
    EXECUTION_REQUEST,
    ArtifactReference,
    ArtifactRole,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRegistry,
    CompiledWorkflow,
    ContractVersion,
    PluginDescriptor,
    WorkflowInputBinding,
    WorkflowOutputPort,
    WorkflowTaskKind,
    WorkflowTaskNode,
)
from qraft.controller_package import ControllerPackageBuilder
from qraft.core import ExecutionSpec
from qraft.execution.allocation_controller import (
    AllocationController,
    HistoricalAllocationController,
    load_controller_config,
)
from qraft.execution.capability_runtime import CompiledWorkflowRuntime
from qraft.execution.legacy_translation import translate_controller_config
from qraft.execution.resource_coordinator import (
    CooperativeShutdown,
    RuntimeAllocation,
)
from qraft.execution.srun_launcher import StepLaunchSpec, StepOutcome

from tests.execution.test_capability_runtime import (
    OPAQUE_PASS,
    PASS_CAPABILITY,
    RecordingLauncher,
    SyntheticCapability,
    execution,
    identity,
    node,
    registry_for,
    runtime,
    workflow,
)
from tests.m4.test_allocation_controller import make_package
from tests.m4.test_controller_package import REPO, source_campaign


class BoundedProbeLauncher:
    def __init__(self, *, release_at: int = 2) -> None:
        self.release_at = release_at
        self.wave_ready = threading.Event()
        self.release_wave = threading.Event()
        self._lock = threading.Lock()
        self._active: dict[str, StepLaunchSpec] = {}
        self.max_active = 0
        self.used_cpus = 0
        self.max_cpus = 0
        self.launches: list[StepLaunchSpec] = []

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        with self._lock:
            self._active[spec.attempt_id + ":" + spec.task_id] = spec
            self.launches.append(spec)
            self.used_cpus += spec.allocated_cpus
            self.max_cpus = max(self.max_cpus, self.used_cpus)
            self.max_active = max(self.max_active, len(self._active))
            if len(self._active) >= self.release_at:
                self.wave_ready.set()
        if spec.task_id != "ROOT" and not self.release_wave.wait(5):
            raise RuntimeError("synchronized test wave was not released")
        spec.stdout_path.write_text(OPAQUE_PASS + "\n", encoding="utf-8")
        spec.stderr_path.write_text("", encoding="utf-8")
        (spec.workdir / "result.dat").write_text(
            f"{spec.task_id}:{spec.attempt_id}\n", encoding="utf-8"
        )
        with self._lock:
            self.used_cpus -= spec.allocated_cpus
            self._active.pop(spec.attempt_id + ":" + spec.task_id)
        return StepOutcome(
            spec.task_id,
            spec.attempt_id,
            (spec.executable, *spec.executable_arguments),
            0,
            0.0,
            False,
        )

    def terminate_all(self, *, kill: bool = False):
        with self._lock:
            return tuple(item.attempt_id for item in self._active.values())


class InterruptingLauncher:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.terminated = threading.Event()
        self._lock = threading.Lock()
        self._active: dict[str, StepLaunchSpec] = {}
        self.launches: list[StepLaunchSpec] = []

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        self.launches.append(spec)
        if spec.task_id == "A":
            spec.stdout_path.write_text(OPAQUE_PASS + "\n", encoding="utf-8")
            spec.stderr_path.write_text("", encoding="utf-8")
            (spec.workdir / "result.dat").write_text("A\n", encoding="utf-8")
            return StepOutcome(spec.task_id, spec.attempt_id, (), 0, 0.0, False)
        with self._lock:
            self._active[spec.attempt_id] = spec
        self.started.set()
        if not self.terminated.wait(5):
            raise RuntimeError("controlled termination was not delivered")
        spec.stdout_path.write_text("interrupted\n", encoding="utf-8")
        spec.stderr_path.write_text("", encoding="utf-8")
        with self._lock:
            self._active.pop(spec.attempt_id, None)
        return StepOutcome(spec.task_id, spec.attempt_id, (), 143, 0.0, True)

    def terminate_all(self, *, kill: bool = False):
        with self._lock:
            affected = tuple(self._active)
        self.terminated.set()
        return affected


def _run_in_thread(current: CompiledWorkflowRuntime):
    pool = ThreadPoolExecutor(max_workers=1)
    return pool, pool.submit(current.run)


def test_ready_tree_runs_with_exact_bounded_concurrency(tmp_path: Path):
    compiled = workflow(
        tmp_path,
        (
            node("ROOT"),
            node("A", dependencies=("ROOT",), source_task="ROOT"),
            node("B", dependencies=("ROOT",), source_task="ROOT"),
            node("C", dependencies=("ROOT",), source_task="ROOT"),
        ),
    )
    launcher = BoundedProbeLauncher()
    current = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in compiled.tasks},
        execution_specs=execution(),
        launcher=launcher,
        allocation=RuntimeAllocation(2, 2, max_parallel_steps=2),
    )
    pool, future = _run_in_thread(current)
    try:
        assert launcher.wave_ready.wait(5)
        assert launcher.max_active == 2
        launcher.release_wave.set()
        result = future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
    assert result.status == "COMPLETED"
    assert result.peak_parallel_steps == 2
    assert launcher.max_active == 2
    assert {item.task_id for item in launcher.launches} == {"ROOT", "A", "B", "C"}


def test_cpu_budget_waits_and_releases_without_overallocation(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"), node("B"), node("C")))
    specs = {"A": execution(ranks=6), "B": execution(ranks=6), "C": execution(ranks=2)}
    launcher = BoundedProbeLauncher()
    current = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in compiled.tasks},
        execution_specs=specs,
        launcher=launcher,
        allocation=RuntimeAllocation(8, 1, max_parallel_steps=3),
    )
    pool, future = _run_in_thread(current)
    try:
        assert launcher.wave_ready.wait(5)
        assert {item.task_id for item in launcher.launches[:2]} == {"A", "C"}
        assert launcher.max_cpus == 8
        launcher.release_wave.set()
        result = future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
    assert result.status == "COMPLETED"
    assert result.peak_cpus == 8
    assert launcher.max_cpus <= 8
    assert [item.task_id for item in launcher.launches][-1] == "B"
    assert current.coordinator.used_cpus == 0


def test_host_leases_are_exclusive_and_released(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"), node("B"), node("C")))
    hydra = ExecutionSpec(
        partition="allocation",
        nodes=1,
        mpi_ranks=1,
        cpus_per_rank=1,
        memory_mb=None,
        launcher="hydra",
        executable="synthetic",
        walltime_seconds=30,
    )
    launcher = BoundedProbeLauncher()
    current = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in compiled.tasks},
        execution_specs=hydra,
        launcher={"hydra": launcher},
        allocation=RuntimeAllocation(
            2, 2, max_parallel_steps=2, hosts=("node-a", "node-b")
        ),
    )
    pool, future = _run_in_thread(current)
    try:
        assert launcher.wave_ready.wait(5)
        first_hosts = [item.hosts for item in launcher.launches[:2]]
        assert first_hosts == [("node-a",), ("node-b",)]
        launcher.release_wave.set()
        assert future.result(timeout=5).status == "COMPLETED"
    finally:
        pool.shutdown(wait=True)
    assert launcher.launches[2].hosts in {("node-a",), ("node-b",)}
    assert current.coordinator.used_hosts == ()


def test_walltime_stop_is_resumable_and_completed_work_reuses(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"),))
    blocked_launcher = RecordingLauncher()
    first = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={"A": identity()},
        execution_specs=execution(),
        launcher=blocked_launcher,
        allocation=RuntimeAllocation(
            1,
            1,
            shutdown_margin_seconds=10,
            remaining_time=lambda: 70,
        ),
    ).run()
    assert first.status == "INTERRUPTED"
    assert blocked_launcher.launches == []
    state = (tmp_path / "run" / "state" / "workflow_runtime.json").read_text()
    assert '"attempts":0' in state and '"status":"PENDING"' in state

    resumed_launcher = RecordingLauncher()
    second_runtime = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={"A": identity()},
        execution_specs=execution(),
        launcher=resumed_launcher,
        allocation=RuntimeAllocation(1, 1, remaining_time=lambda: 120),
    )
    second = second_runtime.run()
    assert second.status == "COMPLETED"
    assert second.attempts["A"].attempt_id == "attempt-0001"

    reuse_launcher = RecordingLauncher()
    third = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={"A": identity()},
        execution_specs=execution(),
        launcher=reuse_launcher,
        allocation=RuntimeAllocation(1, 1, remaining_time=lambda: 120),
    ).run()
    assert third.status == "COMPLETED"
    assert third.reused_nodes == ("A",)
    assert reuse_launcher.launches == []


def test_controlled_interruption_resumes_only_unfinished_attempt(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"), node("B")))
    shutdown = CooperativeShutdown()
    launcher = InterruptingLauncher()
    first_runtime = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={"A": identity(), "B": identity()},
        execution_specs=execution(),
        launcher=launcher,
        allocation=RuntimeAllocation(2, 1, max_parallel_steps=2),
        shutdown=shutdown,
        poll_interval_seconds=0.001,
    )
    pool, future = _run_in_thread(first_runtime)
    try:
        assert launcher.started.wait(5)
        shutdown.request("SIGTERM")
        first = future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
    assert first.status == "INTERRUPTED"
    assert first.attempts["A"].result.execution_state == "COMPLETED"
    assert first.attempts["B"].result.execution_state == "INTERRUPTED"

    resumed_launcher = RecordingLauncher()
    second = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={"A": identity(), "B": identity()},
        execution_specs=execution(),
        launcher=resumed_launcher,
        allocation=RuntimeAllocation(2, 1, max_parallel_steps=2),
    ).run()
    assert second.status == "COMPLETED"
    assert second.reused_nodes == ("A",)
    assert [item.task_id for item in resumed_launcher.launches] == ["B"]
    assert second.attempts["B"].attempt_id == "attempt-0002"


class ExplicitInputCapability(SyntheticCapability):
    def __init__(self) -> None:
        super().__init__()
        self.inspected: list[str] = []

    def select_primary_input(self, **kwargs):
        return kwargs["settings"]["primary_input"]

    def inspect_input(self, path: Path):
        value = path.read_text(encoding="utf-8")
        self.inspected.append(value)
        return value


@pytest.mark.parametrize(
    ("parameter_name", "geometry_name"),
    (("a_parameters", "z_geometry"), ("z_parameters", "a_geometry")),
)
def test_multi_input_primary_is_capability_owned_not_alphabetical(
    tmp_path: Path, parameter_name: str, geometry_name: str
):
    root = tmp_path / f"{parameter_name}-{geometry_name}"
    root.mkdir()
    parameter = root / "parameters.dat"
    geometry = root / "geometry.dat"
    parameter.write_text("PARAMETERS", encoding="utf-8")
    geometry.write_text("GEOMETRY", encoding="utf-8")
    artifacts = tuple(
        ArtifactReference(
            artifact_id=name,
            role=ArtifactRole.INPUT,
            relative_path=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size_bytes=path.stat().st_size,
            media_type="text/plain",
        )
        for name, path in ((parameter_name, parameter), (geometry_name, geometry))
    )
    task = WorkflowTaskNode(
        task_id="multi",
        kind=WorkflowTaskKind.CALCULATION,
        capability_id=PASS_CAPABILITY,
        dependencies=(),
        inputs=(
            WorkflowInputBinding(
                parameter_name,
                "parameters.dat",
                "text/plain",
                external_artifact_id=parameter_name,
            ),
            WorkflowInputBinding(
                geometry_name,
                "geometry.dat",
                "text/plain",
                external_artifact_id=geometry_name,
            ),
        ),
        outputs=(
            WorkflowOutputPort(
                "result", "result.dat", "org.example.result", "text/plain"
            ),
        ),
        resources={"max_attempts": 1},
        settings={"primary_input": geometry_name},
    )
    compiled = CompiledWorkflow(
        "multi-input",
        "multi-project",
        "3" * 64,
        (task,),
        (),
        artifacts,
    )
    capability = ExplicitInputCapability()
    result = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(capability),
        root=root / "run",
        source_root=root,
        scientific_identities={"multi": identity()},
        execution_specs=execution(),
        launcher=RecordingLauncher(),
    ).run()
    assert result.status == "COMPLETED"
    assert capability.inspected == ["GEOMETRY", "GEOMETRY"]


def test_second_engine_registration_requires_no_runtime_edit(tmp_path: Path):
    runtime_source = REPO / "src/qraft/execution/capability_runtime.py"
    before = hashlib.sha256(runtime_source.read_bytes()).hexdigest()
    second_id = "org.example.engine.second"
    descriptors = tuple(
        CapabilityDescriptor(
            capability_id=capability_id,
            kind=CapabilityKind.ENGINE,
            implementation_version="1.0.0",
            input_contracts=(EXECUTION_REQUEST,),
            output_contracts=(EXECUTION_EVIDENCE,),
        )
        for capability_id in (PASS_CAPABILITY, second_id)
    )
    plugin = PluginDescriptor(
        "org.example.plugin.two-engines",
        "1.0.0",
        ContractVersion(1, 0),
        descriptors,
        "tests",
    )
    registry = CapabilityRegistry()
    registry.register(
        plugin,
        {PASS_CAPABILITY: SyntheticCapability(), second_id: SyntheticCapability()},
    )
    registry.freeze()
    compiled = workflow(tmp_path, (node("SECOND", capability=second_id),))
    result = runtime(tmp_path, compiled, registry, RecordingLauncher()).run()
    assert result.status == "COMPLETED"
    assert hashlib.sha256(runtime_source.read_bytes()).hexdigest() == before


def test_legacy_config_translates_to_compiled_workflow_and_execution_spec(
    tmp_path: Path,
):
    campaign, _ = make_package(tmp_path, ["SUCCESS"], total_cpus=2)
    config = load_controller_config(campaign)
    plan = translate_controller_config(config, root=tmp_path)
    assert isinstance(plan.workflow, CompiledWorkflow)
    assert plan.workflow.tasks[0].capability_id == "siestaflow.engine.siesta"
    assert plan.workflow.tasks[0].settings["primary_input"] == "primary"
    assert plan.execution_specs["task-1"].allocated_cpus == 1
    assert plan.scientific_identities["task-1"].fingerprint


def test_new_package_worker_targets_canonical_runtime(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(source)
    output = tmp_path / "output"
    output.mkdir()
    result = ControllerPackageBuilder(REPO).build(campaign, output)
    package = Path(result.destination)
    worker = (package / "scripts/run_worker.py").read_text(encoding="utf-8")
    manifest = (package / "manifest.json").read_text(encoding="utf-8")
    assert "CanonicalController.from_file" in worker
    assert "AllocationController.from_file" not in worker
    assert '"execution_authority": "CompiledWorkflowRuntime"' in manifest
    assert '"legacy_scheduler_default": false' in manifest
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import pathlib,sys; "
                f"runtime=pathlib.Path({str(package / 'runtime')!r}); "
                "sys.path.insert(0,str(runtime)); "
                "from qraft.execution.canonical_controller import CanonicalController; "
                "assert runtime in pathlib.Path(sys.modules['qraft'].__file__).parents; "
                "print('SELF_CONTAINED_CANONICAL_IMPORT_PASS')"
            ),
        ],
        cwd=package,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr


def test_historical_controller_is_explicit_compatibility_boundary():
    assert AllocationController is HistoricalAllocationController
    facade = (REPO / "src/qraft/execution/allocation_controller.py").read_text()
    assert "Backward-compatible import only" in facade
    assert "CanonicalController" in facade


def test_architecture_has_one_default_production_runtime_and_no_engine_logic():
    runtime_source = (REPO / "src/qraft/execution/capability_runtime.py").read_text()
    resource_source = (REPO / "src/qraft/execution/resource_coordinator.py").read_text()
    cli_source = (REPO / "src/qraft/cli.py").read_text()
    package_source = (REPO / "src/qraft/controller_package.py").read_text()
    for forbidden in (
        "SiestaOutputParser",
        "engines.siesta",
        'engine == "siesta"',
        'task_kind == "siesta"',
        "require_scf_converged",
        "inputs[sorted(inputs)[0]]",
    ):
        assert forbidden not in runtime_source
        assert forbidden not in resource_source
    assert "CanonicalController.from_file" in cli_source
    assert "AllocationController.from_file" not in cli_source
    assert "CanonicalController.from_file" in package_source
    assert "AllocationController.from_file(campaign" not in package_source
