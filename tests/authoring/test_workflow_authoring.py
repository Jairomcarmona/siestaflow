from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from siestaflow.cli import main
from siestaflow.contracts import SCIENTIFIC_INTENT, WORKFLOW_DEFINITION, contract_catalog
from siestaflow.execution.allocation_controller import AllocationController, ExecutionStatus
from siestaflow.run_preparation import RunPreparationRequest, RunPreparer
from siestaflow.workflow_authoring import (
    MESH_EVALUATION_RECIPE,
    MESH_EVALUATOR_CAPABILITY,
    WorkflowAuthoringService,
)
from siestaflow.workflows import WorkflowCompiler, write_workflow_lock


REPO = Path(__file__).resolve().parents[2]
HASHES = {name: character * 64 for name, character in zip(("atoms", "structure", "pseudo", "input"), "abcd")}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def rule() -> dict:
    return {
        "schema_version": "1.0", "rule_id": "TEST_MESH_V1", "parameter": "Mesh.Cutoff",
        "initial_values": ["100", "200", "300"], "extension_values": [], "cutoff_unit": "Ry",
        "energy_tolerance": {"value": "1", "unit": "meV/atom"},
        "force_tolerance": {"value": "0.01", "unit": "eV/Ang"}, "consecutive_levels": 2,
        "eggbox": {"required": True, "displacement_fraction": ["0.5", "0.5", "0.5"]},
        "require_magnetic_stability": True, "selection": "LOWEST_PASSING", "final_authority": "HUMAN_REVIEW",
    }


def observation(cutoff: int, energy: str, force: str, *, kind: str = "PRIMARY", baseline: str | None = None) -> dict:
    return {
        "schema_version": "1.0", "observation_id": f"{kind.lower()}-{cutoff}", "kind": kind,
        "requested_cutoff": {"value": str(cutoff), "unit": "Ry"},
        "actual_cutoff": {"value": str(cutoff + 1), "unit": "Ry"},
        "mesh_dimensions": [cutoff // 10, cutoff // 10 + 1, cutoff // 10 + 2], "atom_count": 2,
        "atom_identity_sha256": HASHES["atoms"],
        "structure_sha256": HASHES["structure"] if kind == "PRIMARY" else "e" * 64,
        "pseudopotential_manifest_sha256": HASHES["pseudo"], "input_sha256": HASHES["input"],
        "energy": {"value": energy, "unit": "eV"},
        "forces": {"unit": "eV/Ang", "values": [[force, "0", "0"], ["0", force, "0"]]},
        "scf_converged": True, "magnetic_signature": "FM", "baseline_observation_id": baseline,
    }


def authoring_source(root: Path) -> tuple[Path, Path]:
    write_json(root / "rule.json", rule())
    records = [
        observation(100, "-19.990", "0.030"),
        observation(200, "-19.999", "0.005"),
        observation(300, "-20.000", "0.000"),
        observation(200, "-19.9995", "0.004", kind="EGGBOX", baseline="primary-200"),
    ]
    paths = []
    for index, record in enumerate(records, 1):
        path = root / "observations" / f"{index:03d}.json"
        write_json(path, record)
        paths.append(path.relative_to(root).as_posix())
    intent = root / "intent.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "mesh-evidence-local", "project_id": "test-project",
        "recipe": MESH_EVALUATION_RECIPE,
        "parameters": {"rule": "rule.json", "observations": paths},
        "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 30},
        "metadata": {"classification": "SYNTHETIC_STRUCTURED_EVIDENCE"},
    })
    return intent, root / "workflow.json"


def profile(root: Path) -> Path:
    path = root / "profile.json"
    write_json(path, {
        "schema_version": "1.0", "profile_id": "local-authoring", "target": "slurm",
        "slurm": {"partition": "local", "account": "test", "qos": "normal"},
        "allocation": {"nodes": 1, "total_cpus": 1, "memory": "1G", "walltime": "00:05:00", "max_parallel_steps": 1, "shutdown_margin_seconds": 30, "termination_grace_seconds": 10},
        "runtime": {"module_commands": [], "siesta_executable": "siesta", "executable_arguments": [],
                    "launcher": {"kind": "srun", "command": ["srun"], "arguments": [], "bootstrap": "ssh", "processes_per_node": 1},
                    "exclusive": True, "environment": {}},
        "task_policy": {"max_attempts": 1, "require_scf_converged": True},
    })
    return path


def test_registry_exposes_recipe_and_builder_without_global_discovery() -> None:
    assert SCIENTIFIC_INTENT in contract_catalog()
    assert WORKFLOW_DEFINITION in contract_catalog()
    service = WorkflowAuthoringService()
    assert [item["recipe_id"] for item in service.recipes()] == [MESH_EVALUATION_RECIPE]
    detail = service.recipe(MESH_EVALUATION_RECIPE)
    assert detail["metadata"]["requires"] == [MESH_EVALUATOR_CAPABILITY]
    assert detail["metadata"]["runs_engine"] is False
    preparer = RunPreparer(REPO)
    assert preparer.task_adapter_ids == (MESH_EVALUATOR_CAPABILITY,)
    with pytest.raises(ValueError, match="already registered"):
        RunPreparer(REPO, task_adapters={MESH_EVALUATOR_CAPABILITY: lambda *args, **kwargs: {}})


def test_application_builds_a_canonical_deterministic_workflow(tmp_path: Path) -> None:
    intent, output = authoring_source(tmp_path)
    service = WorkflowAuthoringService()
    preview = service.create_definition(intent, output, dry_run=True)
    assert preview["side_effects"] == 0 and not output.exists()
    result = service.create_definition(intent, output)
    assert result["status"] == "WORKFLOW_DEFINITION_CREATED"
    first = WorkflowCompiler().compile(output)
    second = WorkflowCompiler().compile(output)
    assert first.valid and first.lock_dict() == second.lock_dict()
    task = first.compiled.tasks[0]  # type: ignore[union-attr]
    assert task.capability_id == MESH_EVALUATOR_CAPABILITY
    assert task.kind.value == "validation"
    assert len(task.inputs) == 5
    assert first.compiled.metadata["final_authority"] == "HUMAN_REVIEW"  # type: ignore[union-attr]


def test_cli_lists_describes_and_creates_recipe_workflow(tmp_path: Path, capsys) -> None:
    intent, output = authoring_source(tmp_path)
    assert main(["workflow", "recipes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["recipes"][0]["recipe_id"] == MESH_EVALUATION_RECIPE
    assert main(["workflow", "recipe", MESH_EVALUATION_RECIPE, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["metadata"]["runs_engine"] is False
    assert main(["workflow", "create", str(intent), "--output", str(output), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "WORKFLOW_DEFINITION_CREATED"
    assert output.is_file()


def test_mesh_recipe_compiles_prepares_and_executes_through_canonical_gate(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    intent, definition = authoring_source(source)
    WorkflowAuthoringService().create_definition(intent, definition)
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    lock = source / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=source, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="mesh-evidence-canonical-local",
    ))
    package = Path(prepared.package_path)
    verification = subprocess.run([sys.executable, "verify_package.py"], cwd=package, capture_output=True, text=True)
    assert verification.returncode == 0, verification.stderr
    environment = {
        "SLURM_JOB_ID": "mesh-local-job", "SLURM_SUBMIT_DIR": str(package),
        "SLURM_JOB_END_TIME": str(time.time() + 300), "SLURM_NNODES": "1",
        "SLURM_NTASKS": "1", "SLURM_CPUS_PER_TASK": "1",
    }
    controller = AllocationController.from_file(
        package / "campaign.yaml", environment=environment, poll_interval_seconds=0.01,
    )
    assert controller.run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    report = package / "work/evaluate_mesh_evidence/attempt-0001/mesh-convergence-report.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "READY_FOR_HUMAN_REVIEW"
    assert payload["rule_id"] == "TEST_MESH_V1"
    assert len(payload["rule_sha256"]) == 64
    assert [item["observation_id"] for item in payload["observations"]] == [
        "primary-100", "primary-200", "primary-300", "eggbox-200",
    ]


def test_authoring_rejects_unknown_recipe_unsafe_paths_and_overwrite(tmp_path: Path) -> None:
    intent, output = authoring_source(tmp_path)
    raw = json.loads(intent.read_text())
    raw["recipe"] = "org.example.unknown-recipe"
    write_json(intent, raw)
    with pytest.raises(KeyError, match="unknown capability"):
        WorkflowAuthoringService().create_definition(intent, output)
    raw["recipe"] = MESH_EVALUATION_RECIPE
    raw["parameters"]["rule"] = "../rule.json"
    write_json(intent, raw)
    with pytest.raises(ValueError, match="safe relative"):
        WorkflowAuthoringService().create_definition(intent, output)
    raw["parameters"]["rule"] = "rule.json"
    write_json(intent, raw)
    WorkflowAuthoringService().create_definition(intent, output)
    with pytest.raises(FileExistsError):
        WorkflowAuthoringService().create_definition(intent, output)


def test_remote_evaluator_inputs_must_be_portable_json(tmp_path: Path) -> None:
    intent, output = authoring_source(tmp_path)
    (tmp_path / "rule.json").write_text("schema_version: '1.0'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="portable JSON"):
        WorkflowAuthoringService().create_definition(intent, output)
