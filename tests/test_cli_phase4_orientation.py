"""Phase 4 freezes first-screen orientation and target classification."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import qraft.target_classifier as target_classifier
from qraft.cli import main
from qraft.target_classifier import (
    ACCEPTED_TARGET_TYPES,
    TargetClassification,
    TargetClassificationError,
    TargetKind,
    classify_target,
)
from tests.runs.test_prepared_run import _prepared


REPO = Path(__file__).resolve().parents[1]
FDF = REPO / "examples/generic/minimal_siesta_smoke/systems/xy_cell.fdf"
WORKFLOW = REPO / "examples/workflows/restart_chain_compile_only/workflow.json"
WORKFLOW_LOCK = REPO / "tests/fixtures/phase3/yoltla_job_781100/workflow.lock.json"


class _UnreadableStdin:
    def read(self, *_args, **_kwargs):
        raise AssertionError("qraft orientation consumed stdin")

    def readline(self, *_args, **_kwargs):
        raise AssertionError("qraft orientation consumed stdin")

    def isatty(self) -> bool:
        return False


def _campaign(path: Path) -> Path:
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "campaign_id": "phase-4-classifier",
        "engine": "siesta",
        "protocol": "convergence",
        "system": {"fdf": "system.fdf"},
        "parameters": {
            "mesh_cutoff": {
                "mode": "scan", "values": [80, 100], "unit": "Ry",
            },
            "basis_size": {"mode": "fixed", "value": "DZP"},
        },
        "criterion": {
            "metric": "energy_per_atom", "delta": 0.01,
            "unit": "eV", "consecutive": 1,
        },
    }), encoding="utf-8")
    return path


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    if root.is_file():
        stat = root.stat()
        return {root.name: (root.read_bytes(), stat.st_mtime_ns)}
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_qraft_and_help_are_identical_and_never_enter_repl_or_read_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    entered: list[bool] = []
    monkeypatch.setattr("qraft.repl.run_repl", lambda: entered.append(True) or 0)
    monkeypatch.setattr(sys, "stdin", _UnreadableStdin())

    assert main([]) == 0
    no_argument = capsys.readouterr()
    assert main(["--help"]) == 0
    explicit_help = capsys.readouterr()

    assert no_argument.out == explicit_help.out
    assert no_argument.err == explicit_help.err == ""
    assert entered == []


def test_orientation_is_frozen_high_level_discovery(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    text = capsys.readouterr().out
    for section in (
        "QRAFT — run reproducible scientific campaigns",
        "GET STARTED", "MONITOR / CONTINUE", "RESULTS", "LEARN",
        "Complete workflow:", "Setup and diagnostics:",
        "Advanced workflows and compatibility:",
    ):
        assert section in text
    for invocation in (
        "init [PATH]", "check TARGET", "run TARGET", "status [TARGET]",
        "resume [TARGET]", "results [TARGET]", "examples [TOPIC]",
        "qraft setup --help", "qraft inspect --help", "qraft advanced --help",
        "qraft help migration",
    ):
        assert invocation in text
    assert "_fdf-run" not in text
    assert "qraft validate" not in text
    assert "qraft env" not in text
    assert "qraft config" not in text
    assert "qraft>" not in text


@pytest.mark.parametrize("command", ["init", "check", "setup", "inspect", "advanced"])
def test_phase4_discovery_help_routes_exit_zero(command: str) -> None:
    with pytest.raises(SystemExit) as result:
        main([command, "--help"])
    assert result.value.code == 0


def test_check_classifies_but_never_claims_readiness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _campaign(tmp_path / "campaign.yaml")
    assert main(["check", str(campaign), "--json"]) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "BLOCKED"
    assert payload["error"]["code"] == "CHECK_NOT_IMPLEMENTED_PHASE_4"
    assert "CAMPAIGN_SPEC" in payload["error"]["message"]
    assert "ready" not in payload["error"]["message"].casefold()
    assert captured.err == ""


def test_init_guidance_points_to_check_without_changing_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "campaign.yaml"
    assert main(["init", str(target), "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "CREATED"
    assert payload["path"] == str(target.resolve())
    assert "qraft check" in payload["next_step"]
    assert "qraft validate campaign.yaml --profile local" in target.read_text(
        encoding="utf-8"
    )
    assert captured.err == ""


def test_invalid_check_target_uses_structured_expected_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = tmp_path / "unknown.data"
    invalid.write_text("not a supported qraft target\n", encoding="utf-8")
    assert main(["check", str(invalid), "--json"]) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "BLOCKED"
    assert payload["error"]["code"] == "TARGET_NOT_CLASSIFIABLE"
    assert all(kind in payload["error"]["message"] for kind in ACCEPTED_TARGET_TYPES)
    assert captured.err == ""


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (FDF, TargetKind.FDF),
        (WORKFLOW, TargetKind.WORKFLOW_DEFINITION),
        (WORKFLOW_LOCK, TargetKind.WORKFLOW_LOCK),
    ],
)
def test_real_repository_targets_classify_without_writes(
    path: Path, kind: TargetKind,
) -> None:
    before = _snapshot(path)
    first = classify_target(path)
    second = classify_target(path)
    assert first == second
    assert first.kind is kind
    assert _snapshot(path) == before


def test_valid_campaign_and_extension_mismatch_use_content(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path / "campaign.bin")
    misleading = tmp_path / "looks-structured.json"
    shutil.copyfile(FDF, misleading)
    assert classify_target(campaign).kind is TargetKind.CAMPAIGN_SPEC
    assert classify_target(misleading).kind is TargetKind.FDF


def test_prepared_package_classification_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, package = _prepared(tmp_path)
    before = _snapshot(package)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("classification attempted execution"),
    )
    classified = classify_target(package)
    assert classified.kind is TargetKind.PREPARED_RUN_PACKAGE
    assert _snapshot(package) == before


def test_runs_root_classification_is_read_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "session.json").write_text(json.dumps({
        "schema_version": "1.0",
        "fdf": None,
        "profile": None,
        "protocol": "single_fdf",
        "pseudo_manifest": None,
        "project_config": None,
        "recipe": None,
        "runs_root": str(runs_root),
        "overrides": {},
    }), encoding="utf-8")
    before = _snapshot(runs_root)
    assert classify_target(runs_root).kind is TargetKind.RUNS_ROOT
    assert _snapshot(runs_root) == before


@pytest.mark.parametrize("relative", ["missing", "invalid-directory"])
def test_missing_and_invalid_targets_fail_explicitly(
    tmp_path: Path, relative: str,
) -> None:
    target = tmp_path / relative
    expected = "TARGET_NOT_FOUND"
    if relative == "invalid-directory":
        target.mkdir()
        expected = "TARGET_NOT_CLASSIFIABLE"
    with pytest.raises(TargetClassificationError) as result:
        classify_target(target)
    assert result.value.code == expected
    assert result.value.expected == "one of: " + ", ".join(ACCEPTED_TARGET_TYPES)


def test_multiple_valid_interpretations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "ambiguous"
    target.write_text("fixture", encoding="utf-8")
    resolved = target.resolve()
    monkeypatch.setattr(target_classifier, "_classify_file", lambda _path: (
        TargetClassification(TargetKind.FDF, resolved, "fixture-a"),
        TargetClassification(TargetKind.CAMPAIGN_SPEC, resolved, "fixture-b"),
    ))
    with pytest.raises(TargetClassificationError) as result:
        classify_target(target)
    assert result.value.code == "TARGET_AMBIGUOUS"
