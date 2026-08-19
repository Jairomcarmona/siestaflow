from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from qraft.remote_environment import (
    EnvironmentProbePackager,
    EvidenceStatus,
    PROBE_ID,
    RemoteEnvironmentImporter,
    RemoteEnvironmentStatus,
    YoltlaProfile,
    create_environment_fixture_bundle,
    redact_environment,
)
from qraft.engines.siesta.pseudopotentials import PseudopotentialManifest


REFERENCE_MANIFEST = Path(__file__).resolve().parents[2] / "examples" / "reference_projects" / "birnessite_mn_o" / "pseudopotentials" / "manifest.yaml"
REFERENCE_REQUIREMENTS = {item.filename: item.sha256 for item in PseudopotentialManifest.load(REFERENCE_MANIFEST).entries}


def test_package_is_reproducible_complete_and_science_free(tmp_path: Path):
    packager = EnvironmentProbePackager(REFERENCE_REQUIREMENTS)
    first = packager.build_files()
    second = packager.build_files()
    assert first == second
    assert {
        "README_RUN.md", "EXACT_COMMANDS.md", "PROBE_CHECKLIST.md",
        "probe_manifest.json", "probe_manifest.sha256", "expected_evidence.json",
        "run_login_probe.sh", "prepare_scheduler_probe.py",
        "submit_environment_probe.slurm", "inspect_probe_job.sh",
        "collect_probe_results.sh", "verify_local_package.py",
        "checksums.sha256",
    } <= set(first)
    manifest = json.loads(first["probe_manifest.json"])
    assert manifest["contains_fdf"] is False
    assert manifest["contains_pseudopotentials"] is False
    assert manifest["scheduler_selection_policy"] == "UNIQUE_COMPATIBLE_DEFAULT_PARTITION_OR_EVIDENCE_BOUND_HUMAN_SELECTION"
    assert not any(name.lower().endswith((".fdf", ".xyz", ".psml", ".psf")) for name in first)
    for forbidden in ("BEGIN PRIVATE KEY", "AKIA", "ghp_", "Bearer ey"):
        assert forbidden not in "\n".join(first.values())
    plan = packager.package(tmp_path)
    assert Path(plan.destination).is_dir()
    assert len(plan.files) == len(first)


def test_dry_run_has_zero_side_effects(tmp_path: Path):
    output = tmp_path / "absent"
    plan = EnvironmentProbePackager(REFERENCE_REQUIREMENTS).package(output, dry_run=True)
    assert plan.dry_run is True
    assert not output.exists()


def test_scripts_have_safety_guards_and_no_automatic_submission():
    files = EnvironmentProbePackager(REFERENCE_REQUIREMENTS).build_files()
    for name in ("run_login_probe.sh", "submit_environment_probe.slurm", "inspect_probe_job.sh", "collect_probe_results.sh", "scripts/probe_common.sh"):
        assert "set -euo pipefail" in files[name]
    assert "#SBATCH --signal=B:USR1@60" in files["submit_environment_probe.slurm"]
    assert "SCHEDULER_PROBE_NOT_PREPARED" in files["submit_environment_probe.slurm"]
    executable_text = "\n".join(content for name, content in files.items() if not name.endswith(".md"))
    assert not any(line.lstrip().startswith("sbatch ") for line in executable_text.splitlines())
    assert "sudo " not in executable_text
    assert "conda create" not in executable_text
    assert "curl " not in executable_text and "wget " not in executable_text


def test_exact_commands_are_human_operated_and_contain_submission_step():
    commands = EnvironmentProbePackager(REFERENCE_REQUIREMENTS).build_files()["EXACT_COMMANDS.md"]
    assert "sbatch generated/submit_environment_probe.slurm" in commands
    assert "manually" in commands.lower()
    assert "ssh " not in commands.lower()
    assert "scp " not in commands.lower()


def test_sensitive_environment_variables_are_removed():
    values = {
        "SLURM_JOB_ID": "1", "PATH": "/bin", "API_TOKEN": "secret",
        "PASSWORD": "secret", "COOKIE_VALUE": "secret", "SAFE_KEYSTONE": "also secret",
    }
    assert redact_environment(values) == {"SLURM_JOB_ID": "1", "PATH": "/bin"}


def test_synthetic_complete_bundle_is_review_and_profile_is_inferred(tmp_path: Path):
    bundle = tmp_path / "bundle"
    create_environment_fixture_bundle(bundle, pseudopotential_requirements=REFERENCE_REQUIREMENTS)
    report = RemoteEnvironmentImporter().import_bundle(bundle, tmp_path / "imported")
    assert report.status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_REVIEW
    assert report.synthetic is True
    assert "SYNTHETIC_BUNDLE_REJECTED_AS_REAL_EVIDENCE" in report.findings
    assert all(report.requirements.values())
    assert report.profile.fields["partition"].evidence_status is EvidenceStatus.INFERRED
    assert (tmp_path / "imported" / "original_bundle").is_dir()


def test_altered_bundle_fails(tmp_path: Path):
    bundle = tmp_path / "bundle"
    create_environment_fixture_bundle(bundle, pseudopotential_requirements=REFERENCE_REQUIREMENTS)
    (bundle / "scheduler_probe" / "summary.json").write_text("altered", encoding="utf-8")
    report = RemoteEnvironmentImporter().import_bundle(bundle, tmp_path / "out")
    assert report.status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED
    assert any("checksum mismatch" in item for item in report.findings)


def test_incomplete_bundle_remains_incomplete_and_null(tmp_path: Path):
    bundle = tmp_path / "bundle"
    create_environment_fixture_bundle(bundle, complete=False, pseudopotential_requirements=REFERENCE_REQUIREMENTS)
    report = RemoteEnvironmentImporter().import_bundle(bundle, tmp_path / "out")
    assert report.status is RemoteEnvironmentStatus.REMOTE_EVIDENCE_INCOMPLETE
    assert "mpi_discovery/summary.json" in report.missing_files
    assert report.profile.fields["launcher"].value is None
    assert report.profile.fields["launcher"].evidence_status is EvidenceStatus.MISSING


def test_empty_squeue_does_not_create_success_without_terminal_evidence(tmp_path: Path):
    bundle = tmp_path / "bundle"
    create_environment_fixture_bundle(bundle, squeue_present=False, terminal_evidence=False, pseudopotential_requirements=REFERENCE_REQUIREMENTS)
    report = RemoteEnvironmentImporter().import_bundle(bundle, tmp_path / "out")
    assert report.status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_REVIEW
    assert report.requirements["slurm_job_terminal_demonstrated"] is False
    assert "EMPTY_SQUEUE_IS_NOT_TERMINAL_SUCCESS" in report.findings


def test_pseudo_hash_mismatch_is_blocking(tmp_path: Path):
    bundle = tmp_path / "bundle"
    create_environment_fixture_bundle(bundle, pseudo_status="PSEUDOPOTENTIAL_SET_HASH_MISMATCH", pseudopotential_requirements=REFERENCE_REQUIREMENTS)
    report = RemoteEnvironmentImporter().import_bundle(bundle, tmp_path / "out")
    assert report.status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED
    assert report.requirements["pseudopotentials_verified"] is False


def test_tar_path_traversal_is_rejected(tmp_path: Path):
    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo("../escape.txt")
        data = b"unsafe"
        info.size = len(data)
        handle.addfile(info, io.BytesIO(data))
    report = RemoteEnvironmentImporter().import_bundle(archive, tmp_path / "out")
    assert report.status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED
    assert not (tmp_path / "escape.txt").exists()


def test_expected_pseudo_hashes_are_embedded_only_as_manifest():
    files = EnvironmentProbePackager(REFERENCE_REQUIREMENTS).build_files()
    assert all(digest in files["probe_manifest.json"] for digest in REFERENCE_REQUIREMENTS.values())
    assert "read_bytes" in files["scripts/verify_pseudos.py"]
    assert "shutil.copy" not in files["scripts/verify_pseudos.py"]


def test_pending_profile_has_all_required_null_fields():
    profile = YoltlaProfile.pending()
    assert profile.profile_status == "REMOTE_EVIDENCE_PENDING"
    assert len(profile.fields) == 19
    assert all(field.value is None and field.evidence_status is EvidenceStatus.MISSING for field in profile.fields.values())


def _run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    return subprocess.run([sys.executable, "-m", "qraft.cli", *args], cwd=repo, env=env, capture_output=True, text=True, timeout=30)


def test_cli_package_and_synthetic_import(tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "work"
    output = tmp_path / "packages"
    dry = _run_cli(repo, "--workspace", str(workspace), "remote", "environment", "package", "--output", str(output), "--dry-run", "--json")
    assert dry.returncode == 0
    assert not output.exists()
    made = _run_cli(repo, "--workspace", str(workspace), "remote", "environment", "package", "--output", str(output), "--json")
    assert made.returncode == 0
    bundle = tmp_path / "bundle"
    create_environment_fixture_bundle(bundle, pseudopotential_requirements=REFERENCE_REQUIREMENTS)
    imported = _run_cli(repo, "--workspace", str(workspace), "remote", "environment", "import", str(bundle), "--json")
    assert imported.returncode == 0
    assert "REMOTE_ENVIRONMENT_REVIEW" in imported.stdout


def test_manifest_identity_and_scientific_false_are_binding(tmp_path: Path):
    bundle = tmp_path / "bundle"
    create_environment_fixture_bundle(bundle, pseudopotential_requirements=REFERENCE_REQUIREMENTS)
    manifest_path = bundle / "results_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["scientific_calculation_performed"] = True
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    # Re-hashing an invalid claim must not make it acceptable.
    import hashlib
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (bundle / "results_manifest.sha256").write_text(f"{digest}  results_manifest.json\n")
    checks = []
    for path in sorted(item for item in bundle.rglob("*") if item.is_file() and item.name != "checksums.sha256"):
        checks.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(bundle).as_posix()}\n")
    (bundle / "checksums.sha256").write_text("".join(checks))
    report = RemoteEnvironmentImporter().import_bundle(bundle, tmp_path / "out")
    assert report.status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED
    assert any("scientific_calculation_performed=false" in item for item in report.findings)
