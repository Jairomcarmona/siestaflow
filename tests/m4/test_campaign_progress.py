from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from qraft.execution.campaign_progress import (
    read_campaign_progress,
    render_campaign_progress,
)


REPO = Path(__file__).resolve().parents[2]


def campaign(root: Path) -> Path:
    (root / "input").mkdir()
    source = root / "input" / "task.fdf"
    source.write_text("test\n", encoding="utf-8")
    import hashlib

    config = {
        "schema_version": "1.0",
        "campaign_id": "progress-test",
        "system_id": "test",
        "slurm": {"partition": "p", "account": "a", "qos": "normal"},
        "resources": {
            "nodes": 1,
            "total_cpus": 1,
            "memory": "1G",
            "walltime": "00:05:00",
            "max_parallel_steps": 1,
            "shutdown_margin_seconds": 1,
            "termination_grace_seconds": 1,
        },
        "runtime": {
            "siesta_executable": "siesta",
            "srun_command": ["srun"],
            "environment": {},
        },
        "tasks": [{
            "task_id": "first",
            "input": "input/task.fdf",
            "input_hashes": {
                "input/task.fdf": hashlib.sha256(source.read_bytes()).hexdigest()
            },
            "required_artifacts": [],
            "mpi_processes": 1,
            "cpus_per_process": 1,
            "estimated_runtime_seconds": 1,
            "max_attempts": 1,
            "require_scf_converged": True,
        }],
    }
    path = root / "campaign.yaml"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_progress_before_execution_is_read_only(tmp_path: Path):
    campaign(tmp_path)
    snapshot = read_campaign_progress(tmp_path)
    assert snapshot["campaign_status"] == "PENDING"
    assert snapshot["completed"] == 0
    assert snapshot["total"] == 1
    assert snapshot["ready"] == ["first"]
    assert not (tmp_path / "state").exists()
    assert "0/1" in render_campaign_progress(snapshot)


def test_progress_cli_supports_machine_and_human_output(tmp_path: Path):
    campaign(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    machine = subprocess.run(
        [
            sys.executable,
            "-m",
            "qraft.cli",
            "campaign",
            "progress",
            str(tmp_path),
            "--json",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert machine.returncode == 0, machine.stderr
    assert json.loads(machine.stdout)["campaign_id"] == "progress-test"
    human = subprocess.run(
        [
            sys.executable,
            "-m",
            "qraft.cli",
            "campaign",
            "watch",
            str(tmp_path),
            "--iterations",
            "1",
            "--interval",
            "0.01",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert human.returncode == 0, human.stderr
    assert "CAMPAIGN progress-test" in human.stdout
