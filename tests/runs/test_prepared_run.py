from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from siestaflow.cli import main
from siestaflow.execution.allocation_controller import load_controller_config
from siestaflow.run_inspection import RunInspector
from siestaflow.run_preparation import RunPreparer, RunPreparationRequest
from siestaflow.workflows import WorkflowCompiler, write_workflow_lock


REPO = Path(__file__).resolve().parents[2]


def _fdf() -> str:
    return """SystemName Prepared run test
SystemLabel prepared_run
NumberOfAtoms 1
NumberOfSpecies 1
LatticeConstant 1.0 Ang
%block LatticeVectors
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
%endblock LatticeVectors
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0.0 0.0 0.0 1
%endblock AtomicCoordinatesAndAtomicSpecies
NetCharge 0
Spin non-polarized
MD.Steps 0
MD.TypeOfRun CG
MeshCutoff 100 Ry
%block kgrid_Monkhorst_Pack
1 0 0 0.0
0 1 0 0.0
0 0 1 0.0
%endblock kgrid_Monkhorst_Pack
"""


def _sources(root: Path) -> Path:
    (root / "inputs").mkdir(parents=True)
    (root / "pseudos").mkdir()
    (root / "inputs" / "parent.fdf").write_text(_fdf(), encoding="utf-8")
    (root / "inputs" / "restart.fdf").write_text(
        _fdf().replace("MD.Steps 0", "DM.UseSaveDM T\nMD.Steps 0"),
        encoding="utf-8",
    )
    (root / "pseudos" / "C.psml").write_text("<psml/>\n", encoding="utf-8")
    definition = {
        "schema_version": "1.0",
        "workflow_id": "prepared-chain",
        "project_id": "run-tests",
        "description": "Two-stage exact destination test",
        "metadata": {"execution_authorized": False},
        "tasks": [
            {
                "task_id": "parent",
                "kind": "calculation",
                "capability": "siestaflow.engine.siesta",
                "inputs": [
                    {
                        "name": "fdf",
                        "source": "inputs/parent.fdf",
                        "destination": "input/main.fdf",
                        "media_type": "text/x-siesta-fdf",
                    },
                    {
                        "name": "pseudo",
                        "source": "pseudos/C.psml",
                        "destination": "C.psml",
                        "media_type": "application/xml",
                    },
                ],
                "outputs": [
                    {
                        "name": "density",
                        "path": "prepared_run.DM",
                        "artifact_type": "siesta.density-matrix",
                        "media_type": "application/x-siesta-dm",
                    }
                ],
                "resources": {
                    "nodes": 2,
                    "mpi_processes": 4,
                    "processes_per_node": 2,
                    "cpus_per_process": 1,
                    "walltime_seconds": 300,
                },
            },
            {
                "task_id": "restart",
                "kind": "calculation",
                "capability": "siestaflow.engine.siesta",
                "inputs": [
                    {
                        "name": "fdf",
                        "source": "inputs/restart.fdf",
                        "destination": "input/restart.fdf",
                        "media_type": "text/x-siesta-fdf",
                    },
                    {
                        "name": "pseudo",
                        "source": "pseudos/C.psml",
                        "destination": "C.psml",
                        "media_type": "application/xml",
                    },
                    {
                        "name": "parent_dm",
                        "from": {"task": "parent", "output": "density"},
                        "destination": "prepared_run.DM",
                    },
                ],
                "outputs": [
                    {
                        "name": "density",
                        "path": "prepared_run.DM",
                        "artifact_type": "siesta.density-matrix",
                        "media_type": "application/x-siesta-dm",
                    }
                ],
                "resources": {
                    "nodes": 2,
                    "mpi_processes": 4,
                    "processes_per_node": 2,
                    "cpus_per_process": 1,
                    "walltime_seconds": 300,
                },
            },
        ],
    }
    path = root / "workflow.json"
    path.write_text(json.dumps(definition, indent=2) + "\n", encoding="utf-8")
    return path


def _profile(root: Path) -> Path:
    value = {
        "schema_version": "1.0",
        "profile_id": "yoltla-test",
        "target": "slurm",
        "slurm": {
            "partition": "tt2d-64p",
            "account": "vini",
            "qos": "normal",
        },
        "allocation": {
            "nodes": 2,
            "total_cpus": 4,
            "memory": "8G",
            "walltime": "00:30:00",
            "max_parallel_steps": 1,
            "shutdown_margin_seconds": 60,
            "termination_grace_seconds": 10,
        },
        "runtime": {
            "module_commands": [
                "module purge",
                "module load siesta/5.4.2",
                "module load python/3.12",
            ],
            "siesta_executable": "siesta",
            "executable_arguments": [],
            "launcher": {
                "kind": "hydra",
                "command": ["mpiexec.hydra"],
                "arguments": [],
                "bootstrap": "ssh",
                "processes_per_node": 2,
            },
            "exclusive": True,
            "environment": {"OMP_NUM_THREADS": "1"},
        },
        "task_policy": {
            "max_attempts": 2,
            "require_scf_converged": True,
        },
    }
    path = root / "profile.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _prepared(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    definition = _sources(source)
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    profile = _profile(tmp_path)
    output = tmp_path / "output"
    result = RunPreparer(REPO).prepare(
        RunPreparationRequest(
            workflow_lock=lock,
            source_root=source,
            execution_profile=profile,
            output_root=output,
            run_id="prepared-run-001",
        )
    )
    return result, Path(result.package_path)


def test_prepare_builds_hash_bound_package_with_exact_destinations(
    tmp_path: Path,
) -> None:
    result, package = _prepared(tmp_path)
    assert result.status == "RUN_PACKAGE_READY_FOR_MANUAL_TRANSFER"
    assert result.execution_authorized is False
    assert result.submission_performed is False
    assert package.is_dir()
    assert Path(result.zip_path).is_file()

    config = load_controller_config(package / "campaign.yaml")
    parent = config.tasks[0]
    assert set(parent.input_destinations.values()) == {
        "input/main.fdf",
        "C.psml",
    }
    assert config.tasks[1].transfers[0].destination == "prepared_run.DM"
    inspection = RunInspector().inspect(package)
    assert inspection.status == "PREPARED_RUN_VERIFIED"
    assert inspection.campaign_status == "PENDING"
    verified = subprocess.run(
        [sys.executable, "verify_package.py"],
        cwd=package,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr
    assert "SIESTAFLOW_CONTROLLER_PACKAGE_VERIFIED" in verified.stdout
    plan = RunInspector().resume(package)
    assert plan.status == "INITIAL_SUBMISSION_REQUIRED"
    assert plan.command == "sbatch submit.slurm"
    assert plan.submission_performed is False


def test_prepare_dry_run_does_not_create_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    definition = _sources(source)
    compilation = WorkflowCompiler().compile(definition)
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    output = tmp_path / "dry"
    result = RunPreparer(REPO).prepare(
        RunPreparationRequest(
            workflow_lock=lock,
            source_root=source,
            execution_profile=_profile(tmp_path),
            output_root=output,
            run_id="prepared-run-dry",
            dry_run=True,
        )
    )
    assert result.status == "DRY_RUN_NO_SIDE_EFFECTS"
    assert not output.exists()


def test_inspection_rejects_provenance_tampering(tmp_path: Path) -> None:
    _, package = _prepared(tmp_path)
    lock = package / "workflow.lock.json"
    lock.write_text(lock.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        RunInspector().inspect(package)


def test_run_cli_inspect_status_and_resume_are_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    _, package = _prepared(tmp_path)

    assert main(["run", "inspect", str(package), "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["status"] == "PREPARED_RUN_VERIFIED"

    assert main(["run", "status", str(package), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["progress"]["campaign_status"] == "PENDING"

    assert main(["run", "resume", str(package), "--json"]) == 0
    resume = json.loads(capsys.readouterr().out)
    assert resume["status"] == "INITIAL_SUBMISSION_REQUIRED"
    assert resume["command"] == "sbatch submit.slurm"
    assert resume["submission_performed"] is False


def test_resume_requires_explicit_previous_job_terminal_confirmation(
    tmp_path: Path,
) -> None:
    _, package = _prepared(tmp_path)
    payload = {
        "schema_version": "1.0",
        "campaign_id": "prepared-run-001",
        "system_id": "prepared-chain",
        "status": "RUNNING",
        "current_job_id": "old-job",
        "allocation_history": [
            {"job_id": "old-job", "started_at_epoch": 1.0}
        ],
        "tasks": {
            "parent": {
                "status": "RUNNING",
                "attempts": 1,
                "last_attempt": "attempt-0001",
                "result_manifest_sha256": None,
                "reason": "running when allocation ended",
                "depends_on": [],
            },
            "restart": {
                "status": "PENDING",
                "attempts": 0,
                "last_attempt": None,
                "result_manifest_sha256": None,
                "reason": "not started",
                "depends_on": ["parent"],
            },
        },
        "revision": 1,
        "updated_at_epoch": 2.0,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    state = package / "state"
    state.mkdir()
    (state / "campaign_state.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "payload": payload,
                "sha256": hashlib.sha256(encoded).hexdigest(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    blocked = RunInspector().resume(package)
    assert blocked.status == "PREVIOUS_JOB_TERMINAL_CONFIRMATION_REQUIRED"
    assert blocked.command is None
    resumed = RunInspector().resume(
        package,
        previous_job_terminal=True,
    )
    assert resumed.status == "RESUBMISSION_REQUIRED"
    assert resumed.command == "sbatch submit.slurm"
    assert resumed.terminal_confirmation_received is True
