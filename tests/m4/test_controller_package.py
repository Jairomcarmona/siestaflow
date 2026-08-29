from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from qraft.controller_package import ControllerPackageBuilder


REPO = Path(__file__).resolve().parents[2]


def source_campaign(
    root: Path, *, qos: str | None = "normal", include_qos: bool = True,
    account: str | None = "vini", include_account: bool = True,
) -> Path:
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
        "slurm": {"partition": "tt2d-100p"},
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
    if include_qos:
        config["slurm"]["qos"] = qos
    if include_account:
        config["slurm"]["account"] = account
    path = root / "campaign.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def resolution_lock(root: Path, *, qos: str | None, account: str | None = "vini") -> Path:
    path = root / "run.lock.json"
    path.write_text(json.dumps({
        "payload": {"metadata": {"execution_resolution": {
            "resolution_mode": "MANUAL_COMPATIBILITY_OVERRIDE",
            "human_confirmed": True,
            "selected_partition": "tt2d-100p", "selected_account": account,
            "selected_qos": qos, "selected_nodes": 5,
            "selected_total_ranks": 100, "selected_walltime": "2-00:00:00",
        }}},
    }), encoding="utf-8")
    return path


def test_hydra_package_requires_explicit_bootstrap(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(source)
    data = json.loads(campaign.read_text(encoding="utf-8"))
    data["runtime"]["launcher"].pop("bootstrap")
    campaign.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="runtime.launcher.bootstrap"):
        ControllerPackageBuilder(REPO).build(campaign, output)
    assert not list(output.rglob("submit.slurm"))


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
    assert "QRAFT_CONTROLLER_PACKAGE_VERIFIED" in result.stdout
    (root / "qraft.out").write_text("derived campaign evidence\n", encoding="utf-8")
    repeated = subprocess.run(
        [sys.executable, "verify_package.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert "mpiexec.hydra" in (root / "campaign.yaml").read_text()
    submit = (root / "submit.slurm").read_text()
    assert "QRAFT_SIESTA_MODULE_LOAD_WARNING" in submit
    assert "siesta --version" not in submit
    assert "export QRAFT_PYTHON=python3" in submit
    assert '"$QRAFT_PYTHON" verify_package.py' in submit
    assert 'exec "$QRAFT_PYTHON" scripts/run_worker.py campaign.yaml "$ROOT"' in submit
    assert submit.count("#SBATCH --account=vini") == 1
    assert submit.index("export OMP_NUM_THREADS=1") < submit.index("command -v siesta")


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
            "qraft.cli",
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


@pytest.mark.parametrize("include_qos", [False, True])
def test_controller_package_without_explicit_qos_omits_directive_and_verifies(
    tmp_path: Path, include_qos: bool,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(source, qos=None, include_qos=include_qos)
    output = tmp_path / "output"
    output.mkdir()
    lock = resolution_lock(source, qos=None)
    result = ControllerPackageBuilder(REPO).build(
        campaign, output, provenance_files={"run.lock.json": lock},
    )
    root = Path(result.destination)
    submit = (root / "submit.slurm").read_text(encoding="utf-8")
    assert "#SBATCH --qos=" not in submit
    verified = subprocess.run(
        [sys.executable, "verify_package.py"], cwd=root,
        capture_output=True, text=True,
    )
    assert verified.returncode == 0, verified.stderr


@pytest.mark.parametrize("include_account", [False, True])
def test_controller_package_without_explicit_account_omits_directive_and_verifies(
    tmp_path: Path, include_account: bool,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(
        source, account=None, include_account=include_account,
    )
    output = tmp_path / "output"
    output.mkdir()
    lock = resolution_lock(source, qos="normal", account=None)
    result = ControllerPackageBuilder(REPO).build(
        campaign, output, provenance_files={"run.lock.json": lock},
    )
    root = Path(result.destination)
    submit = (root / "submit.slurm").read_text(encoding="utf-8")
    assert "#SBATCH --account=" not in submit
    verified = subprocess.run(
        [sys.executable, "verify_package.py"], cwd=root,
        capture_output=True, text=True,
    )
    assert verified.returncode == 0, verified.stderr


@pytest.mark.parametrize(
    ("campaign_account", "include_account", "lock_account"),
    [(None, False, "vini"), ("vini", True, None)],
)
def test_controller_package_rejects_account_resolution_mismatches(
    tmp_path: Path, campaign_account: str | None, include_account: bool,
    lock_account: str | None,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(
        source, account=campaign_account, include_account=include_account,
    )
    with pytest.raises(ValueError, match="generated Slurm campaign disagree"):
        ControllerPackageBuilder(REPO).build(
            campaign, tmp_path / "output",
            provenance_files={"run.lock.json": resolution_lock(source, qos="normal", account=lock_account)},
        )


def test_controller_package_keeps_explicit_qos_and_rejects_resolution_mismatch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    campaign = source_campaign(source, qos="normal")
    output = tmp_path / "output"
    output.mkdir()
    matching = resolution_lock(source, qos="normal")
    result = ControllerPackageBuilder(REPO).build(
        campaign, output, provenance_files={"run.lock.json": matching},
    )
    assert (Path(result.destination) / "submit.slurm").read_text().count(
        "#SBATCH --qos=normal"
    ) == 1
    mismatch = source / "mismatch.lock.json"
    mismatch.write_text(
        resolution_lock(source, qos="high").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="generated Slurm campaign disagree"):
        ControllerPackageBuilder(REPO).build(
            campaign, tmp_path / "mismatch-output",
            provenance_files={"run.lock.json": mismatch},
        )
