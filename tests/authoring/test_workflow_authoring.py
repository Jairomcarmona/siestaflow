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
    KGRID_EVALUATION_RECIPE,
    KGRID_EVALUATOR_CAPABILITY,
    MESH_EVALUATION_RECIPE,
    MESH_EVALUATOR_CAPABILITY,
    OBSERVATION_PRODUCTION_RECIPE,
    OBSERVATION_PRODUCER_CAPABILITY,
    SCIENTIFIC_COMPOSITION_RECIPE,
    STRUCTURAL_RELAXATION_CAPABILITY,
    STRUCTURAL_RELAXATION_RECIPE,
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


def manual_composition_source(root: Path) -> tuple[Path, Path]:
    intent, output = authoring_source(root)
    original = json.loads(intent.read_text(encoding="utf-8"))
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "researcher-selected-cycle",
        "project_id": original["project_id"], "recipe": SCIENTIFIC_COMPOSITION_RECIPE,
        "parameters": {"modules": [{
            "module_id": "mesh", "capability": MESH_EVALUATOR_CAPABILITY,
            "parameters": original["parameters"], "resources": original["resources"],
            "metadata": {"selection": "isolated-convergence"},
        }]},
        "resources": {}, "metadata": {"requested_by": "researcher"},
    })
    return intent, output


def structural_relaxation_source(root: Path) -> tuple[Path, Path]:
    fdf = root / "relax.fdf"
    fdf.write_text("""SystemName Local technical relaxation fixture
SystemLabel relax_local
NumberOfAtoms 1
NumberOfSpecies 1
%block ChemicalSpeciesLabel
  1 6 C
%endblock ChemicalSpeciesLabel
LatticeConstant 1.0 Ang
%block LatticeVectors
  8.0 0.0 0.0
  0.0 8.0 0.0
  0.0 0.0 8.0
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
  0.0 0.0 0.0 1
%endblock AtomicCoordinatesAndAtomicSpecies
NetCharge 0
Spin non-polarized
MD.TypeOfRun CG
MD.NumCGSteps 2
""", encoding="utf-8", newline="\n")
    (root / "C.psml").write_text("technical fixture only\n", encoding="utf-8")
    intent = root / "relaxation-intent.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "relaxation-local", "project_id": "test-project",
        "recipe": STRUCTURAL_RELAXATION_RECIPE,
        "parameters": {"fdf": "relax.fdf", "pseudopotentials": [{"source": "C.psml", "destination": "C.psml"}]},
        "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 60},
        "metadata": {"classification": "TECHNICAL_RELAXATION_CONTRACT_TEST"},
    })
    return intent, root / "relaxation-workflow.json"


def kgrid(dimensions: tuple[int, int, int]) -> dict:
    return {"dimensions": list(dimensions), "shifts": ["0.0", "0.0", "0.0"]}


def kgrid_authoring_source(root: Path) -> tuple[Path, Path]:
    write_json(root / "rule.json", {
        "schema_version": "1.0", "rule_id": "TEST_KGRID_V1", "parameter": "kgrid.MonkhorstPack",
        "initial_values": [kgrid((2, 2, 1)), kgrid((3, 3, 1)), kgrid((4, 4, 1))],
        "extension_values": [], "energy_tolerance": {"value": "1", "unit": "meV/atom"},
        "force_tolerance": {"value": "0.01", "unit": "eV/Ang"}, "consecutive_levels": 2,
        "require_magnetic_stability": True, "selection": "LOWEST_PASSING", "final_authority": "HUMAN_REVIEW",
    })
    records = []
    for dimensions, energy, force in (((2, 2, 1), "-19.990", "0.030"), ((3, 3, 1), "-19.999", "0.005"), ((4, 4, 1), "-20.000", "0.000")):
        spec = kgrid(dimensions)
        records.append({
            "schema_version": "1.0", "observation_id": f"k{'x'.join(map(str, dimensions))}",
            "requested_grid": spec, "used_grid": spec, "atom_count": 2,
            "atom_identity_sha256": HASHES["atoms"], "structure_sha256": HASHES["structure"],
            "pseudopotential_manifest_sha256": HASHES["pseudo"], "invariant_input_sha256": "e" * 64,
            "energy": {"value": energy, "unit": "eV"},
            "forces": {"values": [[force, "0", "0"], ["0", force, "0"]], "unit": "eV/Ang"},
            "scf_converged": True, "magnetic_signature": "FM",
        })
    paths = []
    for index, record in enumerate(records, 1):
        path = root / "observations" / f"{index:03d}.json"
        write_json(path, record)
        paths.append(path.relative_to(root).as_posix())
    intent = root / "intent.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "kgrid-evidence-local", "project_id": "test-project",
        "recipe": KGRID_EVALUATION_RECIPE,
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
    assert [item["recipe_id"] for item in service.recipes()] == [
        SCIENTIFIC_COMPOSITION_RECIPE, KGRID_EVALUATION_RECIPE,
        MESH_EVALUATION_RECIPE, OBSERVATION_PRODUCTION_RECIPE, STRUCTURAL_RELAXATION_RECIPE,
    ]
    detail = service.recipe(MESH_EVALUATION_RECIPE)
    assert detail["metadata"]["requires"] == [MESH_EVALUATOR_CAPABILITY]
    assert detail["metadata"]["runs_engine"] is False
    preparer = RunPreparer(REPO)
    assert preparer.task_adapter_ids == (
        KGRID_EVALUATOR_CAPABILITY, MESH_EVALUATOR_CAPABILITY, OBSERVATION_PRODUCER_CAPABILITY,
    )
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
    composition = first.compiled.metadata["composition"]  # type: ignore[union-attr]
    assert composition["fragments"] == ["mesh-evidence-evaluation"]
    assert all(item["artifact_type"].startswith("siestaflow.") for item in composition["ports"])


def test_manual_composition_preview_is_deterministic_and_never_authorizes_execution(tmp_path: Path) -> None:
    intent, output = manual_composition_source(tmp_path)
    service = WorkflowAuthoringService()
    first = service.compose_definition(intent, output, dry_run=True)
    second = service.compose_definition(intent, output, dry_run=True)
    assert first == second
    assert first["status"] == "WORKFLOW_DEFINITION_PREVIEW"
    assert first["execution_authorized"] is False and not output.exists()
    assert first["definition"]["metadata"]["recipe_id"] == SCIENTIFIC_COMPOSITION_RECIPE
    assert first["definition"]["metadata"]["composition"]["fragments"] == ["mesh-evidence-evaluation"]
    result = service.compose_definition(intent, output)
    assert result["status"] == "WORKFLOW_DEFINITION_CREATED"
    assert WorkflowCompiler().compile(output).valid


def test_manual_composition_rejects_duplicate_modules_and_non_builder_capabilities(tmp_path: Path) -> None:
    intent, output = manual_composition_source(tmp_path)
    raw = json.loads(intent.read_text(encoding="utf-8"))
    raw["parameters"]["modules"].append(dict(raw["parameters"]["modules"][0]))
    write_json(intent, raw)
    with pytest.raises(ValueError, match="module ids must be unique"):
        WorkflowAuthoringService().compose_definition(intent, output)
    raw["parameters"]["modules"] = [{
        **raw["parameters"]["modules"][0],
        "module_id": "not-a-builder", "capability": MESH_EVALUATION_RECIPE,
    }]
    write_json(intent, raw)
    with pytest.raises(ValueError, match="not a workflow builder"):
        WorkflowAuthoringService().compose_definition(intent, output)


def test_structural_relaxation_compiles_and_prepares_through_the_canonical_route(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    intent, definition = structural_relaxation_source(source)
    service = WorkflowAuthoringService()
    service.create_definition(intent, definition)
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    task = compilation.compiled.tasks[0]  # type: ignore[union-attr]
    assert task.kind.value == "calculation"
    assert task.capability_id == "siestaflow.engine.siesta"
    assert task.outputs[0].relative_path == "relax_local.XV"
    assert task.outputs[0].artifact_type == "siestaflow.relaxed-structure"
    lock = source / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=source, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="structural-relaxation-local",
    ))
    package = Path(prepared.package_path)
    campaign = json.loads((package / "campaign.yaml").read_text(encoding="utf-8"))
    prepared_task = campaign["tasks"][0]
    assert prepared_task["kind"] == "siesta"
    assert prepared_task["required_artifacts"] == ["relax_local.XV"]
    assert set(prepared_task["input_destinations"].values()) >= {"relax.fdf", "C.psml"}
    assert "runtime/siestaflow/execution/allocation_controller.py" in (package / "checksums.sha256").read_text(encoding="utf-8")


def test_structural_relaxation_requires_explicit_cg_and_number_of_steps(tmp_path: Path) -> None:
    intent, output = structural_relaxation_source(tmp_path)
    fdf = tmp_path / "relax.fdf"
    fdf.write_text(fdf.read_text(encoding="utf-8").replace("MD.NumCGSteps 2\n", ""), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="MD.NumCGSteps"):
        WorkflowAuthoringService().create_definition(intent, output)
    fdf.write_text(fdf.read_text(encoding="utf-8").replace("MD.TypeOfRun CG", "MD.TypeOfRun MD") + "MD.NumCGSteps 2\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="MD.TypeOfRun CG"):
        WorkflowAuthoringService().create_definition(intent, output)


def test_structural_relaxation_rejects_non_psml_or_misnamed_pseudopotentials(tmp_path: Path) -> None:
    intent, output = structural_relaxation_source(tmp_path)
    raw = json.loads(intent.read_text(encoding="utf-8"))
    raw["parameters"]["pseudopotentials"][0]["source"] = "C.psf"
    (tmp_path / "C.psf").write_text("technical fixture only\n", encoding="utf-8")
    write_json(intent, raw)
    with pytest.raises(ValueError, match="PSML"):
        WorkflowAuthoringService().create_definition(intent, output)
    raw["parameters"]["pseudopotentials"][0]["source"] = "C.psml"
    raw["parameters"]["pseudopotentials"][0]["destination"] = "wrong.psml"
    write_json(intent, raw)
    with pytest.raises(ValueError, match="ChemicalSpeciesLabel"):
        WorkflowAuthoringService().create_definition(intent, output)


def test_observation_producer_recipe_builds_a_canonical_postprocess_node(tmp_path: Path) -> None:
    for name in ("input.fdf", "stdout.txt", "FORCE_STRESS", "pseudo.json"):
        (tmp_path / name).write_text("placeholder\n", encoding="utf-8")
    intent = tmp_path / "observation-intent.json"
    output = tmp_path / "observation-workflow.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "observation-local", "project_id": "test-project",
        "recipe": OBSERVATION_PRODUCTION_RECIPE,
        "parameters": {"axis": "mesh", "observation_id": "mesh-300", "fdf": "input.fdf",
                       "stdout": "stdout.txt", "force_stress": "FORCE_STRESS", "pseudopotential_manifest": "pseudo.json"},
        "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 30},
        "metadata": {"classification": "LOCAL_REAL_ARTIFACT_POSTPROCESSING"},
    })
    WorkflowAuthoringService().create_definition(intent, output)
    compilation = WorkflowCompiler().compile(output)
    assert compilation.valid
    task = compilation.compiled.tasks[0]  # type: ignore[union-attr]
    assert task.kind.value == "postprocess"
    assert task.capability_id == OBSERVATION_PRODUCER_CAPABILITY
    assert task.outputs[0].artifact_type == "siestaflow.mesh-observation"
    assert compilation.compiled.metadata["composition"]["fragments"] == ["observation-production"]  # type: ignore[union-attr]


def test_cli_lists_describes_and_creates_recipe_workflow(tmp_path: Path, capsys) -> None:
    intent, output = authoring_source(tmp_path)
    assert main(["workflow", "recipes", "--json"]) == 0
    assert [item["recipe_id"] for item in json.loads(capsys.readouterr().out)["recipes"]] == [
        SCIENTIFIC_COMPOSITION_RECIPE, KGRID_EVALUATION_RECIPE,
        MESH_EVALUATION_RECIPE, OBSERVATION_PRODUCTION_RECIPE, STRUCTURAL_RELAXATION_RECIPE,
    ]
    assert main(["workflow", "recipe", MESH_EVALUATION_RECIPE, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["metadata"]["runs_engine"] is False
    assert main(["workflow", "create", str(intent), "--output", str(output), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "WORKFLOW_DEFINITION_CREATED"
    assert output.is_file()
    compose_intent, compose_output = manual_composition_source(tmp_path / "compose")
    assert main(["workflow", "compose", str(compose_intent), "--output", str(compose_output), "--dry-run", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["status"] == "WORKFLOW_DEFINITION_PREVIEW"
    assert preview["execution_authorized"] is False and not compose_output.exists()


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


def test_kgrid_recipe_reuses_cli_compiler_and_runtime_extension_seam(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    intent, definition = kgrid_authoring_source(source)
    WorkflowAuthoringService().create_definition(intent, definition)
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    assert compilation.compiled.tasks[0].capability_id == KGRID_EVALUATOR_CAPABILITY  # type: ignore[union-attr]
    lock = source / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=source, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="kgrid-evidence-canonical-local",
    ))
    package = Path(prepared.package_path)
    environment = {
        "SLURM_JOB_ID": "kgrid-local-job", "SLURM_SUBMIT_DIR": str(package),
        "SLURM_JOB_END_TIME": str(time.time() + 300), "SLURM_NNODES": "1",
        "SLURM_NTASKS": "1", "SLURM_CPUS_PER_TASK": "1",
    }
    controller = AllocationController.from_file(
        package / "campaign.yaml", environment=environment, poll_interval_seconds=0.01,
    )
    assert controller.run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    report = json.loads((package / "work/evaluate_kgrid_evidence/attempt-0001/kgrid-convergence-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "READY_FOR_HUMAN_REVIEW"
    assert report["selected_grid"]["dimensions"] == [3, 3, 1]


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
