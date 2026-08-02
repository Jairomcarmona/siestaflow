from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from siestaflow.contracts import (
    ApprovalDecision,
    NumericalProfileReference,
    ScientificApproval,
    ScientificArtifactReference,
    ScientificAuthority,
)
from siestaflow.workflow_composition import (
    ArtifactPortContract,
    RecipePolicy,
    WorkflowComposer,
    WorkflowFragment,
)
from siestaflow.workflows import WorkflowCompiler


HASH = "a" * 64
RESOURCES = {
    "nodes": 1, "mpi_processes": 1, "processes_per_node": 1,
    "cpus_per_process": 1, "walltime_seconds": 60,
}


def port(artifact_type: str, media_type: str = "application/json") -> ArtifactPortContract:
    return ArtifactPortContract(artifact_type, media_type)


def intent() -> SimpleNamespace:
    return SimpleNamespace(
        intent_id="manual-composition", project_id="generic-project",
        sha256=HASH, metadata={"requested_by": "researcher"},
    )


def task(
    task_id: str,
    capability: str,
    *,
    inputs: list[dict],
    outputs: list[tuple[str, str]],
    kind: str = "postprocess",
) -> dict:
    return {
        "task_id": task_id, "kind": kind, "capability": capability,
        "inputs": inputs,
        "outputs": [
            {"name": name, "path": f"{name}.json", "artifact_type": artifact_type,
             "media_type": "application/json", "required": True}
            for name, artifact_type in outputs
        ],
        "resources": RESOURCES, "settings": {},
    }


def external(name: str, source_name: str | None = None) -> dict:
    source = source_name or name
    return {"name": name, "source": f"inputs/{source}.json", "destination": f"input/{name}.json", "media_type": "application/json"}


def produced(name: str, source_task: str, source_output: str) -> dict:
    return {"name": name, "from": {"task": source_task, "output": source_output},
            "destination": f"input/{name}.json", "media_type": "application/json"}


def relaxation_fragment() -> WorkflowFragment:
    node = task(
        "relax", "org.example.relaxation", kind="calculation",
        inputs=[external("structure"), external("electronic_model"), external("numerical_profile")],
        outputs=[("ground_state", "siestaflow.ground-state"),
                 ("relaxed_structure", "siestaflow.relaxed-structure")],
    )
    return WorkflowFragment.single("relaxation", node, input_contracts={
        "structure": port("siestaflow.structure"),
        "electronic_model": port("siestaflow.electronic-model"),
        "numerical_profile": port("siestaflow.numerical-profile"),
    })


def analysis_fragment(name: str, artifact_type: str) -> WorkflowFragment:
    node = task(
        name, f"org.example.{name}",
        inputs=[produced("ground_state", "relax", "ground_state"), external("spec", f"{name}_spec")],
        outputs=[("result", artifact_type)],
    )
    return WorkflowFragment.single(name, node, input_contracts={
        "ground_state": port("siestaflow.ground-state"),
        "spec": port(f"siestaflow.{name}-spec"),
    })


def policy() -> RecipePolicy:
    return RecipePolicy(
        "org.example.manual-cycle", "1.0.0", "Researcher-selected cycle",
        "USER_SELECTED_MODULES",
    )


def test_scientific_contracts_distinguish_provisional_and_approved_inputs() -> None:
    artifact = ScientificArtifactReference(
        "ground-state", "siestaflow.ground-state", HASH, "b" * 64,
    )
    assert artifact.authority is ScientificAuthority.PROVISIONAL
    provisional = NumericalProfileReference("numerics", HASH, ScientificAuthority.PROVISIONAL)
    approved = NumericalProfileReference(
        "numerics", HASH, ScientificAuthority.APPROVED, "approval-01", "b" * 64,
    )
    assert provisional.approval_id is None and approved.approval_id == "approval-01"
    decision = ScientificApproval(
        "approval-01", HASH, "b" * 64, ApprovalDecision.APPROVE,
        "researcher", "2026-08-01T00:00:00Z",
    )
    assert decision.decision is ApprovalDecision.APPROVE
    with pytest.raises(ValueError, match="hash-bound approval"):
        NumericalProfileReference("numerics", HASH, ScientificAuthority.APPROVED)
    with pytest.raises(ValueError, match="timezone"):
        ScientificApproval(
            "approval-02", HASH, "b" * 64, ApprovalDecision.REJECT,
            "researcher", "2026-08-01T00:00:00",
        )


def test_researcher_can_compose_only_relaxation() -> None:
    definition = WorkflowComposer().compose(intent(), policy(), (relaxation_fragment(),))
    assert [item["task_id"] for item in definition["tasks"]] == ["relax"]
    assert definition["metadata"]["composition"]["fragments"] == ["relaxation"]
    assert definition["metadata"]["execution_authorized"] is False


def test_researcher_can_compose_relaxation_and_selected_parallel_analyses(tmp_path: Path) -> None:
    fragments = (
        relaxation_fragment(),
        analysis_fragment("bands", "siestaflow.band-structure"),
        analysis_fragment("dos-pdos", "siestaflow.dos-pdos-result"),
        analysis_fragment("optics", "siestaflow.optical-spectrum"),
    )
    first = WorkflowComposer().compose(intent(), policy(), fragments)
    second = WorkflowComposer().compose(intent(), policy(), fragments)
    assert first == second
    assert [item["task_id"] for item in first["tasks"]] == ["relax", "bands", "dos-pdos", "optics"]
    assert len(first["metadata"]["composition"]["connections"]) == 3
    for name in ("structure", "electronic_model", "numerical_profile", "bands_spec", "dos-pdos_spec", "optics_spec"):
        path = tmp_path / "inputs" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    workflow = tmp_path / "workflow.json"
    workflow.write_text(json.dumps(first, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    compilation = WorkflowCompiler().compile(workflow)
    assert compilation.valid
    assert [(edge.source_task_id, edge.target_task_id) for edge in compilation.compiled.edges] == [
        ("relax", "bands"), ("relax", "dos-pdos"), ("relax", "optics"),
    ]


def test_composer_rejects_incompatible_artifact_connection() -> None:
    wrong = task(
        "bands", "org.example.bands",
        inputs=[produced("ground_state", "relax", "ground_state")],
        outputs=[("result", "siestaflow.band-structure")],
    )
    fragment = WorkflowFragment.single(
        "bands", wrong,
        input_contracts={"ground_state": port("siestaflow.relaxed-structure")},
    )
    with pytest.raises(ValueError, match="scientific artifact contract mismatch"):
        WorkflowComposer().compose(intent(), policy(), (relaxation_fragment(), fragment))


def test_composer_rejects_duplicate_task_identity() -> None:
    first = relaxation_fragment()
    second = WorkflowFragment("relaxation-copy", first.tasks, first.input_contracts)
    with pytest.raises(ValueError, match="task ids must be unique"):
        WorkflowComposer().compose(intent(), policy(), (first, second))
