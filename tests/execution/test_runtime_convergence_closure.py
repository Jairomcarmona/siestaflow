from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
from qraft.core import ExecutionSpec, TechnicalValidation
from qraft.engines.siesta.adapter import SiestaEngineAdapter, SyntheticSiestaLauncher
from qraft.execution.allocation_controller import (
    AllocationController,
    HistoricalAllocationController,
    load_controller_config,
)
from qraft.execution.capability_runtime import CompiledWorkflowRuntime
from qraft.execution.legacy_translation import translate_controller_config
from qraft.execution.resource_coordinator import (
    CooperativeShutdown,
    ResourceCoordinator,
    ResourceRequest,
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


class RestartCapability(SyntheticCapability):
    def mutable_input_names(self, **kwargs):
        bindings = dict(kwargs.get("bindings", {}))
        return tuple(
            name
            for name, binding in bindings.items()
            if binding.source_task_id is not None
        )

    def classify_result(self, parsed, **kwargs):
        self.classifications += 1
        if OPAQUE_PASS in parsed:
            return TechnicalValidation(
                "PASS",
                "SYNTHETIC_ACCEPTED",
                ("capability accepted opaque output",),
                {"opaque": parsed},
            )
        return TechnicalValidation(
            "FAIL",
            "SYNTHETIC_REJECTED",
            ("capability rejected opaque output",),
            {"opaque": parsed},
        )

    def validate_consumed_inputs(self, parsed, **kwargs):
        classified = kwargs["classified"]
        if "RESTART_CONSUMED" in parsed:
            return classified
        return TechnicalValidation(
            "FAIL",
            "RESTART_INPUT_NOT_CONSUMED",
            ("synthetic capability did not confirm restart consumption",),
            {"opaque": parsed},
        )


class RestartMutationLauncher:
    def __init__(self, *, confirms_consumption: bool = True) -> None:
        self.confirms_consumption = confirms_consumption
        self.launches: list[StepLaunchSpec] = []
        self.restart_before: str | None = None
        self.restart_after: str | None = None

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        self.launches.append(spec)
        if spec.task_id == "B":
            restart = spec.workdir / "restart.bin"
            self.restart_before = hashlib.sha256(restart.read_bytes()).hexdigest()
            restart.write_bytes(restart.read_bytes() + b"mutated by engine\n")
            self.restart_after = hashlib.sha256(restart.read_bytes()).hexdigest()
        output = OPAQUE_PASS
        if spec.task_id == "B" and self.confirms_consumption:
            output += "\nRESTART_CONSUMED"
        spec.stdout_path.write_text(output + "\n", encoding="utf-8")
        spec.stderr_path.write_text("", encoding="utf-8")
        (spec.workdir / "result.dat").write_text(
            f"artifact:{spec.task_id}:{spec.attempt_id}\n", encoding="utf-8"
        )
        return StepOutcome(
            spec.task_id,
            spec.attempt_id,
            (spec.executable, *spec.executable_arguments),
            0,
            0.01,
            False,
        )

    def terminate_all(self, *, kill: bool = False):
        return ()


def _run_in_thread(current: CompiledWorkflowRuntime):
    pool = ThreadPoolExecutor(max_workers=1)
    return pool, pool.submit(current.run)


def _restart_workflow(root: Path) -> CompiledWorkflow:
    parent = node("A")
    child = replace(
        node("B", dependencies=("A",), source_task="A"),
        inputs=(
            WorkflowInputBinding(
                "input",
                "restart.bin",
                "text/plain",
                source_task_id="A",
                source_output_name="result",
            ),
        ),
    )
    return workflow(root, (parent, child))


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
        allocation=RuntimeAllocation(8, 2, max_parallel_steps=3),
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


def test_node_capacity_prevents_overallocation_and_releases():
    coordinator = ResourceCoordinator(RuntimeAllocation(32, 2, max_parallel_steps=4))
    first = coordinator.try_acquire(ResourceRequest("A", cpus=4, nodes=2))
    assert first is not None
    assert coordinator.try_acquire(ResourceRequest("B", cpus=4, nodes=2)) is None
    assert coordinator.used_nodes == coordinator.peak_nodes == 2
    coordinator.release(first)

    second = coordinator.try_acquire(ResourceRequest("B", cpus=4, nodes=2))
    assert second is not None
    coordinator.release(second)
    coordinator.assert_released()
    assert coordinator.used_nodes == 0
    assert coordinator.used_cpus == 0
    assert coordinator.used_hosts == ()


def test_nonexclusive_single_node_tasks_share_one_physical_node_and_release():
    coordinator = ResourceCoordinator(RuntimeAllocation(16, 1, max_parallel_steps=4))
    leases = [
        coordinator.try_acquire(ResourceRequest(task_id, cpus=4, nodes=1))
        for task_id in ("A", "B", "C", "D")
    ]
    assert all(leases)
    assert coordinator.used_cpus == coordinator.peak_cpus == 16
    assert coordinator.used_nodes == coordinator.peak_nodes == 1
    assert coordinator.peak_steps == 4
    assert coordinator.try_acquire(ResourceRequest("E", cpus=4, nodes=1)) is None
    for lease in leases:
        coordinator.release(lease)
    coordinator.assert_released()
    assert coordinator.used_cpus == coordinator.used_nodes == 0


def test_exclusive_hosts_remain_unshareable_with_shared_single_node_tasks():
    coordinator = ResourceCoordinator(
        RuntimeAllocation(16, 1, max_parallel_steps=4, hosts=("node-1",))
    )
    shared = coordinator.try_acquire(ResourceRequest("shared", cpus=4, nodes=1))
    assert shared is not None
    assert coordinator.try_acquire(
        ResourceRequest("exclusive", cpus=4, nodes=1, exclusive_hosts=True)
    ) is None
    coordinator.release(shared)

    exclusive = coordinator.try_acquire(
        ResourceRequest("exclusive", cpus=4, nodes=1, exclusive_hosts=True)
    )
    assert exclusive is not None and exclusive.hosts == ("node-1",)
    assert coordinator.try_acquire(ResourceRequest("shared", cpus=4, nodes=1)) is None
    coordinator.release(exclusive)
    coordinator.assert_released()


def test_cpu_and_node_limits_are_independently_enforced():
    node_bound = ResourceCoordinator(RuntimeAllocation(32, 2, max_parallel_steps=4))
    node_lease = node_bound.try_acquire(ResourceRequest("A", cpus=1, nodes=2))
    assert node_lease is not None
    assert node_bound.try_acquire(ResourceRequest("B", cpus=1, nodes=1)) is None
    node_bound.release(node_lease)
    node_bound.assert_released()

    cpu_bound = ResourceCoordinator(RuntimeAllocation(4, 2, max_parallel_steps=4))
    cpu_lease = cpu_bound.try_acquire(ResourceRequest("A", cpus=4, nodes=1))
    assert cpu_lease is not None
    assert cpu_bound.try_acquire(ResourceRequest("B", cpus=1, nodes=1)) is None
    cpu_bound.release(cpu_lease)
    cpu_bound.assert_released()


def test_mutable_restart_keeps_immutable_evidence_and_reuses(tmp_path: Path):
    compiled = _restart_workflow(tmp_path)
    capability = RestartCapability()
    first_launcher = RestartMutationLauncher()
    first_runtime = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(capability),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in compiled.tasks},
        execution_specs=execution(),
        launcher=first_launcher,
    )
    first = first_runtime.run()
    assert first.status == "COMPLETED"
    assert first_launcher.restart_before != first_launcher.restart_after

    attempt_root = tmp_path / "run" / "work" / "B" / "attempt-0001"
    payload = json.loads((attempt_root / "attempt.json").read_text())["payload"]
    evidence_relative, evidence_hash = next(iter(payload["input_evidence"].items()))
    assert evidence_relative.startswith(".qraft/input-evidence/")
    assert hashlib.sha256((attempt_root / evidence_relative).read_bytes()).hexdigest() == evidence_hash
    assert hashlib.sha256((attempt_root / "restart.bin").read_bytes()).hexdigest() != evidence_hash
    assert payload["mutable_inputs"] == ["input"]
    assert "restart.bin" not in payload["working_input_evidence"]

    reuse_launcher = RestartMutationLauncher()
    reused = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(RestartCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in compiled.tasks},
        execution_specs=execution(),
        launcher=reuse_launcher,
    ).run()
    assert reused.status == "COMPLETED"
    assert reused.reused_nodes == ("A", "B")
    assert reuse_launcher.launches == []


@pytest.mark.parametrize("tamper_target", ["immutable", "parent-source"])
def test_mutable_restart_tamper_rejects_reuse(tmp_path: Path, tamper_target: str):
    compiled = _restart_workflow(tmp_path)
    common = {
        "workflow": compiled,
        "root": tmp_path / "run",
        "source_root": tmp_path,
        "scientific_identities": {
            task.task_id: identity() for task in compiled.tasks
        },
        "execution_specs": execution(),
    }
    first_launcher = RestartMutationLauncher()
    first = CompiledWorkflowRuntime(
        registry=registry_for(RestartCapability()),
        launcher=first_launcher,
        **common,
    ).run()
    assert first.status == "COMPLETED"

    if tamper_target == "immutable":
        child_root = tmp_path / "run" / "work" / "B" / "attempt-0001"
        payload = json.loads((child_root / "attempt.json").read_text())["payload"]
        evidence_relative = next(iter(payload["input_evidence"]))
        (child_root / evidence_relative).write_bytes(b"tampered immutable evidence\n")
    else:
        parent_artifact = tmp_path / "run" / "work" / "A" / "attempt-0001" / "result.dat"
        parent_artifact.write_bytes(b"tampered parent source\n")

    retry_launcher = RestartMutationLauncher()
    retried = CompiledWorkflowRuntime(
        registry=registry_for(RestartCapability()),
        launcher=retry_launcher,
        **common,
    ).run()
    assert retried.status == "COMPLETED"
    assert "B" not in retried.reused_nodes
    assert any(item.task_id == "B" for item in retry_launcher.launches)


def test_siesta_capability_rejects_unconfirmed_restart_consumption():
    adapter = SiestaEngineAdapter()
    binding = WorkflowInputBinding(
        "restart",
        "seed.DM",
        "application/octet-stream",
        source_task_id="A",
        source_output_name="density",
    )
    assert adapter.mutable_input_names(bindings={"restart": binding}) == ("restart",)

    without_confirmation = adapter.parse_output(
        SyntheticSiestaLauncher.normal_output("B").splitlines(keepends=True),
        settings={"synthetic": True},
    )
    classified = adapter.classify_result(without_confirmation)
    assert classified.status == "PASS"
    rejected = adapter.validate_consumed_inputs(
        without_confirmation,
        classified=classified,
        mutable_inputs=("restart",),
    )
    assert rejected.status == "FAIL"
    assert rejected.classification == "RESTART_INPUT_NOT_CONSUMED"

    confirmed_text = (
        "Attempting to read DM from file succeeded\n"
        + SyntheticSiestaLauncher.normal_output("B")
    )
    confirmed = adapter.parse_output(
        confirmed_text.splitlines(keepends=True), settings={"synthetic": True}
    )
    accepted = adapter.validate_consumed_inputs(
        confirmed,
        classified=adapter.classify_result(confirmed),
        mutable_inputs=("restart",),
    )
    assert accepted.status == "PASS"


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
        assert len(first_hosts) == 2
        assert all(hosts in {("node-a",), ("node-b",)} for hosts in first_hosts)
        assert len(set(first_hosts)) == 2
        assert set(current.coordinator.used_hosts) == {"node-a", "node-b"}
        assert len(current.coordinator.active_task_ids) == 2
        launcher.release_wave.set()
        assert future.result(timeout=5).status == "COMPLETED"
    finally:
        pool.shutdown(wait=True)
    assert launcher.launches[2].hosts in {("node-a",), ("node-b",)}
    assert current.coordinator.used_hosts == ()
    assert current.coordinator.active_task_ids == ()
    current.coordinator.assert_released()


def test_walltime_stop_is_resumable_and_completed_work_reuses(tmp_path: Path):
    task = node("A")
    compiled = workflow(tmp_path, (replace(
        task,
        resources={**task.resources, "estimated_runtime_seconds": 60},
    ),))
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


def test_unknown_runtime_estimate_does_not_become_allocation_walltime(
    tmp_path: Path,
) -> None:
    compiled = workflow(tmp_path, (node("A"),))
    launcher = RecordingLauncher()
    result = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={"A": identity()},
        execution_specs=execution(),
        launcher=launcher,
        allocation=RuntimeAllocation(
            1,
            1,
            shutdown_margin_seconds=10,
            remaining_time=lambda: 59,
        ),
    ).run()
    assert result.status == "COMPLETED"
    assert [item.task_id for item in launcher.launches] == ["A"]


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


def test_legacy_scientific_identity_ignores_task_rename(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS"], total_cpus=2)
    config = load_controller_config(campaign)
    original = config.tasks[0]
    renamed = replace(original, task_id="point-B")
    renamed_config = replace(config, tasks=(renamed,))

    first = translate_controller_config(config, root=tmp_path)
    second = translate_controller_config(renamed_config, root=tmp_path)

    assert (
        first.scientific_identities[original.task_id].fingerprint
        == second.scientific_identities[renamed.task_id].fingerprint
    )


def test_legacy_execution_changes_do_not_change_scientific_identity(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS"], total_cpus=8)
    config = load_controller_config(campaign)
    original = config.tasks[0]
    relocated = replace(original, mpi_processes=4, nodes=2)
    relocated_config = replace(config, tasks=(relocated,), launcher_kind="mpiexec")

    first = translate_controller_config(config, root=tmp_path)
    second = translate_controller_config(relocated_config, root=tmp_path)

    assert (
        first.scientific_identities[original.task_id].fingerprint
        == second.scientific_identities[original.task_id].fingerprint
    )
    assert (
        first.execution_specs[original.task_id].fingerprint
        != second.execution_specs[original.task_id].fingerprint
    )


def test_legacy_scientific_identity_changes_with_protected_input(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS"], total_cpus=2)
    config = load_controller_config(campaign)
    original = config.tasks[0]
    first = translate_controller_config(config, root=tmp_path)

    input_path = tmp_path / original.input_path
    input_path.write_bytes(input_path.read_bytes() + b"scientific mutation\n")
    mutated_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    mutated = replace(
        original,
        input_hashes={**original.input_hashes, original.input_path: mutated_hash},
    )
    second = translate_controller_config(replace(config, tasks=(mutated,)), root=tmp_path)

    assert (
        first.scientific_identities[original.task_id].fingerprint
        != second.scientific_identities[original.task_id].fingerprint
    )


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
    assert (package / "runtime/qraft/magnetism.py").is_file()
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
        '".DM"',
        "dm_restart",
    ):
        assert forbidden not in runtime_source
        assert forbidden not in resource_source
    assert "CanonicalController.from_file" in cli_source
    assert "AllocationController.from_file" not in cli_source
    assert "CanonicalController.from_file" in package_source
    assert "AllocationController.from_file(campaign" not in package_source
