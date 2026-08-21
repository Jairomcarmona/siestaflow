from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from qraft.core import ScientificIdentity
from qraft.execution.capability_runtime import CompiledWorkflowRuntime
from qraft.execution.resource_coordinator import RuntimeAllocation
from qraft.workflow_composition import (
    ArtifactPortContract,
    RecipePolicy,
    WorkflowComposer,
    WorkflowFragment,
)
from qraft.workflows import WorkflowCompiler

from tests.execution.test_capability_runtime import (
    OPAQUE_FAIL,
    OPAQUE_PASS,
    PASS_CAPABILITY,
    RecordingLauncher,
    SyntheticCapability,
    execution,
    identity,
    registry_for,
)


RESOURCES = {
    "nodes": 1,
    "mpi_processes": 1,
    "processes_per_node": 1,
    "cpus_per_process": 1,
    "walltime_seconds": 60,
}
RESULT = ArtifactPortContract("org.example.m3-result", "application/json")
SEED = ArtifactPortContract("org.example.m3-seed", "application/json")


class MultiInputSyntheticCapability(SyntheticCapability):
    def __init__(self) -> None:
        super().__init__()
        self.consumed_inputs: dict[str, dict[str, str]] = {}

    def select_primary_input(self, **kwargs):
        return str(kwargs["settings"]["primary_input"])

    def validate_input(self, inspected, **kwargs):
        evidence_key = kwargs["settings"].get("evidence_task")
        if evidence_key is not None:
            self.consumed_inputs[str(evidence_key)] = {
                name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                for name, path in kwargs["inputs"].items()
            }
        return super().validate_input(inspected, **kwargs)


def _external(name: str = "seed") -> dict[str, str]:
    return {
        "name": name,
        "source": f"inputs/{name}.json",
        "destination": f"input/{name}.json",
        "media_type": "application/json",
    }


def _produced(name: str, source_task: str) -> dict[str, object]:
    return {
        "name": name,
        "from": {"task": source_task, "output": "result"},
        "destination": f"input/{name}.json",
        "media_type": "application/json",
    }


def _task(
    task_id: str,
    inputs: list[dict[str, object]],
    *,
    settings: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "kind": "postprocess",
        "capability": PASS_CAPABILITY,
        "inputs": inputs,
        "outputs": [{
            "name": "result",
            "path": "result.dat",
            "artifact_type": RESULT.artifact_type,
            "media_type": RESULT.media_type,
            "required": True,
        }],
        "resources": RESOURCES,
        "settings": settings or {},
    }


def _fragment(
    task_id: str,
    inputs: list[dict[str, object]],
    *,
    settings: dict[str, str] | None = None,
) -> WorkflowFragment:
    contracts = {
        str(item["name"]): SEED if "source" in item else RESULT
        for item in inputs
    }
    return WorkflowFragment.single(
        task_id.lower(), _task(task_id, inputs, settings=settings), input_contracts=contracts
    )


def _compile(tmp_path: Path, fragments: tuple[WorkflowFragment, ...]):
    source = tmp_path / "inputs" / "seed.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("{}\n", encoding="utf-8")
    definition = WorkflowComposer().compose(
        SimpleNamespace(
            intent_id="m3-generic", project_id="m3-project",
            sha256="a" * 64, metadata={"requested_by": "M3"},
        ),
        RecipePolicy("org.example.m3", "1.0.0", "M3 generic runtime proof", "TEST"),
        fragments,
    )
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(definition, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    compilation = WorkflowCompiler().compile(path)
    assert compilation.valid and compilation.compiled is not None
    return definition, compilation.compiled


def _runtime(
    tmp_path: Path,
    workflow,
    launcher: RecordingLauncher,
    *,
    root: Path | None = None,
    allocation_id: str = "local",
    capability: MultiInputSyntheticCapability | None = None,
) -> CompiledWorkflowRuntime:
    return CompiledWorkflowRuntime(
        workflow=workflow,
        registry=registry_for(capability or MultiInputSyntheticCapability()),
        root=root or tmp_path / "run",
        source_root=tmp_path,
        scientific_identities={task.task_id: identity() for task in workflow.tasks},
        execution_specs=execution(),
        launcher=launcher,
        allocation=RuntimeAllocation(
            total_cpus=1,
            total_nodes=1,
            max_parallel_steps=1,
            allocation_id=allocation_id,
        ),
    )


def _states(root: Path) -> dict[str, str]:
    data = json.loads((root / "state" / "workflow_runtime.json").read_text(encoding="utf-8"))
    return {key: value["status"] for key, value in data["payload"]["tasks"].items()}


def test_principal_composed_fanout_fanin_failure_isolation(tmp_path: Path) -> None:
    fragments = (
        _fragment("ROOT", [_external()]),
        _fragment("A", [_produced("input", "ROOT")]),
        _fragment("B", [_produced("input", "ROOT")]),
        _fragment("C", [_produced("input", "ROOT")]),
        _fragment("B_CHILD", [_produced("input", "B")]),
        _fragment("JOIN", [
            _produced("left", "A"),
            _produced("right", "C"),
        ], settings={"primary_input": "left", "evidence_task": "JOIN"}),
    )
    definition, workflow = _compile(tmp_path, fragments)
    assert definition["metadata"]["composition"]["fragments"] == [
        "root", "a", "b", "c", "b_child", "join"
    ]
    assert {(edge.source_task_id, edge.target_task_id) for edge in workflow.edges} == {
        ("ROOT", "A"), ("ROOT", "B"), ("ROOT", "C"),
        ("B", "B_CHILD"), ("A", "JOIN"), ("C", "JOIN"),
    }
    launcher = RecordingLauncher({"B": [(OPAQUE_FAIL, 0, False, True)]})
    root = tmp_path / "run"
    capability = MultiInputSyntheticCapability()
    result = _runtime(
        tmp_path, workflow, launcher, root=root, capability=capability
    ).run()

    assert _states(root) == {
        "ROOT": "COMPLETED", "A": "COMPLETED", "B": "FAILED",
        "C": "COMPLETED", "B_CHILD": "BLOCKED", "JOIN": "COMPLETED",
    }
    launched = [item.task_id for item in launcher.launches]
    assert launched[0] == "ROOT" and "B_CHILD" not in launched
    assert launched.index("JOIN") > max(launched.index("A"), launched.index("C"))
    join = root / "work" / "JOIN" / "attempt-0001"
    payload = json.loads((join / "attempt.json").read_text(encoding="utf-8"))["payload"]
    for name, parent in (("left", "A"), ("right", "C")):
        parent_artifact = root / "work" / parent / "attempt-0001" / "result.dat"
        digest = hashlib.sha256(parent_artifact.read_bytes()).hexdigest()
        assert payload["input_sources"][name] == digest
        assert capability.consumed_inputs["JOIN"][name] == digest
    assert result.attempts["JOIN"].result.execution_state == "COMPLETED"


def test_failed_is_terminal_and_interrupted_retries_immutably(tmp_path: Path) -> None:
    _, failed_workflow = _compile(tmp_path / "failed", (_fragment("A", [_external()]),))
    failed_root = tmp_path / "failed-run"
    first_failed = _runtime(
        tmp_path / "failed", failed_workflow,
        RecordingLauncher({"A": [(OPAQUE_FAIL, 0, False, True)]}), root=failed_root,
    ).run()
    assert first_failed.status == "FAILED"
    second_launcher = RecordingLauncher()
    second_failed = _runtime(
        tmp_path / "failed", failed_workflow, second_launcher, root=failed_root,
    ).run()
    assert second_failed.status == "FAILED" and second_launcher.launches == []
    assert (failed_root / "work" / "A" / "attempt-0001" / "attempt.json").is_file()
    assert not (failed_root / "work" / "A" / "attempt-0002").exists()

    _, interrupted_workflow = _compile(tmp_path / "interrupted", (_fragment("B", [_external()]),))
    interrupted_root = tmp_path / "interrupted-run"
    first_interrupted = _runtime(
        tmp_path / "interrupted", interrupted_workflow,
        RecordingLauncher({"B": [(OPAQUE_PASS, 0, True, True)]}), root=interrupted_root,
    ).run()
    assert first_interrupted.status == "INTERRUPTED"
    retried = _runtime(
        tmp_path / "interrupted", interrupted_workflow, RecordingLauncher(), root=interrupted_root,
    ).run()
    assert retried.attempts["B"].attempt_id == "attempt-0002"
    assert (interrupted_root / "work" / "B" / "attempt-0001" / "attempt.json").is_file()


def test_allocation_rollover_reuses_valid_work_and_continues(tmp_path: Path) -> None:
    _, workflow = _compile(
        tmp_path, (
            _fragment("ROOT", [_external()]),
            _fragment("WORK", [_produced("input", "ROOT")]),
        ),
    )
    root = tmp_path / "run"
    identities: dict[str, ScientificIdentity] = {
        task.task_id: identity() for task in workflow.tasks
    }
    first = CompiledWorkflowRuntime(
        workflow=workflow, registry=registry_for(MultiInputSyntheticCapability()),
        root=root, source_root=tmp_path, scientific_identities=identities,
        execution_specs=execution(),
        launcher=RecordingLauncher({"WORK": [(OPAQUE_PASS, 0, True, True)]}),
        allocation=RuntimeAllocation(1, 1, allocation_id="alloc-001"),
    ).run()
    assert first.status == "INTERRUPTED"
    second_launcher = RecordingLauncher()
    second = CompiledWorkflowRuntime(
        workflow=workflow, registry=registry_for(MultiInputSyntheticCapability()),
        root=root, source_root=tmp_path, scientific_identities=identities,
        execution_specs=execution(), launcher=second_launcher,
        allocation=RuntimeAllocation(1, 1, allocation_id="alloc-002"),
    ).run()
    assert second.status == "COMPLETED"
    assert second.reused_nodes == ("ROOT",)
    assert [item.task_id for item in second_launcher.launches] == ["WORK"]
    assert second.attempts["WORK"].attempt_id == "attempt-0002"
    assert (root / "work" / "ROOT" / "attempt-0002").exists() is False
    state = json.loads((root / "state" / "workflow_runtime.json").read_text(encoding="utf-8"))["payload"]
    assert [item["allocation_id"] for item in state["allocation_history"]] == ["alloc-001", "alloc-002"]
