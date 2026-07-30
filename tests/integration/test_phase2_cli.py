from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from siestaflow.project_packages import ProjectPackageLoader


REPO = Path(__file__).resolve().parents[2]
GENERIC = REPO / "examples/generic/minimal_siesta_smoke"


def run_cli(*arguments: str):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO / "src")
    return subprocess.run(
        [sys.executable, "-m", "siestaflow.cli", *arguments],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def project_arguments(destination: Path) -> tuple[str, ...]:
    return (
        "project",
        "init",
        str(destination),
        "--project-id",
        "research_cli_project",
        "--title",
        "Research CLI project",
        "--system-id",
        "xy_source",
        "--fdf",
        str(GENERIC / "systems/xy_cell.fdf"),
        "--structure",
        str(GENERIC / "structures/xy.xyz"),
        "--pseudo-manifest",
        str(GENERIC / "pseudopotentials/manifest.yaml"),
    )


def test_environment_check_cli_is_read_only_and_machine_readable(tmp_path: Path):
    result = run_cli(
        "environment",
        "check",
        "--siesta",
        str(tmp_path / "missing-siesta"),
        "--launcher",
        "direct",
        "--working-directory",
        str(tmp_path),
        "--json",
    )

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["metadata"]["read_only"] is True
    assert payload["metadata"]["job_submitted"] is False
    assert not tuple(tmp_path.iterdir())


def test_project_init_cli_creates_valid_idempotent_package(tmp_path: Path):
    destination = tmp_path / "research"
    first = run_cli(*project_arguments(destination), "--json")
    second = run_cli(*project_arguments(destination), "--json")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert json.loads(first.stdout)["status"] == "PROJECT_INITIALIZED_WITH_REVIEW"
    assert json.loads(second.stdout)["status"] == "PROJECT_ALREADY_INITIALIZED"
    assert ProjectPackageLoader().validate(destination).valid


def test_project_init_cli_dry_run_writes_nothing(tmp_path: Path):
    destination = tmp_path / "preview"
    result = run_cli(*project_arguments(destination), "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "PROJECT_INIT_PREVIEW"
    assert not destination.exists()


def test_input_validation_text_explains_remediation(tmp_path: Path):
    invalid = tmp_path / "invalid.fdf"
    invalid.write_text(
        "NumberOfAtoms nope\nUnknown.Experimental.Label 1\n",
        encoding="utf-8",
    )
    result = run_cli("input", "validate", str(invalid))

    assert result.returncode == 2
    assert "SIESTA INPUT: FAIL" in result.stdout
    assert "Suggested action:" in result.stdout
    assert "MISSING_REQUIRED_BLOCK" in result.stdout
