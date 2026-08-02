from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from siestaflow.cli import main
from siestaflow.contracts import (
    CompiledWorkflow,
    ContractEnvelope,
    ContractIntegrityError,
    DecisionStatus,
    WORKFLOW_LOCK,
    WorkflowEdgeKind,
)
from siestaflow.workflows import WorkflowCompiler, workflow_plan


def write_valid_workflow(root: Path) -> Path:
    inputs = root / "inputs"
    inputs.mkdir()
    fdf = inputs / "system.fdf"
    fdf.write_text("SystemLabel test\n", encoding="utf-8")
    definition = {
        "schema_version": "1.0",
        "workflow_id": "restart-chain",
        "project_id": "graphene-study",
        "description": "Parent, DM restart, and postprocessing",
        "metadata": {"scientific_policy": "external"},
        "tasks": [
            {
                "task_id": "parent",
                "kind": "calculation",
                "capability": "siestaflow.engine.siesta",
                "inputs": [{
                    "name": "fdf",
                    "source": "inputs/system.fdf",
                    "destination": "system.fdf",
                    "media_type": "text/x-siesta-fdf",
                }],
                "outputs": [{
                    "name": "density_matrix",
                    "path": "system.DM",
                    "artifact_type": "siesta.density-matrix",
                    "media_type": "application/x-siesta-dm",
                }],
                "resources": {
                    "nodes": 2,
                    "mpi_processes": 64,
                    "processes_per_node": 32,
                    "cpus_per_process": 1,
                    "walltime_seconds": 3600,
                },
            },
            {
                "task_id": "restart",
                "kind": "calculation",
                "capability": "siestaflow.engine.siesta",
                "inputs": [
                    {
                        "name": "fdf",
                        "source": "inputs/system.fdf",
                        "media_type": "text/x-siesta-fdf",
                    },
                    {
                        "name": "parent_dm",
                        "from": {
                            "task": "parent",
                            "output": "density_matrix",
                        },
                        "destination": "system.DM",
                    },
                ],
                "outputs": [{
                    "name": "density_matrix",
                    "path": "system.DM",
                    "artifact_type": "siesta.density-matrix",
                    "media_type": "application/x-siesta-dm",
                }],
                "resources": {
                    "nodes": 2,
                    "mpi_processes": 64,
                    "processes_per_node": 32,
                    "cpus_per_process": 1,
                    "walltime_seconds": 1800,
                },
            },
            {
                "task_id": "postprocess",
                "kind": "postprocess",
                "capability": "siestaflow.postprocess.density-summary",
                "inputs": [{
                    "name": "density",
                    "from": {
                        "task": "restart",
                        "output": "density_matrix",
                    },
                    "destination": "final.DM",
                }],
                "outputs": [{
                    "name": "summary",
                    "path": "density-summary.json",
                    "artifact_type": "siestaflow.density-summary",
                    "media_type": "application/json",
                }],
                "resources": {
                    "nodes": 1,
                    "mpi_processes": 1,
                    "processes_per_node": 1,
                    "cpus_per_process": 1,
                    "walltime_seconds": 60,
                },
            },
        ],
    }
    path = root / "workflow.json"
    path.write_text(
        json.dumps(definition, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def test_valid_workflow_compiles_to_deterministic_hash_bound_dag(
    tmp_path: Path,
) -> None:
    path = write_valid_workflow(tmp_path)
    first = WorkflowCompiler().compile(path)
    second = WorkflowCompiler().compile(path)

    assert first.valid
    assert first.report.status is DecisionStatus.PASS
    assert first.lock_dict() == second.lock_dict()
    assert first.lock_dict()["contract"] == {
        "name": "siestaflow.workflow-lock",
        "version": "1.0",
    }
    ContractEnvelope.from_dict(
        first.lock_dict(), required_contract=WORKFLOW_LOCK
    )
    compiled = first.compiled
    assert compiled is not None
    assert [task.task_id for task in compiled.tasks] == [
        "parent",
        "restart",
        "postprocess",
    ]
    assert compiled.tasks[1].dependencies == ("parent",)
    assert compiled.tasks[2].dependencies == ("restart",)
    assert [edge.kind for edge in compiled.edges] == [
        WorkflowEdgeKind.ARTIFACT,
        WorkflowEdgeKind.ARTIFACT,
    ]
    artifact = compiled.external_artifacts[0]
    assert artifact.sha256 == hashlib.sha256(
        (tmp_path / "inputs" / "system.fdf").read_bytes()
    ).hexdigest()

    tampered = first.lock_dict()
    tampered["payload"]["workflow_id"] = "tampered"
    with pytest.raises(ContractIntegrityError):
        ContractEnvelope.from_dict(tampered, required_contract=WORKFLOW_LOCK)

    with pytest.raises(ValueError, match="topologically ordered"):
        CompiledWorkflow(
            compiled.workflow_id,
            compiled.project_id,
            compiled.definition_sha256,
            tuple(reversed(compiled.tasks)),
            compiled.edges,
            compiled.external_artifacts,
            compiled.metadata,
        )


def test_plan_is_resolved_but_never_authorizes_execution(tmp_path: Path) -> None:
    compiled = WorkflowCompiler().compile(write_valid_workflow(tmp_path)).compiled
    assert compiled is not None
    plan = workflow_plan(compiled)

    assert plan["task_count"] == 3
    assert plan["execution_authorized"] is False
    assert plan["requested_cpu_seconds_upper_bound"] == (
        64 * 3600 + 64 * 1800 + 60
    )


def test_cycle_is_blocked_with_actionable_finding(tmp_path: Path) -> None:
    path = write_valid_workflow(tmp_path)
    data = json.loads(path.read_text())
    data["tasks"][0]["depends_on"] = ["postprocess"]
    path.write_text(json.dumps(data), encoding="utf-8")

    result = WorkflowCompiler().compile(path)

    assert not result.valid
    assert result.compiled is None
    assert {item.code for item in result.report.findings} == {
        "WORKFLOW_CYCLE_DETECTED"
    }
    assert result.report.findings[0].hint


def test_missing_or_tampered_external_input_is_blocked(tmp_path: Path) -> None:
    path = write_valid_workflow(tmp_path)
    data = json.loads(path.read_text())
    data["tasks"][0]["inputs"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")

    result = WorkflowCompiler().compile(path)

    assert not result.valid
    finding = result.report.findings[0]
    assert finding.code == "WORKFLOW_EXTERNAL_INPUT_INVALID"
    assert "SHA-256 mismatch" in finding.message


def test_unknown_field_and_unsafe_path_fail_closed(tmp_path: Path) -> None:
    path = write_valid_workflow(tmp_path)
    data = json.loads(path.read_text())
    data["tasks"][0]["mystery"] = True
    data["tasks"][1]["inputs"][0]["source"] = "../outside.fdf"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = WorkflowCompiler().compile(path)

    assert not result.valid
    codes = {item.code for item in result.report.findings}
    assert "WORKFLOW_FIELD_UNKNOWN" in codes


def test_resource_placement_mismatch_is_blocked(tmp_path: Path) -> None:
    path = write_valid_workflow(tmp_path)
    data = json.loads(path.read_text())
    data["tasks"][0]["resources"]["mpi_processes"] = 63
    path.write_text(json.dumps(data), encoding="utf-8")

    result = WorkflowCompiler().compile(path)

    assert not result.valid
    assert "WORKFLOW_RESOURCE_PLACEMENT_MISMATCH" in {
        item.code for item in result.report.findings
    }


def test_cli_validates_plans_graphs_and_compiles_without_execution(
    tmp_path: Path, capsys
) -> None:
    path = write_valid_workflow(tmp_path)

    assert main(["workflow", "validate", str(path), "--json"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["valid"] is True
    assert validation["execution_authorized"] is False

    assert main(["workflow", "plan", str(path), "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["task_count"] == 3

    assert (
        main(
            [
                "workflow",
                "graph",
                str(path),
                "--format",
                "mermaid",
            ]
        )
        == 0
    )
    assert "flowchart TD" in capsys.readouterr().out

    lock = tmp_path / "workflow.lock.json"
    assert (
        main(
            [
                "workflow",
                "compile",
                str(path),
                "--output",
                str(lock),
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    assert not lock.exists()
    capsys.readouterr()

    assert (
        main(
            [
                "workflow",
                "compile",
                str(path),
                "--output",
                str(lock),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "WORKFLOW_COMPILED"
    assert lock.is_file()
    assert json.loads(lock.read_text())["content_sha256"] == result[
        "content_sha256"
    ]
