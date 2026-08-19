from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from qraft.cli import main
from qraft.protocols.single_fdf import (
    build_fdf_plan,
    build_scientific_identity,
    execute_fdf_plan,
    resolve_execution_spec,
    validate_technical_result,
)
from qraft.execution.srun_launcher import StepLaunchSpec
from qraft.protocols import single_fdf


FDF = """SystemName QRAFT vertical test
SystemLabel qraft_vertical
NumberOfAtoms 1
NumberOfSpecies 1
MeshCutoff 200 Ry
NetCharge 0
Spin non-polarized
MD.TypeOfRun CG
MD.Steps 0
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0.0 0.0 0.0 1
%endblock AtomicCoordinatesAndAtomicSpecies
"""


def inputs(root: Path) -> Path:
    fdf = root / "calc.fdf"
    fdf.write_text(FDF, encoding="utf-8")
    (root / "C.psf").write_text("pseudo-v1\n", encoding="utf-8")
    return fdf


def test_identity_changes_only_for_scientific_inputs(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    first = build_scientific_identity(fdf)
    assert first == build_scientific_identity(fdf)

    (tmp_path / "C.psf").write_text("pseudo-v2\n", encoding="utf-8")
    pseudo_changed = build_scientific_identity(fdf)
    assert pseudo_changed.fingerprint != first.fingerprint

    (tmp_path / "C.psf").write_text("pseudo-v1\n", encoding="utf-8")
    fdf.write_text(FDF.replace("200 Ry", "300 Ry"), encoding="utf-8")
    fdf_changed = build_scientific_identity(fdf)
    assert fdf_changed.fingerprint != first.fingerprint


def test_execution_overrides_do_not_change_identity_or_dag(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    first = build_fdf_plan(
        fdf, overrides={
            "mpi_ranks": 4, "partition": "p4", "nodes": 1,
            "launcher": "openmpi", "executable": "siesta",
        }
    )
    second = build_fdf_plan(
        fdf, overrides={
            "mpi_ranks": 8, "partition": "p8", "nodes": 2,
            "launcher": "openmpi", "executable": "siesta",
        }
    )
    assert first["scientific_identity"] == second["scientific_identity"]
    assert first["dag"] == second["dag"]
    assert first["execution_spec"]["fingerprint"] != second["execution_spec"]["fingerprint"]


def test_configuration_precedence_and_invalid_resources(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    project = tmp_path / "project.json"
    recipe = tmp_path / "recipe.json"
    profile.write_text(json.dumps({"execution": {
        "partition": "profile", "mpi_ranks": 2,
        "launcher": "openmpi", "executable": "siesta",
    }}))
    project.write_text(json.dumps({"execution": {"partition": "project", "mpi_ranks": 4}}))
    recipe.write_text(json.dumps({"execution": {"partition": "recipe", "mpi_ranks": 8}}))
    spec, provenance = resolve_execution_spec(
        profile=profile,
        project_config=project,
        recipe=recipe,
        overrides={"partition": "cli", "mpi_ranks": 16},
    )
    assert spec.partition == "cli"
    assert spec.mpi_ranks == 16
    assert provenance["partition"] == provenance["mpi_ranks"] == "cli"

    with pytest.raises(ValueError, match="positive integer"):
        resolve_execution_spec(overrides={"mpi_ranks": 0, "partition": "local", "launcher": "direct", "executable": "siesta"})
    with pytest.raises(ValueError, match="divisible"):
        resolve_execution_spec(overrides={"mpi_ranks": 3, "nodes": 2, "partition": "local", "launcher": "openmpi", "executable": "siesta"})


def _outputs(root: Path, stdout_text: str, stderr_text: str = "") -> tuple[Path, Path]:
    stdout = root / "stdout.txt"
    stderr = root / "stderr.txt"
    stdout.write_text(stdout_text, encoding="utf-8")
    stderr.write_text(stderr_text, encoding="utf-8")
    return stdout, stderr


def test_technical_acceptance_requires_parser_stderr_and_artifacts(tmp_path: Path) -> None:
    normal = "Siesta started\nSCF cycle 1\nSCF converged\nJob completed\n"
    stdout, stderr = _outputs(tmp_path, normal)
    artifact = tmp_path / "required.DM"
    artifact.write_text("dm", encoding="utf-8")
    assert validate_technical_result(
        exit_code=0, stdout=stdout, stderr=stderr, required_artifacts=(artifact,)
    ).status == "PASS"

    assert validate_technical_result(
        exit_code=0, stdout=stdout, stderr=stderr, required_artifacts=(tmp_path / "missing",)
    ).status == "FAIL"
    stderr.write_text("MPI_ABORT invoked\n", encoding="utf-8")
    assert validate_technical_result(
        exit_code=0, stdout=stdout, stderr=stderr
    ).status == "FAIL"
    stderr.write_text("", encoding="utf-8")
    assert validate_technical_result(
        exit_code=1, stdout=stdout, stderr=stderr
    ).status == "FAIL"


def test_run_persists_immutable_attempt_and_reuses_valid_result(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    fake = tmp_path / "fake_siesta.py"
    fake.write_text(
        "import sys\nsys.stdin.read()\n"
        "print('Siesta started')\nprint('SCF cycle 1')\n"
        "print('SCF converged')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    overrides = {
        "launcher": "direct",
        "executable": sys.executable,
        "executable_arguments": [str(fake)],
        "partition": "local",
    }
    runs = tmp_path / "runs"
    first = execute_fdf_plan(fdf, overrides=overrides, runs_root=runs)
    assert first["attempt"]["result"]["technical_validation"]["status"] == "PASS"
    attempt_id = first["attempt"]["attempt_id"]
    manifest = next(runs.glob(f"*/{attempt_id}/attempt.json"))
    original = manifest.read_bytes()

    reused = execute_fdf_plan(fdf, overrides=overrides, runs_root=runs)
    assert reused["status"] == "REUSED_VALIDATED_ATTEMPT"
    assert reused["attempt"]["attempt_id"] == attempt_id
    assert manifest.read_bytes() == original

    forced = execute_fdf_plan(
        fdf, overrides=overrides, runs_root=runs, force_new_attempt=True
    )
    assert forced["attempt"]["attempt_id"] != attempt_id
    assert manifest.read_bytes() == original


def test_tampered_attempt_manifest_is_never_reused(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    fake = tmp_path / "fake_siesta.py"
    fake.write_text(
        "import sys\nsys.stdin.read()\nprint('Siesta started')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    overrides = {
        "launcher": "direct", "partition": "local",
        "executable": sys.executable, "executable_arguments": [str(fake)],
    }
    runs = tmp_path / "runs"
    first = execute_fdf_plan(fdf, overrides=overrides, runs_root=runs)
    first_id = first["attempt"]["attempt_id"]
    manifest = next(runs.glob(f"*/{first_id}/attempt.json"))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["exit_code"] = 99
    manifest.write_text(json.dumps(data), encoding="utf-8")

    recovered = execute_fdf_plan(fdf, overrides=overrides, runs_root=runs)
    assert recovered["status"] == "ATTEMPT_FINISHED"
    assert recovered["attempt"]["attempt_id"] != first_id


def test_practical_cli_plan_and_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fdf = inputs(tmp_path)
    assert main([
        "--workspace", "run", "plan", str(fdf), "--np", "4",
        "--partition", "tt2d-4p", "--launcher", "openmpi",
        "--siesta", "siesta", "--json",
    ]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["execution_spec"]["mpi_ranks"] == 4
    assert [node["node_id"] for node in plan["dag"]] == [
        "validate_input", "run_siesta", "technical_validate"
    ]

    fake = tmp_path / "fake_cli_siesta.py"
    fake.write_text(
        "import sys\nsys.stdin.read()\nprint('Siesta started')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    assert main([
        "run", str(fdf), "--launcher", "direct", "--partition", "local",
        "--siesta", sys.executable, "--siesta-argument", str(fake),
        "--runs-root", str(tmp_path / "cli-runs"), "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["attempt"]["result"]["technical_validation"]["status"] == "PASS"


def test_active_slurm_capacity_and_partition_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fdf = inputs(tmp_path)
    stdin = tmp_path / "input.fdf"
    stdin.write_text(FDF, encoding="utf-8")
    spec = StepLaunchSpec(
        "run_siesta", "attempt", tmp_path, stdin,
        tmp_path / "stdout.txt", tmp_path / "stderr.txt",
        8, 1, "siesta",
    )
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setenv("SLURM_JOB_PARTITION", "p4")
    monkeypatch.setenv("SLURM_NTASKS", "4")
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "1")
    monkeypatch.setenv("SLURM_NNODES", "1")
    execution, _ = resolve_execution_spec(
        overrides={"partition": "p4", "mpi_ranks": 8, "launcher": "srun", "executable": "siesta"}
    )
    with pytest.raises(ValueError, match="exceed allocation"):
        single_fdf._launch(execution, spec)

    partition_mismatch, _ = resolve_execution_spec(
        overrides={"partition": "other", "mpi_ranks": 4, "launcher": "srun", "executable": "siesta"}
    )
    with pytest.raises(ValueError, match="partition does not match"):
        single_fdf._launch(partition_mismatch, spec)
