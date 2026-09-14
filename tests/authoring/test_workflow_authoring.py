from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from qraft.cli import main
from qraft.contracts import SCIENTIFIC_INTENT, WORKFLOW_DEFINITION, contract_catalog
from qraft.execution.allocation_controller import AllocationController, ExecutionStatus
from qraft.run_preparation import RunPreparationRequest, RunPreparer
from qraft.workflow_authoring import (
    BAND_STRUCTURE_CAPABILITY,
    BAND_STRUCTURE_RECIPE,
    CONVERGE_THEN_RELAX_CAPABILITY,
    CONVERGE_THEN_RELAX_RECIPE,
    DOS_PDOS_CAPABILITY,
    DOS_PDOS_RECIPE,
    GROUND_STATE_TO_DOS_PDOS_CAPABILITY,
    GROUND_STATE_TO_DOS_PDOS_RECIPE,
    GROUND_STATE_TO_ELECTRONIC_ANALYSIS_CAPABILITY,
    GROUND_STATE_TO_ELECTRONIC_ANALYSIS_RECIPE,
    KGRID_EVALUATION_RECIPE,
    KGRID_EVALUATOR_CAPABILITY,
    MESH_EVALUATION_RECIPE,
    MESH_EVALUATOR_CAPABILITY,
    OBSERVATION_PRODUCTION_RECIPE,
    OBSERVATION_PRODUCER_CAPABILITY,
    OPTICAL_SPECTRUM_RECIPE,
    SCIENTIFIC_COMPOSITION_RECIPE,
    STRUCTURAL_RELAXATION_CAPABILITY,
    STRUCTURAL_RELAXATION_RECIPE,
    WorkflowAuthoringService,
)
from qraft.scientific_convergence import evaluate_mesh_files
from qraft.scientific_kgrid import evaluate_kgrid_files
from qraft.workflows import WorkflowCompiler, write_workflow_lock


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


def dos_pdos_source(root: Path) -> tuple[Path, Path]:
    fdf = root / "dos-pdos.fdf"
    fdf.write_text("""SystemName Local technical DOS/PDOS fixture
SystemLabel dos_local
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
MD.NumCGSteps 0
%block ProjectedDensityOfStates
  EF -10.0 10.0 0.20 301 eV
%endblock ProjectedDensityOfStates
""", encoding="utf-8", newline="\n")
    (root / "C.psml").write_text("technical fixture only\n", encoding="utf-8")
    intent = root / "dos-pdos-intent.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "dos-pdos-local", "project_id": "test-project",
        "recipe": DOS_PDOS_RECIPE,
        "parameters": {"fdf": "dos-pdos.fdf", "pseudopotentials": [{"source": "C.psml", "destination": "C.psml"}]},
        "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 60},
        "metadata": {"classification": "TECHNICAL_DOS_PDOS_CONTRACT_TEST"},
    })
    return intent, root / "dos-pdos-workflow.json"


def band_structure_source(root: Path) -> tuple[Path, Path]:
    fdf = root / "bands.fdf"
    fdf.write_text("""SystemName Local technical band fixture
SystemLabel bands_local
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
MD.NumCGSteps 0
BandLinesScale ReciprocalLatticeVectors
%block BandLines
  1 0.0 0.0 0.0 Gamma
  4 0.5 0.0 0.0 X
%endblock BandLines
""", encoding="utf-8", newline="\n")
    (root / "C.psml").write_text("technical fixture only\n", encoding="utf-8")
    intent = root / "bands-intent.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "bands-local", "project_id": "test-project",
        "recipe": BAND_STRUCTURE_RECIPE,
        "parameters": {"fdf": "bands.fdf", "pseudopotentials": [{"source": "C.psml", "destination": "C.psml"}]},
        "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 60},
        "metadata": {"classification": "TECHNICAL_BANDS_CONTRACT_TEST"},
    })
    return intent, root / "bands-workflow.json"


def ground_state_to_dos_pdos_source(root: Path) -> tuple[Path, Path]:
    _, _ = dos_pdos_source(root)
    child = root / "dos-pdos.fdf"
    parent = root / "ground-state.fdf"
    source = child.read_text(encoding="utf-8")
    parent.write_text(
        source.replace("SystemLabel dos_local", "SystemLabel ground_local").replace(
            "%block ProjectedDensityOfStates\n  EF -10.0 10.0 0.20 301 eV\n%endblock ProjectedDensityOfStates\n", ""
        ),
        encoding="utf-8", newline="\n",
    )
    child.write_text(
        source + "DM.UseSaveDM T\n", encoding="utf-8", newline="\n",
    )
    intent = root / "ground-state-dos-pdos-intent.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "ground-state-dos-pdos-local", "project_id": "test-project",
        "recipe": GROUND_STATE_TO_DOS_PDOS_RECIPE,
        "parameters": {
            "ground_state_fdf": "ground-state.fdf", "dos_pdos_fdf": "dos-pdos.fdf",
            "pseudopotentials": [{"source": "C.psml", "destination": "C.psml"}],
        },
        "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 60},
        "metadata": {"classification": "TECHNICAL_RESTART_CONTRACT_TEST"},
    })
    return intent, root / "ground-state-dos-pdos-workflow.json"


def ground_state_to_electronic_analysis_source(root: Path) -> tuple[Path, Path]:
    _, _ = ground_state_to_dos_pdos_source(root)
    dos = root / "dos-pdos.fdf"
    base = dos.read_text(encoding="utf-8")
    analysis_block = "%block ProjectedDensityOfStates\n  EF -10.0 10.0 0.20 301 eV\n%endblock ProjectedDensityOfStates\n"
    common = base.replace(analysis_block, "").replace("DM.UseSaveDM T\n", "")
    (root / "bands.fdf").write_text(
        common.replace("SystemLabel dos_local", "SystemLabel bands_local")
        + "BandLinesScale ReciprocalLatticeVectors\n"
        + "%block BandLines\n  1 0.0 0.0 0.0 Gamma\n  4 0.5 0.0 0.0 X\n%endblock BandLines\n"
        + "DM.UseSaveDM T\n",
        encoding="utf-8", newline="\n",
    )
    (root / "optics.fdf").write_text(
        common.replace("SystemLabel dos_local", "SystemLabel optics_local")
        + "OpticalCalculation T\nOptical.Energy.Minimum 0.0 eV\n"
        + "Optical.Energy.Maximum 5.0 eV\nOptical.Broaden 0.2 eV\n"
        + "Optical.NumberOfBands 4\nOptical.PolarizationType polycrystal\n"
        + "%block Optical.Mesh\n  1 1 1\n%endblock Optical.Mesh\nDM.UseSaveDM T\n",
        encoding="utf-8", newline="\n",
    )
    intent = root / "electronic-analysis-intent.json"
    write_json(intent, {
        "schema_version": "1.0", "intent_id": "electronic-analysis-local",
        "project_id": "test-project", "recipe": GROUND_STATE_TO_ELECTRONIC_ANALYSIS_RECIPE,
        "parameters": {
            "ground_state_fdf": "ground-state.fdf", "dos_pdos_fdf": "dos-pdos.fdf",
            "bands_fdf": "bands.fdf", "optics_fdf": "optics.fdf",
            "pseudopotentials": [{"source": "C.psml", "destination": "C.psml"}],
        },
        "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1,
                      "cpus_per_process": 1, "walltime_seconds": 60},
        "metadata": {"classification": "TECHNICAL_CLI_INTEGRATION_ACCEPTANCE"},
    })
    return intent, root / "electronic-analysis-workflow.json"


def approved_mesh_contracts(root: Path) -> tuple[Path, Path, Path]:
    source_intent, _ = authoring_source(root)
    raw = json.loads(source_intent.read_text(encoding="utf-8"))
    report = root / "mesh-convergence-report.json"
    evaluate_mesh_files(
        root / raw["parameters"]["rule"],
        [root / item for item in raw["parameters"]["observations"]], report,
    )
    approval = root / "mesh-approval.json"
    profile = root / "mesh-profile.json"
    assert main([
        "scientific", "decide", str(report), "--approval-id", "mesh-approval-01",
        "--decision", "APPROVE", "--actor", "researcher",
        "--decided-at", "2026-08-02T00:00:00Z", "--output", str(approval), "--json",
    ]) == 0
    assert main([
        "scientific", "profile", str(report), "--approval", str(approval),
        "--profile-id", "mesh-200-ry", "--output", str(profile), "--json",
    ]) == 0
    return report, approval, profile


def converge_then_relaxation_source(root: Path) -> tuple[Path, Path]:
    report, approval, numerical_profile = approved_mesh_contracts(root)
    intent, output = structural_relaxation_source(root)
    fdf = root / "relax.fdf"
    fdf.write_text(
        fdf.read_text(encoding="utf-8") + "Mesh.Cutoff 200 Ry\n",
        encoding="utf-8", newline="\n",
    )
    raw = json.loads(intent.read_text(encoding="utf-8"))
    raw["recipe"] = CONVERGE_THEN_RELAX_RECIPE
    raw["parameters"]["numerical_profiles"] = [{
        "profile": numerical_profile.name, "approval": approval.name, "evidence": report.name,
    }]
    write_json(intent, raw)
    return intent, output


def approved_kgrid_contracts(root: Path) -> tuple[Path, Path, Path]:
    source_intent, _ = kgrid_authoring_source(root)
    raw = json.loads(source_intent.read_text(encoding="utf-8"))
    report = root / "kgrid-convergence-report.json"
    evaluate_kgrid_files(
        root / raw["parameters"]["rule"],
        [root / item for item in raw["parameters"]["observations"]], report,
    )
    approval = root / "kgrid-approval.json"
    profile = root / "kgrid-profile.json"
    assert main([
        "scientific", "decide", str(report), "--approval-id", "kgrid-approval-01",
        "--decision", "APPROVE", "--actor", "researcher",
        "--decided-at", "2026-08-02T00:00:00Z", "--output", str(approval), "--json",
    ]) == 0
    assert main([
        "scientific", "profile", str(report), "--approval", str(approval),
        "--profile-id", "kgrid-3x3x1", "--output", str(profile), "--json",
    ]) == 0
    return report, approval, profile


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
        SCIENTIFIC_COMPOSITION_RECIPE, BAND_STRUCTURE_RECIPE, CONVERGE_THEN_RELAX_RECIPE, DOS_PDOS_RECIPE,
        GROUND_STATE_TO_DOS_PDOS_RECIPE, GROUND_STATE_TO_ELECTRONIC_ANALYSIS_RECIPE,
        KGRID_EVALUATION_RECIPE,
        MESH_EVALUATION_RECIPE, OBSERVATION_PRODUCTION_RECIPE, OPTICAL_SPECTRUM_RECIPE, STRUCTURAL_RELAXATION_RECIPE,
    ]
    detail = service.recipe(MESH_EVALUATION_RECIPE)
    assert detail["metadata"]["requires"] == [MESH_EVALUATOR_CAPABILITY]
    assert detail["metadata"]["runs_engine"] is False
    assert service.recipe(DOS_PDOS_RECIPE)["metadata"]["requires"] == [DOS_PDOS_CAPABILITY]
    assert service.recipe(GROUND_STATE_TO_DOS_PDOS_RECIPE)["metadata"]["requires"] == [GROUND_STATE_TO_DOS_PDOS_CAPABILITY]
    assert service.recipe(GROUND_STATE_TO_ELECTRONIC_ANALYSIS_RECIPE)["metadata"]["requires"] == [GROUND_STATE_TO_ELECTRONIC_ANALYSIS_CAPABILITY]
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
    assert "runtime/qraft/execution/allocation_controller.py" in (package / "checksums.sha256").read_text(encoding="utf-8")


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


def test_approved_convergence_profile_creates_a_new_hash_bound_relaxation_stage(tmp_path: Path, capsys) -> None:
    intent, definition = converge_then_relaxation_source(tmp_path)
    capsys.readouterr()
    service = WorkflowAuthoringService()
    preview = service.create_definition(intent, definition, dry_run=True)
    assert preview["side_effects"] == 0 and not definition.exists()
    result = service.create_definition(intent, definition)
    assert result["recipe_id"] == CONVERGE_THEN_RELAX_RECIPE
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    task = compilation.compiled.tasks[0]  # type: ignore[union-attr]
    assert task.capability_id == "siestaflow.engine.siesta"
    assert {item.name for item in task.inputs} >= {
        "numerical_001_profile", "numerical_001_approval", "numerical_001_evidence",
    }
    profiles = task.settings["numerical_profiles"]
    assert profiles[0]["parameter"] == "Mesh.Cutoff"
    assert profiles[0]["selection"] == {"unit": "Ry", "value": "200"}
    assert compilation.compiled.metadata["scientific_scope"] == "CONVERGENCE_APPROVED_STRUCTURAL_RELAXATION"  # type: ignore[union-attr]
    assert compilation.compiled.metadata["execution_authorized"] is False  # type: ignore[union-attr]
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=tmp_path, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="approved-convergence-relaxation",
    ))
    campaign = json.loads((Path(prepared.package_path) / "campaign.yaml").read_text(encoding="utf-8"))
    propagation = campaign["tasks"][0]["scientific_propagation"]
    assert propagation[0]["profile_id"] == "mesh-200-ry"
    assert propagation[0]["parameter"] == "Mesh.Cutoff"


def test_dos_pdos_recipe_builds_a_canonical_siesta_task_and_package(tmp_path: Path) -> None:
    intent, definition = dos_pdos_source(tmp_path)
    result = WorkflowAuthoringService().create_definition(intent, definition)
    assert result["recipe_id"] == DOS_PDOS_RECIPE
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    task = compilation.compiled.tasks[0]  # type: ignore[union-attr]
    assert task.capability_id == "siestaflow.engine.siesta"
    assert task.kind.value == "calculation"
    assert [(item.name, item.relative_path, item.required) for item in task.outputs] == [
        ("projected_dos", "dos_local.PDOS", True),
        ("total_dos", "dos_local.DOS", True),
    ]
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=tmp_path, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="dos-pdos-local",
    ))
    campaign = json.loads((Path(prepared.package_path) / "campaign.yaml").read_text(encoding="utf-8"))
    assert campaign["tasks"][0]["required_artifacts"] == ["dos_local.PDOS", "dos_local.DOS"]


def test_band_structure_recipe_requires_explicit_path_and_declares_bands(tmp_path: Path) -> None:
    intent, definition = band_structure_source(tmp_path)
    result = WorkflowAuthoringService().create_definition(intent, definition)
    assert result["recipe_id"] == BAND_STRUCTURE_RECIPE
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    task = compilation.compiled.tasks[0]  # type: ignore[union-attr]
    assert [(item.name, item.relative_path, item.artifact_type) for item in task.outputs] == [
        ("band_structure", "bands_local.bands", "siestaflow.band-structure"),
    ]
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=tmp_path, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="bands-local",
    ))
    campaign = json.loads((Path(prepared.package_path) / "campaign.yaml").read_text(encoding="utf-8"))
    assert campaign["tasks"][0]["required_artifacts"] == ["bands_local.bands"]


@pytest.mark.parametrize("replacement", [
    "BandLinesScale pi/b", "  2 0.0 0.0 0.0 Gamma", "%block BandPoints\n  0.0 0.0 0.0\n%endblock BandPoints",
])
def test_band_structure_rejects_invalid_or_ambiguous_path_contract(tmp_path: Path, replacement: str) -> None:
    intent, definition = band_structure_source(tmp_path)
    fdf = tmp_path / "bands.fdf"
    if replacement.startswith("%block"):
        fdf.write_text(fdf.read_text(encoding="utf-8") + replacement + "\n", encoding="utf-8", newline="\n")
    elif replacement.startswith("  2"):
        fdf.write_text(fdf.read_text(encoding="utf-8").replace("  1 0.0 0.0 0.0 Gamma", replacement), encoding="utf-8", newline="\n")
    else:
        fdf.write_text(fdf.read_text(encoding="utf-8").replace("BandLinesScale ReciprocalLatticeVectors", replacement), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        WorkflowAuthoringService().create_definition(intent, definition)


def test_ground_state_to_dos_pdos_transfers_only_hash_bound_dm(tmp_path: Path) -> None:
    intent, definition = ground_state_to_dos_pdos_source(tmp_path)
    result = WorkflowAuthoringService().create_definition(intent, definition)
    assert result["recipe_id"] == GROUND_STATE_TO_DOS_PDOS_RECIPE
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    tasks = {task.task_id: task for task in compilation.compiled.tasks}  # type: ignore[union-attr]
    assert tasks["dos_pdos"].dependencies == ("ground_state",)
    binding = next(item for item in tasks["dos_pdos"].inputs if item.name == "ground_state_dm")
    assert (binding.source_task_id, binding.source_output_name, binding.destination) == (
        "ground_state", "density_matrix", "dos_local.DM",
    )
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=tmp_path, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="ground-state-dos-pdos-local",
    ))
    campaign = json.loads((Path(prepared.package_path) / "campaign.yaml").read_text(encoding="utf-8"))
    assert campaign["tasks"][1]["transfers"] == [{
        "from_task": "ground_state", "artifact": "ground_local.DM", "destination": "dos_local.DM",
    }]


def test_electronic_analysis_recipe_fans_one_dm_into_three_cli_modules(tmp_path: Path) -> None:
    intent, definition = ground_state_to_electronic_analysis_source(tmp_path)
    result = WorkflowAuthoringService().create_definition(intent, definition)
    assert result["recipe_id"] == GROUND_STATE_TO_ELECTRONIC_ANALYSIS_RECIPE
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    tasks = {task.task_id: task for task in compilation.compiled.tasks}  # type: ignore[union-attr]
    assert tuple(tasks) == ("ground_state", "bands", "dos_pdos", "optics")
    for task_id, label in (("dos_pdos", "dos_local"), ("bands", "bands_local"), ("optics", "optics_local")):
        assert tasks[task_id].dependencies == ("ground_state",)
        binding = next(item for item in tasks[task_id].inputs if item.name == "ground_state_dm")
        assert (binding.source_task_id, binding.source_output_name, binding.destination) == (
            "ground_state", "density_matrix", f"{label}.DM",
        )
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    prepared = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=tmp_path, execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages", run_id="electronic-analysis-local",
    ))
    campaign = json.loads((Path(prepared.package_path) / "campaign.yaml").read_text(encoding="utf-8"))
    for task in campaign["tasks"][1:]:
        assert task["transfers"][0]["from_task"] == "ground_state"
        assert task["transfers"][0]["artifact"] == "ground_local.DM"


def test_electronic_analysis_rejects_missing_dm_restart_or_changed_identity(tmp_path: Path) -> None:
    intent, definition = ground_state_to_electronic_analysis_source(tmp_path)
    optics = tmp_path / "optics.fdf"
    optics.write_text(optics.read_text(encoding="utf-8").replace("DM.UseSaveDM T\n", ""), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="DM.UseSaveDM"):
        WorkflowAuthoringService().create_definition(intent, definition)
    optics.write_text(optics.read_text(encoding="utf-8") + "DM.UseSaveDM T\n", encoding="utf-8", newline="\n")
    optics.write_text(optics.read_text(encoding="utf-8").replace("NetCharge 0", "NetCharge 1"), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="restart-compatible"):
        WorkflowAuthoringService().create_definition(intent, definition)


def test_ground_state_to_dos_pdos_rejects_missing_restart_or_changed_scientific_input(tmp_path: Path) -> None:
    intent, definition = ground_state_to_dos_pdos_source(tmp_path)
    child = tmp_path / "dos-pdos.fdf"
    child.write_text(child.read_text(encoding="utf-8").replace("DM.UseSaveDM T\n", ""), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="DM.UseSaveDM"):
        WorkflowAuthoringService().create_definition(intent, definition)
    child.write_text(child.read_text(encoding="utf-8") + "DM.UseSaveDM T\n", encoding="utf-8", newline="\n")
    child.write_text(child.read_text(encoding="utf-8").replace("NetCharge 0", "NetCharge 1"), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="restart-compatible"):
        WorkflowAuthoringService().create_definition(intent, definition)


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("MD.TypeOfRun MD", "MD.TypeOfRun CG"),
        ("MD.NumCGSteps 1", "MD.NumCGSteps 0"),
        ("EF 10.0 -10.0 0.20 301 eV", "EF -10.0 10.0 0.20 301 eV"),
        ("EF -10.0 10.0 0.00 301 eV", "EF -10.0 10.0 0.20 301 eV"),
        ("EF -10.0 10.0 0.20 1 eV", "EF -10.0 10.0 0.20 301 eV"),
    ],
)
def test_dos_pdos_rejects_invalid_analysis_contract(tmp_path: Path, replacement: str, message: str) -> None:
    intent, definition = dos_pdos_source(tmp_path)
    fdf = tmp_path / "dos-pdos.fdf"
    fdf.write_text(fdf.read_text(encoding="utf-8").replace(message, replacement), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        WorkflowAuthoringService().create_definition(intent, definition)


def test_converge_then_relax_rejects_wrong_fdf_or_unmatched_evidence(tmp_path: Path, capsys) -> None:
    intent, definition = converge_then_relaxation_source(tmp_path)
    capsys.readouterr()
    fdf = tmp_path / "relax.fdf"
    fdf.write_text(fdf.read_text(encoding="utf-8").replace("200 Ry", "300 Ry"), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="does not match"):
        WorkflowAuthoringService().create_definition(intent, definition)
    fdf.write_text(fdf.read_text(encoding="utf-8").replace("300 Ry", "200 Ry"), encoding="utf-8", newline="\n")
    report = tmp_path / "mesh-convergence-report.json"
    report.write_text(report.read_text(encoding="utf-8") + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="hash-bound together"):
        WorkflowAuthoringService().create_definition(intent, definition)


def test_converge_then_relax_accepts_a_hash_bound_kgrid_profile(tmp_path: Path, capsys) -> None:
    report, approval, numerical_profile = approved_kgrid_contracts(tmp_path)
    capsys.readouterr()
    intent, definition = structural_relaxation_source(tmp_path)
    fdf = tmp_path / "relax.fdf"
    fdf.write_text(
        fdf.read_text(encoding="utf-8") + """%block kgrid.MonkhorstPack
  3 0 0 0.0
  0 3 0 0.0
  0 0 1 0.0
%endblock kgrid.MonkhorstPack
""",
        encoding="utf-8", newline="\n",
    )
    raw = json.loads(intent.read_text(encoding="utf-8"))
    raw["recipe"] = CONVERGE_THEN_RELAX_RECIPE
    raw["parameters"]["numerical_profiles"] = [{
        "profile": numerical_profile.name, "approval": approval.name, "evidence": report.name,
    }]
    write_json(intent, raw)
    WorkflowAuthoringService().create_definition(intent, definition)
    task = WorkflowCompiler().compile(definition).compiled.tasks[0]  # type: ignore[union-attr]
    assert task.settings["numerical_profiles"][0]["parameter"] == "kgrid.MonkhorstPack"
    assert task.settings["numerical_profiles"][0]["selection"]["dimensions"] == [3, 3, 1]


def test_rejected_convergence_decision_cannot_propagate_a_profile(tmp_path: Path, capsys) -> None:
    source_intent, _ = authoring_source(tmp_path)
    raw = json.loads(source_intent.read_text(encoding="utf-8"))
    report = tmp_path / "mesh-convergence-report.json"
    evaluate_mesh_files(tmp_path / raw["parameters"]["rule"], [tmp_path / item for item in raw["parameters"]["observations"]], report)
    rejection = tmp_path / "rejection.json"
    assert main([
        "advanced", "scientific", "decide", str(report), "--approval-id", "mesh-rejection-01",
        "--decision", "REJECT", "--actor", "researcher", "--decided-at", "2026-08-02T00:00:00Z",
        "--output", str(rejection), "--json",
    ]) == 0
    assert main([
        "advanced", "scientific", "profile", str(report), "--approval", str(rejection),
        "--profile-id", "not-allowed", "--output", str(tmp_path / "profile.json"), "--json",
    ]) == 2
    captured = capsys.readouterr()
    error = json.loads(captured.out.splitlines()[-1])
    assert "rejected" in error["error"]["message"]
    assert captured.err == ""


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
        SCIENTIFIC_COMPOSITION_RECIPE, BAND_STRUCTURE_RECIPE, CONVERGE_THEN_RELAX_RECIPE, DOS_PDOS_RECIPE,
        GROUND_STATE_TO_DOS_PDOS_RECIPE, GROUND_STATE_TO_ELECTRONIC_ANALYSIS_RECIPE,
        KGRID_EVALUATION_RECIPE,
        MESH_EVALUATION_RECIPE, OBSERVATION_PRODUCTION_RECIPE, OPTICAL_SPECTRUM_RECIPE, STRUCTURAL_RELAXATION_RECIPE,
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
