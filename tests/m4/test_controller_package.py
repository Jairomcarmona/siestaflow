from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from siestaflow.controller_package import ControllerPackageBuilder


REPO = Path(__file__).resolve().parents[2]


def source_campaign(root: Path) -> Path:
    (root / "input").mkdir()
    (root / "pseudopotentials").mkdir()
    source = root / "input" / "run.fdf"
    pseudo = root / "pseudopotentials" / "Mn.psml"
    source.write_text("SystemLabel test\n", encoding="utf-8")
    pseudo.write_text("<psml/>\n", encoding="utf-8")
    config = {
        "schema_version": "2.0",
        "campaign_id": "TEST_CONTROLLER_V02",
        "system_id": "test",
        "slurm": {
            "partition": "tt2d-100p",
            "account": "vini",
            "qos": "normal",
        },
        "resources": {
            "nodes": 5,
            "total_cpus": 100,
            "memory": "640000M",
            "walltime": "2-00:00:00",
            "max_parallel_steps": 1,
            "shutdown_margin_seconds": 1800,
            "termination_grace_seconds": 30,
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
                "processes_per_node": 20,
            },
            "exclusive": True,
            "environment": {"OMP_NUM_THREADS": "1"},
        },
        "tasks": [{
            "task_id": "reference",
            "input": "input/run.fdf",
            "input_hashes": {
                "input/run.fdf": hashlib.sha256(source.read_bytes()).hexdigest(),
                "pseudopotentials/Mn.psml": hashlib.sha256(pseudo.read_bytes()).hexdigest(),
            },
            "required_artifacts": [],
            "mpi_processes": 100,
            "cpus_per_process": 1,
            "nodes": 5,
            "estimated_runtime_seconds": 300,
            "max_attempts": 2,
            "require_scf_converged": True,
        }],
    }
    path = root / "campaign.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def test_controller_package_is_reproducible_and_cleanly_verifies(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(source)
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first = ControllerPackageBuilder(REPO).build(campaign, one)
    second = ControllerPackageBuilder(REPO).build(campaign, two)
    assert Path(first.zip_path).read_bytes() == Path(second.zip_path).read_bytes()
    extraction = tmp_path / "extract"
    extraction.mkdir()
    with ZipFile(first.zip_path) as archive:
        archive.extractall(extraction)
    root = extraction / "TEST_CONTROLLER_V02"
    result = subprocess.run(
        [sys.executable, "verify_package.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "SIESTAFLOW_CONTROLLER_PACKAGE_VERIFIED" in result.stdout
    assert "mpiexec.hydra" in (root / "campaign.yaml").read_text()
    submit = (root / "submit.slurm").read_text()
    assert "SIESTAFLOW_SIESTA_MODULE_LOAD_WARNING" in submit
    assert "SIESTAFLOW_SIESTA_VERSION_PROBE_WARNING" in submit
    assert "python3 scripts/run_worker.py" in submit


def test_controller_package_dry_run_and_cli_have_no_submission(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(source)
    dry = tmp_path / "dry"
    result = ControllerPackageBuilder(REPO).build(campaign, dry, dry_run=True)
    assert result.status == "DRY_RUN_NO_SIDE_EFFECTS"
    assert not dry.exists()
    output = tmp_path / "cli"
    output.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "siestaflow.cli",
            "remote",
            "controller-package",
            str(campaign),
            "--output",
            str(output),
            "--json",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "CONTROLLER_PACKAGE_READY_FOR_MANUAL_TRANSFER"
    assert Path(payload["zip_path"]).is_file()
    assert not list(output.rglob("sbatch.invoked"))
