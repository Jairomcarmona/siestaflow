import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qraft.remote import RemotePackager, RemoteResultImporter, create_synthetic_result_bundle
from qraft.project_packages import ProjectPackageLoader
from qraft.siesta_campaigns import SiestaCampaignFactory
from qraft.slurm_renderer import SlurmProfile, SlurmRenderer


def test_slurm_preview_preserves_nulls_and_never_contains_submission_command():
    result = SlurmRenderer().render(SlurmProfile(), job_name="test", worker_command="qraft worker")
    assert result.status.value == "PREVIEW_WITH_UNVERIFIED_PROFILE"
    assert "partition=null" in result.script
    assert "LAMMPS" not in result.script
    assert not any(line.lstrip().casefold().startswith("sbatch ") for line in result.script.splitlines())
    assert result.script.count("#!/usr/bin/env bash") == 1


def test_verified_complete_profile_can_render_executable():
    profile = SlurmProfile("TEST_VERIFIED", True, "p", "a", None, 1, 4, 1, "4G", "00:10:00", "B:USR1@60", (), "srun")
    result = SlurmRenderer().render(profile, job_name="test", worker_command="worker")
    assert result.status.value == "EXECUTABLE_AFTER_PROFILE_VERIFICATION"
    assert result.script.rstrip().endswith("srun worker")


def _reference_definition(reference_package: Path):
    package = ProjectPackageLoader().load(reference_package)
    definition, _ = SiestaCampaignFactory().from_package(package, "m1_sanity")
    return package, definition, package.root / package.system("m1_reference").input_template


def test_remote_package_is_reproducible_and_hashes_validate(reference_package: Path, tmp_path: Path):
    package, definition, input_path = _reference_definition(reference_package)
    packager = RemotePackager()
    first = packager.build_files(definition, input_path)
    second = packager.build_files(definition, input_path)
    assert first == second
    plan = packager.package(definition, input_path, tmp_path / "remote_validation")
    root = Path(plan.destination)
    assert (root / "preflight.sh").read_text().rstrip().endswith("exit 2")
    assert "REMOTE_PREFLIGHT_REQUIRES_CONFIGURATION" in (root / "preflight.sh").read_text()
    assert not list(root.rglob("*.psml"))
    for line in (root / "checksums.sha256").read_text().splitlines():
        digest, name = line.split(None, 1)
        assert hashlib.sha256((root / name.strip()).read_bytes()).hexdigest() == digest


def test_remote_package_dry_run_has_zero_side_effects(reference_package: Path, tmp_path: Path):
    _, definition, input_path = _reference_definition(reference_package)
    output = tmp_path / "absent"
    plan = RemotePackager().package(definition, input_path, output, dry_run=True)
    assert plan.dry_run is True
    assert not output.exists()


def test_result_bundle_import_valid_tampered_and_incomplete(tmp_path: Path):
    output = "Siesta Version : SYNTHETIC\nSiesta started\nSCF cycle 1\nSCF converged\nJob completed\n"
    bundle = tmp_path / "bundle"
    create_synthetic_result_bundle(bundle, "CAMPAIGN_X", output)
    report = RemoteResultImporter().import_bundle(bundle, tmp_path / "imported", expected_campaign_id="CAMPAIGN_X")
    assert report.status.value == "REMOTE_RESULTS_IMPORTED"
    assert report.synthetic is True
    assert "SYNTHETIC_BUNDLE_NOT_REAL_EVIDENCE" in report.findings
    altered = tmp_path / "altered"
    create_synthetic_result_bundle(altered, "CAMPAIGN_X", output)
    (altered / "results" / "siesta.out").write_text("altered", encoding="utf-8")
    assert RemoteResultImporter().import_bundle(altered, tmp_path / "bad").status.value == "REMOTE_RESULTS_INVALID"
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    assert RemoteResultImporter().import_bundle(incomplete, tmp_path / "review").status.value == "REMOTE_RESULTS_INCOMPLETE"


def _run_cli(repo: Path, *args: str):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    return subprocess.run([sys.executable, "-m", "qraft.cli", *args], cwd=repo, env=env, capture_output=True, text=True, timeout=30)


def test_cli_full_local_flow_and_dry_run(reference_package: Path, tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "work"
    common = ("--workspace", str(workspace))
    input_path = reference_package / "systems" / "m1_reference.fdf"
    assert _run_cli(repo, *common, "fdf", "inspect", str(input_path), "--json").returncode == 0
    assert _run_cli(repo, *common, "input", "validate", str(input_path), "--json").returncode == 0
    dry = _run_cli(repo, *common, "campaign", "create", "--project", str(reference_package), "--campaign-id", "m1_sanity", "--dry-run", "--json")
    assert dry.returncode == 0 and not workspace.exists()
    assert _run_cli(repo, *common, "campaign", "create", "--project", str(reference_package), "--campaign-id", "m1_sanity", "--json").returncode == 0
    assert _run_cli(repo, *common, "campaign", "validate", "m1_sanity", "--json").returncode == 0
    assert _run_cli(repo, *common, "campaign", "simulate", "m1_sanity", "--json").returncode == 0
    assert _run_cli(repo, *common, "remote", "package", "m1_sanity", "--json").returncode == 0


def test_context_remains_exactly_642_zip_members():
    import zipfile

    root = Path(__file__).resolve().parents[3]
    context = root / "context"
    archive = root / "SIESTAFLOW_CONTEXT_v01.zip"
    with zipfile.ZipFile(archive) as handle:
        members = [item for item in handle.infolist() if not item.is_dir()]
        assert len(members) == 642
        for member in members:
            parts = Path(member.filename).parts
            relative = Path(*parts[1:]) if parts and parts[0] == "SIESTAFLOW_CONTEXT" else Path(*parts)
            target = context / relative
            assert target.is_file()
            assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(handle.read(member)).digest()
    assert len([path for path in context.rglob("*") if path.is_file()]) == 642
