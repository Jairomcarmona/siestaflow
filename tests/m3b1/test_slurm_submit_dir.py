from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from qraft.slurm_renderer import SlurmProfile, SlurmRenderer
from qraft.remote_environment import EnvironmentProbePackager


def profile() -> SlurmProfile:
    return SlurmProfile(
        name="verified-test-profile",
        verified_for_siesta=True,
        partition="test-partition",
        account="test-account",
        qos="test-qos",
        nodes=1,
        ntasks=1,
        cpus_per_task=1,
        memory="1G",
        walltime="00:02:00",
        signal="B:USR1@60",
        launcher_command="bash",
    )


def rendered(worker="scripts/worker.sh") -> str:
    result = SlurmRenderer().render(profile(), job_name="technical-smoke", worker_command=worker)
    assert result.status.value == "EXECUTABLE_AFTER_PROFILE_VERIFICATION"
    return result.script


def run_from_spool(spool: Path, submit_dir: Path | None, *, missing: bool = False):
    if submit_dir is None:
        setup = "unset SLURM_SUBMIT_DIR"
    elif missing:
        setup = 'export SLURM_SUBMIT_DIR="$PWD/does-not-exist"'
    else:
        relative = Path(os.path.relpath(submit_dir, spool)).as_posix()
        setup = f'export SLURM_SUBMIT_DIR="$(cd {shlex.quote(relative)} && pwd -P)"'
    return subprocess.run(["bash", "-c", setup + "; bash slurm_script"], cwd=spool, capture_output=True, text=True)


def test_render_uses_submit_dir_as_only_package_root_authority():
    script = rendered()
    assert '[[ -n "${SLURM_SUBMIT_DIR:-}" ]]' in script
    assert 'ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)' in script
    assert '[[ -f "$ROOT/package_manifest.json" ]]' in script
    root_section = script.split("# QRAFT_PACKAGE_ROOT_END", 1)[0]
    assert "BASH_SOURCE" not in root_section
    assert 'dirname "$0"' not in root_section
    assert "ROOT=$PWD" not in root_section and "ROOT=$(pwd" not in root_section


def test_environment_probe_generated_slurm_source_uses_same_fix():
    preparer = EnvironmentProbePackager().build_files()["prepare_scheduler_probe.py"]
    assert 'ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)' in preparer
    assert '[[ -f "$ROOT/probe_manifest.json" ]]' in preparer
    assert 'dirname "${BASH_SOURCE[0]}"' not in preparer


@pytest.mark.parametrize(
    "submit_dir,manifest,error",
    [
        (None, True, "SLURM_SUBMIT_DIR_NOT_SET"),
        ("missing", True, "INVALID_SLURM_SUBMIT_DIR"),
        ("existing", False, "INVALID_SLURM_SUBMIT_DIR"),
    ],
)
def test_invalid_submit_dir_blocks(tmp_path: Path, submit_dir: str | None, manifest: bool, error: str):
    package = tmp_path / "existing"; package.mkdir()
    if manifest:
        (package / "package_manifest.json").write_text("{}\n")
    spool = tmp_path / "var/spool/slurm/job12345"; spool.mkdir(parents=True)
    script = spool / "slurm_script"; script.write_text(rendered(), encoding="utf-8", newline="\n")
    if submit_dir is None:
        selected = None
    elif submit_dir == "missing":
        selected = package
    else:
        selected = package
    result = run_from_spool(spool, selected, missing=submit_dir == "missing")
    assert result.returncode == 2
    assert error in result.stderr


def test_spool_copy_runtime_writes_only_under_submit_root(tmp_path: Path):
    package = tmp_path / "package"; package.mkdir()
    (package / "package_manifest.json").write_text("{}\n")
    scripts = package / "scripts"; scripts.mkdir()
    (scripts / "worker.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "printf '%s\\n' \"$ROOT\" >evidence/root.txt\n"
        "printf work >work/created.txt\nprintf results >results/created.txt\n",
        encoding="utf-8", newline="\n",
    )
    spool = tmp_path / "var/spool/slurm/job12345"; spool.mkdir(parents=True)
    script = spool / "slurm_script"; script.write_text(rendered(), encoding="utf-8", newline="\n")
    before = {p.relative_to(spool).as_posix() for p in spool.rglob("*")}
    expected_root = subprocess.run(["bash", "-c", f"cd {shlex.quote(Path(os.path.relpath(package, spool)).as_posix())} && pwd -P"], cwd=spool, capture_output=True, text=True, check=True).stdout.strip()
    result = run_from_spool(spool, package)
    assert result.returncode == 0, result.stderr
    assert (package / "evidence/root.txt").read_text().strip() == expected_root
    assert (package / "work/created.txt").is_file()
    assert (package / "results/created.txt").is_file()
    after = {p.relative_to(spool).as_posix() for p in spool.rglob("*")}
    assert after == before
    print("SLURM_SUBMIT_DIR_RUNTIME_FIX_PASS")
    print("SPOOL_PATH_REGRESSION_TEST_PASS")
