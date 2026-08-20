from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from qraft.contracts import (
    ARTIFACT_REFERENCE,
    EXECUTION_EVIDENCE,
    EXECUTION_REQUEST,
    VALIDATION_REPORT,
    ArtifactReference,
    ArtifactRole,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRegistry,
    CompiledWorkflow,
    ContractVersion,
    PluginDescriptor,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowInputBinding,
    WorkflowOutputPort,
    WorkflowTaskKind,
    WorkflowTaskNode,
)
from qraft.core import ExecutionSpec, ScientificIdentity, TechnicalValidation
from qraft.engines.siesta.adapter import SiestaEngineAdapter
from qraft.execution.capability_plugins import (
    SIESTA_ENGINE_CAPABILITY,
    register_siesta_engine,
)
from qraft.execution.capability_runtime import CompiledWorkflowRuntime
from qraft.execution.srun_launcher import StepLaunchSpec, StepOutcome


PASS_CAPABILITY = "org.example.engine.synthetic"
OPAQUE_PASS = "opaque::runtime-cannot-interpret::accepted"
OPAQUE_FAIL = "opaque::runtime-cannot-interpret::rejected"


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class SyntheticCapability:
    def __init__(self) -> None:
        self.parses = 0
        self.classifications = 0

    def inspect_input(self, path: Path):
        return path.read_text(encoding="utf-8")

    def validate_input(self, inspected, **kwargs):
        return SimpleNamespace(status="PASS")

    def prepare_task(self, inspected, workspace: Path, **kwargs):
        destination = workspace / "prepared.in"
        kwargs["filesystem"].write_text(destination, str(inspected))
        return destination

    def build_command(self, input_path: Path, **kwargs):
        return ("synthetic-capability", str(input_path))

    def parse_output(self, lines, **kwargs):
        self.parses += 1
        return "".join(lines).strip()

    def discover_artifacts(self, workspace: Path, **kwargs):
        result = workspace / "result.dat"
        if not result.is_file():
            return ()
        return (
            SimpleNamespace(
                path="result.dat",
                sha256=hashlib.sha256(result.read_bytes()).hexdigest(),
            ),
        )

    def classify_result(self, parsed, **kwargs):
        self.classifications += 1
        if parsed == OPAQUE_PASS:
            return TechnicalValidation("PASS", "SYNTHETIC_ACCEPTED", ("capability accepted opaque output",), {"opaque": parsed})
        return TechnicalValidation("FAIL", "SYNTHETIC_REJECTED", ("capability rejected opaque output",), {"opaque": parsed})


class RecordingLauncher:
    def __init__(self, outcomes: dict[str, list[tuple[str, int, bool, bool]]] | None = None) -> None:
        self.outcomes = {key: list(value) for key, value in (outcomes or {}).items()}
        self.launches: list[StepLaunchSpec] = []

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        self.launches.append(spec)
        queue = self.outcomes.setdefault(spec.task_id, [])
        if not queue:
            queue.append((OPAQUE_PASS, 0, False, True))
        output, exit_code, interrupted, artifact = queue.pop(0)
        spec.stdout_path.write_text(output + "\n", encoding="utf-8")
        spec.stderr_path.write_text("", encoding="utf-8")
        if artifact:
            (spec.workdir / "result.dat").write_text(
                f"artifact:{spec.task_id}:{spec.attempt_id}\n", encoding="utf-8"
            )
        return StepOutcome(
            spec.task_id,
            spec.attempt_id,
            (spec.executable, *spec.executable_arguments),
            exit_code,
            0.01,
            interrupted,
        )

    def terminate_all(self, *, kill: bool = False):
        return ()


def registry_for(capability: object, *, compatible: bool = True) -> CapabilityRegistry:
    inputs = (EXECUTION_REQUEST,) if compatible else (VALIDATION_REPORT,)
    outputs = (EXECUTION_EVIDENCE,) if compatible else (ARTIFACT_REFERENCE,)
    descriptor = CapabilityDescriptor(
        capability_id=PASS_CAPABILITY,
        kind=CapabilityKind.ENGINE,
        implementation_version="1.0.0",
        input_contracts=inputs,
        output_contracts=outputs,
    )
    plugin = PluginDescriptor(
        plugin_id="org.example.plugin.synthetic",
        plugin_version="1.0.0",
        core_contract_version=ContractVersion(1, 0),
        capabilities=(descriptor,),
        provider="tests",
    )
    registry = CapabilityRegistry()
    registry.register(plugin, {PASS_CAPABILITY: capability})
    registry.freeze()
    return registry


def identity() -> ScientificIdentity:
    digest = "a" * 64
    return ScientificIdentity(
        engine="synthetic",
        effective_fdf_sha256=digest,
        geometry_sha256="b" * 64,
        species_mapping_sha256="c" * 64,
        pseudopotentials={"X": "d" * 64},
        components={"settings": "e" * 64},
        included_scientific_files={},
    )


def execution(*, ranks: int = 1) -> ExecutionSpec:
    return ExecutionSpec(
        partition="local",
        nodes=1,
        mpi_ranks=ranks,
        cpus_per_rank=1,
        memory_mb=128,
        launcher="fixture",
        executable="synthetic-capability",
        walltime_seconds=60,
    )


def external(root: Path, text: str = "input\n") -> ArtifactReference:
    path = root / "input.dat"
    path.write_text(text, encoding="utf-8")
    return ArtifactReference(
        artifact_id="input-main",
        role=ArtifactRole.INPUT,
        relative_path="input.dat",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
        media_type="text/plain",
    )


def node(
    task_id: str,
    *,
    capability: str = PASS_CAPABILITY,
    dependencies: tuple[str, ...] = (),
    source_task: str | None = None,
) -> WorkflowTaskNode:
    binding = (
        WorkflowInputBinding(
            "input",
            "input.dat",
            "text/plain",
            source_task_id=source_task,
            source_output_name="result",
        )
        if source_task
        else WorkflowInputBinding(
            "input", "input.dat", "text/plain", external_artifact_id="input-main"
        )
    )
    return WorkflowTaskNode(
        task_id=task_id,
        kind=WorkflowTaskKind.CALCULATION,
        capability_id=capability,
        dependencies=dependencies,
        inputs=(binding,),
        outputs=(
            WorkflowOutputPort(
                "result",
                "result.dat",
                "org.example.synthetic-result",
                "text/plain",
            ),
        ),
        resources={"max_attempts": 2},
    )


def workflow(root: Path, tasks: tuple[WorkflowTaskNode, ...]) -> CompiledWorkflow:
    artifact = external(root)
    edges = tuple(
        WorkflowEdge(
            source_task_id=str(task.inputs[0].source_task_id),
            target_task_id=task.task_id,
            kind=WorkflowEdgeKind.ARTIFACT,
            source_output_name="result",
            target_input_name="input",
        )
        for task in tasks
        if task.inputs[0].source_task_id is not None
    )
    return CompiledWorkflow(
        workflow_id="m1-runtime",
        project_id="m1-project",
        definition_sha256="1" * 64,
        tasks=tasks,
        edges=edges,
        external_artifacts=(artifact,),
    )


def runtime(
    tmp_path: Path,
    compiled: CompiledWorkflow,
    registry: CapabilityRegistry,
    launcher: RecordingLauncher,
) -> CompiledWorkflowRuntime:
    return CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry,
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in compiled.tasks},
        execution_specs=execution(),
        launcher=launcher,
    )


def test_registry_executes_synthetic_compiled_node_with_one_attempt(tmp_path: Path):
    capability = SyntheticCapability()
    launcher = RecordingLauncher()
    compiled = workflow(tmp_path, (node("A"),))
    result = runtime(tmp_path, compiled, registry_for(capability), launcher).run()
    assert result.status == "COMPLETED"
    assert result.node_results["A"].technical_validation.classification == "SYNTHETIC_ACCEPTED"
    assert result.attempts["A"].attempt_id == "attempt-0001"
    assert capability.parses == capability.classifications == 1
    assert len(launcher.launches) == 1


def test_unknown_capability_blocks_before_attempt_or_launch(tmp_path: Path):
    launcher = RecordingLauncher()
    compiled = workflow(tmp_path, (node("A", capability="org.example.missing"),))
    result = runtime(
        tmp_path, compiled, registry_for(SyntheticCapability()), launcher
    ).run()
    assert result.status == "BLOCKED"
    assert not launcher.launches
    state = (tmp_path / "run" / "state" / "workflow_runtime.json").read_text()
    assert "unknown capability: org.example.missing" in state
    assert not (tmp_path / "run" / "work" / "A").exists()


def test_contract_incompatibility_blocks_before_attempt_or_launch(tmp_path: Path):
    launcher = RecordingLauncher()
    compiled = workflow(tmp_path, (node("A"),))
    result = runtime(
        tmp_path,
        compiled,
        registry_for(SyntheticCapability(), compatible=False),
        launcher,
    ).run()
    assert result.status == "BLOCKED"
    assert not launcher.launches
    assert not (tmp_path / "run" / "work" / "A").exists()


def test_capability_classification_controls_opaque_failure_and_sibling_continues(tmp_path: Path):
    tasks = (
        node("A"),
        node("C"),
        node("B", dependencies=("A",), source_task="A"),
    )
    compiled = workflow(tmp_path, tasks)
    launcher = RecordingLauncher(
        {
            "A": [(OPAQUE_FAIL, 0, False, True)],
            "C": [(OPAQUE_PASS, 0, False, True)],
        }
    )
    result = runtime(
        tmp_path, compiled, registry_for(SyntheticCapability()), launcher
    ).run()
    assert result.status == "FAILED"
    assert result.node_results["A"].execution_state == "FAILED"
    assert result.node_results["C"].execution_state == "COMPLETED"
    assert [item.task_id for item in launcher.launches] == ["A", "C"]
    state = __import__("json").loads(
        (tmp_path / "run" / "state" / "workflow_runtime.json").read_text()
    )["payload"]["tasks"]
    assert state["B"]["status"] == "BLOCKED"


def test_missing_required_artifact_fails_and_blocks_consumer(tmp_path: Path):
    compiled = workflow(
        tmp_path, (node("A"), node("B", dependencies=("A",), source_task="A"))
    )
    launcher = RecordingLauncher({"A": [(OPAQUE_PASS, 0, False, False)]})
    result = runtime(
        tmp_path, compiled, registry_for(SyntheticCapability()), launcher
    ).run()
    assert result.node_results["A"].technical_validation.classification == "REQUIRED_ARTIFACT_MISSING"
    assert [item.task_id for item in launcher.launches] == ["A"]


def test_tampered_parent_artifact_prevents_consumer_launch(tmp_path: Path):
    compiled = workflow(
        tmp_path, (node("A"), node("B", dependencies=("A",), source_task="A"))
    )
    launcher = RecordingLauncher()

    class TamperingRuntime(CompiledWorkflowRuntime):
        def _execute_task(self, task):
            super()._execute_task(task)
            if task.task_id == "A" and self._state["tasks"]["A"]["status"] == "COMPLETED":
                (self.root / "work" / "A" / "attempt-0001" / "result.dat").write_text(
                    "tampered", encoding="utf-8"
                )

    current = TamperingRuntime(
        workflow=compiled,
        registry=registry_for(SyntheticCapability()),
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in compiled.tasks},
        execution_specs=execution(),
        launcher=launcher,
    )
    result = current.run()
    assert result.status == "BLOCKED"
    assert [item.task_id for item in launcher.launches] == ["A"]


def test_interrupted_attempt_retries_without_overwriting(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"),))
    launcher = RecordingLauncher(
        {"A": [(OPAQUE_PASS, 0, True, True), (OPAQUE_PASS, 0, False, True)]}
    )
    registry = registry_for(SyntheticCapability())
    first = runtime(tmp_path, compiled, registry, launcher).run()
    assert first.status == "INTERRUPTED"
    second = runtime(tmp_path, compiled, registry, launcher).run()
    assert second.status == "COMPLETED"
    assert second.attempts["A"].attempt_id == "attempt-0002"
    assert (tmp_path / "run" / "work" / "A" / "attempt-0001" / "attempt.json").is_file()


def test_valid_attempt_is_reused_without_relaunch(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"),))
    launcher = RecordingLauncher()
    registry = registry_for(SyntheticCapability())
    assert runtime(tmp_path, compiled, registry, launcher).run().status == "COMPLETED"
    second = runtime(tmp_path, compiled, registry, launcher).run()
    assert second.status == "COMPLETED"
    assert second.reused_nodes == ("A",)
    assert len(launcher.launches) == 1


def test_tampered_attempt_artifact_is_not_reused(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"),))
    launcher = RecordingLauncher()
    registry = registry_for(SyntheticCapability())
    assert runtime(tmp_path, compiled, registry, launcher).run().status == "COMPLETED"
    (tmp_path / "run" / "work" / "A" / "attempt-0001" / "result.dat").write_text(
        "tampered", encoding="utf-8"
    )
    second = runtime(tmp_path, compiled, registry, launcher).run()
    assert second.status == "COMPLETED"
    assert second.reused_nodes == ()
    assert second.attempts["A"].attempt_id == "attempt-0002"
    assert len(launcher.launches) == 2


def test_tampered_parser_evidence_is_not_reused(tmp_path: Path):
    compiled = workflow(tmp_path, (node("A"),))
    launcher = RecordingLauncher()
    registry = registry_for(SyntheticCapability())
    assert runtime(tmp_path, compiled, registry, launcher).run().status == "COMPLETED"
    stdout = tmp_path / "run" / "work" / "A" / "attempt-0001" / "stdout.txt"
    stdout.write_text(stdout.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    second = runtime(tmp_path, compiled, registry, launcher).run()
    assert second.status == "COMPLETED"
    assert second.reused_nodes == ()
    assert second.attempts["A"].attempt_id == "attempt-0002"


def test_execution_resources_do_not_contaminate_scientific_identity():
    scientific = identity()
    first = execution(ranks=1)
    second = execution(ranks=2)
    assert scientific.fingerprint == identity().fingerprint
    assert first.fingerprint != second.fingerprint


class TrackingSiestaAdapter(SiestaEngineAdapter):
    def __init__(self):
        super().__init__()
        self.parsed = 0
        self.classified = 0

    def parse_output(self, lines, **kwargs):
        self.parsed += 1
        return super().parse_output(lines, **kwargs)

    def classify_result(self, parsed, **kwargs):
        self.classified += 1
        return super().classify_result(parsed, **kwargs)


def test_siesta_adapter_executes_through_registered_generic_path(tmp_path: Path):
    fdf = """SystemName M1
SystemLabel m1
NumberOfAtoms 1
NumberOfSpecies 1
MeshCutoff 100 Ry
PAO.BasisSize SZ
XC.functional GGA
XC.authors PBE
%block ChemicalSpeciesLabel
1 1 H
%endblock ChemicalSpeciesLabel
LatticeConstant 1.0 Ang
%block LatticeVectors
5 0 0
0 5 0
0 0 5
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
%endblock AtomicCoordinatesAndAtomicSpecies
%block kgrid_Monkhorst_Pack
1 0 0 0.0
0 1 0 0.0
0 0 1 0.0
%endblock kgrid_Monkhorst_Pack
"""
    artifact = external(tmp_path, fdf)
    task = WorkflowTaskNode(
        task_id="siesta",
        kind=WorkflowTaskKind.CALCULATION,
        capability_id=SIESTA_ENGINE_CAPABILITY,
        dependencies=(),
        inputs=(WorkflowInputBinding("fdf", "input.fdf", "application/x-siesta-fdf", external_artifact_id="input-main"),),
        outputs=(),
        resources={"max_attempts": 1},
        settings={"synthetic": True},
    )
    compiled = CompiledWorkflow(
        workflow_id="siesta-m1",
        project_id="m1-project",
        definition_sha256="2" * 64,
        tasks=(task,),
        edges=(),
        external_artifacts=(artifact,),
    )
    adapter = TrackingSiestaAdapter()
    registry = CapabilityRegistry()
    register_siesta_engine(registry, adapter=adapter)
    registry.freeze()
    output = (
        "Siesta Version : 5.4.2-SYNTHETIC\nSiesta started\n"
        "Number of atoms: 1\nNumber of species: 1\nSCF cycle 1\n"
        "SCF converged\nsiesta: Final energy -1.0\nElapsed time: 1.0 s\n"
        "Job completed\n"
    )
    launcher = RecordingLauncher({"siesta": [(output.rstrip(), 0, False, False)]})
    result = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry,
        root=tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={"siesta": identity()},
        execution_specs=execution(),
        launcher=launcher,
    ).run()
    assert result.status == "COMPLETED"
    assert result.node_results["siesta"].technical_validation.status == "PASS"
    assert adapter.parsed == adapter.classified == 1


def test_generic_runtime_modules_have_no_engine_specific_execution_logic():
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "src/qraft/execution/capability_runtime.py",
        "src/qraft/execution/allocation_controller.py",
    ):
        text = (root / relative).read_text(encoding="utf-8").casefold()
        assert "engines.siesta" not in text
        assert 'engine == "siesta"' not in text
        assert "engine == 'siesta'" not in text
        assert 'task_kind == "siesta"' not in text
        assert "task_kind == 'siesta'" not in text
        assert "siestaoutputparser" not in text
