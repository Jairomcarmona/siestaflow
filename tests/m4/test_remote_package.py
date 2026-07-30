from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from siestaflow.execution.allocation_controller import load_controller_config
from siestaflow.m4_remote_package import M4RemoteSmokePackager, PACKAGE_ID


REPOSITORY = Path(__file__).resolve().parents[2]
PROFILE = REPOSITORY / "config/remote_smokes/m4_surf_gr5x5_yoltla.yaml"


def build(tmp_path: Path):
    return M4RemoteSmokePackager(REPOSITORY).build(PROFILE, tmp_path)


def test_m4_package_is_complete_hash_bound_and_deterministic(tmp_path: Path):
    first_root = tmp_path / "first"; first_root.mkdir()
    second_root = tmp_path / "second"; second_root.mkdir()
    first = M4RemoteSmokePackager(REPOSITORY).build(PROFILE, first_root)
    second = M4RemoteSmokePackager(REPOSITORY).build(PROFILE, second_root)
    assert first.zip_sha256 == second.zip_sha256
    root = Path(first.destination)
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["system_id"] == "SURF_Gr5x5_clean_v01"
    assert manifest["login_node_persistent_process_required"] is False
    assert manifest["scientific_interpretation_allowed"] is False
    for name, expected in manifest["immutable_files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    config = load_controller_config(root / "campaign.yaml")
    assert config.campaign_id == PACKAGE_ID
    assert config.tasks[0].mpi_processes == 4


def test_batch_runs_controller_directly_and_reserves_srun_for_task(tmp_path: Path):
    result = build(tmp_path)
    root = Path(result.destination)
    script = (root / "campaign.slurm").read_text()
    assert 'exec python3 "$ROOT/scripts/run_worker.py"' in script
    assert "srun" not in next(line for line in script.splitlines() if "run_worker.py" in line)
    campaign = json.loads((root / "campaign.yaml").read_text())
    assert campaign["runtime"]["srun_command"] == ["srun"]
    assert campaign["runtime"]["exclusive"] is True
    assert "q1h-20p" not in (root / "runtime/siestaflow/execution/allocation_controller.py").read_text()
    assert "vini" not in (root / "runtime/siestaflow/execution/allocation_controller.py").read_text()


def test_clean_extraction_passes_vendored_verifier(tmp_path: Path):
    result = build(tmp_path)
    extraction = tmp_path / "extract"; extraction.mkdir()
    with ZipFile(result.zip_path) as archive:
        archive.extractall(extraction)
    root = extraction / PACKAGE_ID
    completed = subprocess.run([sys.executable, "verify_package.py"], cwd=root, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "M4_PACKAGE_VERIFIED" in completed.stdout
    assert "NO_LOGIN_PERSISTENT_PROCESS_REQUIRED" in completed.stdout
    repeated = subprocess.run([sys.executable, "verify_package.py"], cwd=root, capture_output=True, text=True)
    assert repeated.returncode == 0, repeated.stderr


def test_verifier_rejects_altered_input_and_added_file(tmp_path: Path):
    result = build(tmp_path)
    root = Path(result.destination)
    (root / "input/smoke.fdf").write_text("altered", encoding="utf-8")
    completed = subprocess.run([sys.executable, "verify_package.py"], cwd=root, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "IMMUTABLE_HASH_MISMATCH" in completed.stderr

    other = tmp_path / "other"; other.mkdir()
    root = Path(M4RemoteSmokePackager(REPOSITORY).build(PROFILE, other).destination)
    (root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    completed = subprocess.run([sys.executable, "verify_package.py"], cwd=root, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "CHECKSUM_COVERAGE_MISMATCH" in completed.stderr


def test_package_contains_commands_but_never_executes_submission(tmp_path: Path):
    result = build(tmp_path)
    root = Path(result.destination)
    commands = (root / "EXACT_COMMANDS.md").read_text()
    assert "sbatch --parsable campaign.slurm" in commands
    assert "squeue -j" in commands
    assert "sacct" in (root / "scripts/inspect_job.sh").read_text()
    for path in root.rglob("*.py"):
        assert "subprocess.run(['sbatch'" not in path.read_text(encoding="utf-8")
    assert not (root / "state").exists()


def test_cli_builds_package_without_scheduler_or_engine_execution(tmp_path: Path):
    output = tmp_path / "cli"; output.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPOSITORY / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "siestaflow.cli", "remote", "m4-package",
         "--profile", str(PROFILE), "--output", str(output), "--json"],
        cwd=REPOSITORY, env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "SURF_GR5X5_REMOTE_SMOKE_PACKAGE_READY"
    assert Path(payload["zip_path"]).is_file()


def test_profile_fields_are_external_and_complete():
    profile = json.loads(PROFILE.read_text())
    assert profile["slurm"] == {"partition": "q1h-20p", "account": "vini", "qos": "normal"}
    assert set(profile["resources"]) == {
        "nodes", "total_cpus", "memory", "walltime", "max_parallel_steps",
        "shutdown_margin_seconds", "termination_grace_seconds",
    }
    assert profile["task"]["mpi_processes"] == 4
    assert profile["runtime"]["siesta_executable"] == "siesta"
