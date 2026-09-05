"""Phase-2 output policy and CLI-boundary error contracts."""

from __future__ import annotations

import json
from pathlib import Path

import qraft.cli as cli


def test_human_expected_error_uses_stderr_without_traceback(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "campaign.yaml"
    target.write_text("existing", encoding="utf-8")

    assert cli.main(["init", str(target)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "BLOCKED [INVALID_INPUT]:" in captured.err
    assert "Why:" in captured.err
    assert "Fix:" in captured.err
    assert "Then run:" in captured.err
    assert "Traceback" not in captured.err


def test_json_expected_error_is_one_json_value_on_stdout(
    tmp_path: Path, capsys,
) -> None:
    missing = tmp_path / "missing.fdf"

    assert cli.main(["validate", str(missing), "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "BLOCKED"
    assert payload["error"]["code"] == "INPUT_NOT_FOUND"
    assert "BLOCKED [" not in captured.out
    assert captured.err.count("DEPRECATED:") == 1
    assert "qraft check" in captured.err


def test_json_argument_error_keeps_stdout_machine_readable(capsys) -> None:
    assert cli.main(["--json", "validate"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"
    assert "BLOCKED [" not in captured.out
    assert "usage:" in captured.err


def test_json_success_is_unchanged_and_global_json_is_accepted(
    tmp_path: Path, capsys,
) -> None:
    runs_root = tmp_path / "runs"

    assert cli.main(["--json", "status", "--runs-root", str(runs_root)]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["campaign"] is None
    assert payload["root"] == str(runs_root)
    assert captured.err == ""


def test_current_noninteractive_commands_accept_global_input_and_color_policy(
    tmp_path: Path, capsys,
) -> None:
    runs_root = tmp_path / "runs"

    assert cli.main([
        "status", "--runs-root", str(runs_root), "--json", "--no-input", "--no-color",
    ]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["campaign"] is None
    assert "\x1b[" not in captured.out
    assert captured.err == ""


def test_color_policy_respects_json_no_color_no_color_environment_and_non_tty() -> None:
    assert cli.resolve_cli_output_policy(
        ["status"], environ={}, stdout_isatty=True,
    ).color_enabled is True
    assert cli.resolve_cli_output_policy(
        ["status", "--json"], environ={}, stdout_isatty=True,
    ).color_enabled is False
    assert cli.resolve_cli_output_policy(
        ["status", "--no-color"], environ={}, stdout_isatty=True,
    ).color_enabled is False
    assert cli.resolve_cli_output_policy(
        ["status"], environ={"NO_COLOR": ""}, stdout_isatty=True,
    ).color_enabled is False
    assert cli.resolve_cli_output_policy(
        ["status"], environ={}, stdout_isatty=False,
    ).color_enabled is False


def test_unexpected_cli_failure_returns_one_without_traceback(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    def fail(_args):
        raise AssertionError("injected internal failure")

    monkeypatch.setattr(cli, "_dispatch", fail)

    assert cli.main(["status", "--runs-root", str(tmp_path / "runs")]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "QRAFT_INTERNAL_ERROR" in captured.err
    assert "Traceback" not in captured.err
