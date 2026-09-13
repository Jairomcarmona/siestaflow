"""Regression guards for result-bundle integrity and input validation."""

import hashlib
import json
from pathlib import Path

import pytest

from qraft.remote import ImportStatus, RemoteResultImporter, create_synthetic_result_bundle


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    path = tmp_path / "bundle"
    create_synthetic_result_bundle(path, "audit", "Siesta started\nSCF converged\nJob completed\n")
    return path


def _checksums(bundle: Path) -> None:
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(bundle).as_posix()}\n"
        for path in sorted(bundle.rglob("*"))
        if path.is_file() and path.name != "checksums.sha256"
    ]
    (bundle / "checksums.sha256").write_text("".join(lines), encoding="utf-8")


def _invalid(bundle: Path, finding: str) -> None:
    destination = bundle.parent / "imported"
    report = RemoteResultImporter().import_bundle(bundle, destination)
    assert report.status is ImportStatus.REMOTE_RESULTS_INVALID
    assert any(finding in item for item in report.findings), report.findings
    assert report.preserved_original is None
    assert not destination.exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_valid_bundle_retains_flags_and_original(bundle: Path, dry_run: bool):
    destination = bundle.parent / "imported"
    report = RemoteResultImporter().import_bundle(bundle, destination, expected_campaign_id="audit", dry_run=dry_run)
    assert report.status is ImportStatus.REMOTE_RESULTS_IMPORTED
    assert report.gate == "PASS"
    assert report.campaign_id == "audit"
    assert report.synthetic is True
    assert "SYNTHETIC_BUNDLE_NOT_REAL_EVIDENCE" in report.findings
    if dry_run:
        assert not destination.exists()
    else:
        for path in bundle.rglob("*"):
            if path.is_file():
                assert path.read_bytes() == (destination / "original_bundle" / path.relative_to(bundle)).read_bytes()
        assert json.loads((destination / "import_report.json").read_text())["real_evidence_promoted"] is False


@pytest.mark.parametrize("contents", ["", "\n \n"])
def test_empty_checksums_cannot_accept_tampered_output(bundle: Path, contents: str):
    (bundle / "results/siesta.out").write_text("Siesta started\nSCF converged\nJob completed\nALTERED\n")
    (bundle / "checksums.sha256").write_text(contents)
    _invalid(bundle, "checksum")


@pytest.mark.parametrize("name", RemoteResultImporter.REQUIRED[:-1])
def test_checksums_must_cover_every_required_payload(bundle: Path, name: str):
    checksums = bundle / "checksums.sha256"
    checksums.write_text("".join(line + "\n" for line in checksums.read_text().splitlines() if not line.endswith("  " + name)))
    _invalid(bundle, name)


@pytest.mark.parametrize("line", ["broken", "g" * 64 + "  events.jsonl", "0" * 63 + "  events.jsonl", "0" * 65 + "  events.jsonl"])
def test_malformed_checksum_entries_are_invalid(bundle: Path, line: str):
    with (bundle / "checksums.sha256").open("a") as stream:
        stream.write(line + "\n")
    _invalid(bundle, "checksum")


@pytest.mark.parametrize("alias", ["events.jsonl", "./events.jsonl"])
def test_duplicate_checksum_targets_are_invalid(bundle: Path, alias: str):
    digest = hashlib.sha256((bundle / "events.jsonl").read_bytes()).hexdigest()
    with (bundle / "checksums.sha256").open("a") as stream:
        stream.write(f"{digest}  {alias}\n")
    _invalid(bundle, "duplicate")


@pytest.mark.parametrize("name", ["../outside.txt", "/tmp/outside.txt", "C:/outside.txt", "C:outside.txt", "..\\outside.txt", "//server/share/file"])
def test_checksum_paths_are_rejected_before_external_read(bundle: Path, name: str, monkeypatch):
    outside = bundle.parent / "outside.txt"
    outside.write_text("outside")
    digest = hashlib.sha256(b"outside").hexdigest()
    with (bundle / "checksums.sha256").open("a") as stream:
        stream.write(f"{digest}  {name}\n")
    read_bytes = Path.read_bytes

    def guarded_read(path):
        assert path.resolve().is_relative_to(bundle.resolve()), "read escaped the bundle"
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    _invalid(bundle, "path")


@pytest.mark.parametrize("name", ["result_manifest.json", "checksums.sha256", "results/siesta.out", "unlisted.txt", "extra_dir"])
def test_external_symlinks_rejected_even_when_unlisted(bundle: Path, name: str, monkeypatch):
    path = bundle / name
    outside = bundle.parent / "outside"
    directory = name == "extra_dir"
    if directory:
        outside.mkdir()
        (outside / "secret.txt").write_text("outside")
    else:
        outside.write_bytes(path.read_bytes() if path.exists() else b"outside")
    if path.exists():
        path.unlink()
    path.symlink_to(outside, target_is_directory=directory)
    read_text, read_bytes = Path.read_text, Path.read_bytes

    def guarded_text(path, *args, **kwargs):
        assert path.resolve().is_relative_to(bundle.resolve()), "text read escaped the bundle"
        return read_text(path, *args, **kwargs)

    def guarded_bytes(path, *args, **kwargs):
        assert path.resolve().is_relative_to(bundle.resolve()), "binary read escaped the bundle"
        return read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_text)
    monkeypatch.setattr(Path, "read_bytes", guarded_bytes)
    _invalid(bundle, "path")


@pytest.mark.parametrize("manifest", [[], None, "text", 2, True, {}, {"campaign_id": []}, {"campaign_id": ""}, {"campaign_id": "audit", "synthetic": "false"}, {"campaign_id": "audit", "real_evidence": []}])
def test_invalid_manifest_types_are_reports_not_exceptions(bundle: Path, manifest):
    (bundle / "result_manifest.json").write_text(json.dumps(manifest))
    _checksums(bundle)
    _invalid(bundle, "manifest")


def test_non_utf8_manifest_is_invalid(bundle: Path):
    (bundle / "result_manifest.json").write_bytes(b"\xff")
    _checksums(bundle)
    _invalid(bundle, "manifest")


def test_non_utf8_checksums_are_invalid(bundle: Path):
    (bundle / "checksums.sha256").write_bytes(b"\xff")
    _invalid(bundle, "checksum")


def test_optional_boolean_fields_remain_optional(bundle: Path):
    (bundle / "result_manifest.json").write_text(json.dumps({"campaign_id": "audit"}))
    _checksums(bundle)
    report = RemoteResultImporter().import_bundle(bundle, bundle.parent / "imported")
    assert report.status is ImportStatus.REMOTE_RESULTS_IMPORTED
    assert report.synthetic is False


def test_missing_payload_keeps_incomplete_status(bundle: Path):
    (bundle / "events.jsonl").unlink()
    report = RemoteResultImporter().import_bundle(bundle, bundle.parent / "imported")
    assert report.status is ImportStatus.REMOTE_RESULTS_INCOMPLETE
    assert report.missing_files == ("events.jsonl",)


def test_binary_checksum_marker_remains_supported(bundle: Path):
    checksums = bundle / "checksums.sha256"
    checksums.write_text(checksums.read_text().replace("  ", " *"))
    report = RemoteResultImporter().import_bundle(bundle, bundle.parent / "imported")
    assert report.status is ImportStatus.REMOTE_RESULTS_IMPORTED


def test_internal_symlink_is_copied_without_reading_outside_bundle(bundle: Path):
    (bundle / "output-link").symlink_to(bundle / "results", target_is_directory=True)
    report = RemoteResultImporter().import_bundle(bundle, bundle.parent / "imported")
    assert report.status is ImportStatus.REMOTE_RESULTS_IMPORTED
    assert (Path(report.preserved_original) / "output-link/siesta.out").read_bytes() == (bundle / "results/siesta.out").read_bytes()


def test_checksummed_internal_file_symlink_remains_valid(bundle: Path):
    (bundle / "output-link").symlink_to(bundle / "results/siesta.out")
    _checksums(bundle)
    report = RemoteResultImporter().import_bundle(bundle, bundle.parent / "imported")
    assert report.status is ImportStatus.REMOTE_RESULTS_IMPORTED


@pytest.mark.parametrize("target", [".", "missing"])
def test_cyclic_or_dangling_symlinks_are_invalid(bundle: Path, target: str):
    (bundle / "link").symlink_to(bundle / target, target_is_directory=True)
    _invalid(bundle, "path")


def test_unlisted_special_file_is_invalid_without_opening_it(bundle: Path):
    import os

    os.mkfifo(bundle / "pipe")
    _invalid(bundle, "regular file")


def test_campaign_identity_mismatch_is_invalid(bundle: Path):
    destination = bundle.parent / "imported"
    report = RemoteResultImporter().import_bundle(bundle, destination, expected_campaign_id="different")
    assert report.status is ImportStatus.REMOTE_RESULTS_INVALID
    assert report.findings == ("campaign identity mismatch",)
    assert not destination.exists()


def test_nonconverged_output_remains_review(bundle: Path):
    (bundle / "results/siesta.out").write_text("Siesta started\nSCF cycle 1\n")
    _checksums(bundle)
    report = RemoteResultImporter().import_bundle(bundle, bundle.parent / "imported")
    assert report.status is ImportStatus.REMOTE_RESULTS_REVIEW
    assert report.synthetic is True
