"""Phase-3 canonical grouping, compatibility, and routing contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import pytest

import qraft.cli as cli


def _primitive(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {key: _primitive(item) for key, item in value.items()}
    return value


def _install_recording_dispatch(monkeypatch) -> None:
    def dispatch(args) -> int:
        payload = {
            key: _primitive(value)
            for key, value in vars(args).items()
            if not key.startswith("_")
        }
        print(json.dumps(payload, sort_keys=True))
        return 0

    monkeypatch.setattr(cli, "_dispatch", dispatch)


@pytest.mark.parametrize(
    ("group", "children"),
    [
        ("setup", {"env", "config", "profile"}),
        ("inspect", {"fdf", "input", "rules", "pseudo", "plan"}),
        (
            "advanced",
            {"project", "campaign", "workflow", "scientific", "execution", "example", "remote"},
        ),
    ],
)
def test_canonical_group_help_lists_direct_children_only(
    group: str, children: set[str], capsys,
) -> None:
    with pytest.raises(SystemExit) as result:
        cli.main([group, "--help"])

    assert result.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    for child in children:
        assert child in captured.out


@pytest.mark.parametrize("legacy", ["fdf", "input", "pseudo"])
def test_legacy_family_help_emits_one_migration_notice(
    legacy: str, capsys,
) -> None:
    with pytest.raises(SystemExit) as result:
        cli.main([legacy, "--help"])

    assert result.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert captured.err.count("DEPRECATED:") == 1
    assert "Use:" in captured.err


@pytest.mark.parametrize(
    ("canonical", "legacy"),
    [
        (["setup", "env", "--json"], ["env", "--json"]),
        (["setup", "config", "--json"], ["config", "--json"]),
        (["setup", "profile", "list", "--json"], ["profile", "list", "--json"]),
        (["inspect", "plan", "calc.fdf", "--json"], ["plan", "calc.fdf", "--json"]),
        (["inspect", "fdf", "calc.fdf", "--json"], ["fdf", "inspect", "calc.fdf", "--json"]),
        (["inspect", "input", "calc.fdf", "--json"], ["input", "validate", "calc.fdf", "--json"]),
        (["inspect", "rules", "--json"], ["input", "rules", "--json"]),
        (["inspect", "pseudo", "manifest.json", "--json"], ["pseudo", "verify", "manifest.json", "--json"]),
        (["advanced", "project", "inspect", "project", "--json"], ["project", "inspect", "project", "--json"]),
        (["advanced", "campaign", "validate", "campaign.yaml", "--json"], ["campaign", "validate", "campaign.yaml", "--json"]),
        (["advanced", "campaign", "render", "campaign.yaml", "--json"], ["render", "campaign.yaml", "--json"]),
        (["advanced", "workflow", "recipes", "--json"], ["workflow", "recipes", "--json"]),
        (
            ["advanced", "scientific", "decide", "report.json", "--approval-id", "a", "--decision", "REJECT", "--actor", "r", "--decided-at", "2026-09-04T00:00:00Z", "--output", "decision.json", "--json"],
            ["scientific", "decide", "report.json", "--approval-id", "a", "--decision", "REJECT", "--actor", "r", "--decided-at", "2026-09-04T00:00:00Z", "--output", "decision.json", "--json"],
        ),
        (["advanced", "remote", "m4-package", "--profile", "profile.json", "--output", "bundle", "--json"], ["remote", "m4-package", "--profile", "profile.json", "--output", "bundle", "--json"]),
        (["advanced", "execution", "inspect", "package", "--json"], ["run", "inspect", "package", "--json"]),
        (["advanced", "example", "inspect", "generic/minimal_siesta_smoke", "--json"], ["examples", "inspect", "generic/minimal_siesta_smoke", "--json"]),
    ],
)
def test_canonical_and_legacy_routes_parse_to_identical_handler_inputs(
    canonical: list[str], legacy: list[str], monkeypatch, capsys,
) -> None:
    _install_recording_dispatch(monkeypatch)

    assert cli.main(canonical) == 0
    canonical_capture = capsys.readouterr()
    assert canonical_capture.err == ""
    canonical_payload = json.loads(canonical_capture.out)

    assert cli.main(legacy) == 0
    legacy_capture = capsys.readouterr()
    assert legacy_capture.err.count("DEPRECATED:") == 1
    assert "Use:" in legacy_capture.err
    assert json.loads(legacy_capture.out) == canonical_payload


@pytest.mark.parametrize(
    ("canonical", "legacy"),
    [
        (["setup", "env", "--launcher", "direct", "--siesta", sys.executable, "--json"], ["env", "--launcher", "direct", "--siesta", sys.executable, "--json"]),
        (["setup", "profile", "list", "--json"], ["profile", "list", "--json"]),
        (["inspect", "rules", "--json"], ["input", "rules", "--json"]),
        (["inspect", "fdf", "examples/generic/minimal_siesta_smoke/systems/xy_cell.fdf", "--json"], ["fdf", "inspect", "examples/generic/minimal_siesta_smoke/systems/xy_cell.fdf", "--json"]),
        (["advanced", "example", "inspect", "generic/minimal_siesta_smoke", "--json"], ["examples", "inspect", "generic/minimal_siesta_smoke", "--json"]),
    ],
)
def test_representative_real_json_results_are_exactly_equivalent(
    canonical: list[str], legacy: list[str], capsys,
) -> None:
    canonical_code = cli.main(canonical)
    canonical_capture = capsys.readouterr()
    legacy_code = cli.main(legacy)
    legacy_capture = capsys.readouterr()

    assert legacy_code == canonical_code
    assert json.loads(legacy_capture.out) == json.loads(canonical_capture.out)
    assert canonical_capture.err == ""
    assert legacy_capture.err.count("DEPRECATED:") == 1


def test_representative_human_stdout_is_equivalent_except_warning(capsys) -> None:
    assert cli.main(["setup", "profile", "list"]) == 0
    canonical = capsys.readouterr()
    assert cli.main(["profile", "list"]) == 0
    legacy = capsys.readouterr()

    assert legacy.out == canonical.out
    assert canonical.err == ""
    assert legacy.err.count("DEPRECATED:") == 1


def test_frozen_legacy_routes_keep_their_handlers_and_warn_once(
    monkeypatch, capsys,
) -> None:
    _install_recording_dispatch(monkeypatch)

    assert cli.main(["validate", "calc.fdf", "--json"]) == 0
    validate_capture = capsys.readouterr()
    assert json.loads(validate_capture.out)["domain"] == "validate"
    assert validate_capture.err.count("DEPRECATED:") == 1
    assert "qraft check" in validate_capture.err

    assert cli.main(["environment", "check", "--json"]) == 0
    environment_capture = capsys.readouterr()
    assert json.loads(environment_capture.out)["domain"] == "environment"
    assert environment_capture.err.count("DEPRECATED:") == 1
    assert "qraft setup env" in environment_capture.err

    specs = {command.id: command for command in cli.command_surface()}
    assert specs["qraft.legacy.validate"].frozen_handler is True
    assert specs["qraft.legacy.environment"].frozen_handler is True


def test_run_target_action_and_collision_routing_is_fail_closed(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    _install_recording_dispatch(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["run", "calc.fdf", "--json"]) == 0
    target = capsys.readouterr()
    assert json.loads(target.out)["domain"] == "_fdf-run"
    assert target.err == ""

    assert cli.main(["run", "inspect", "package", "--json"]) == 0
    action = capsys.readouterr()
    assert json.loads(action.out)["domain"] == "run"
    assert action.err.count("DEPRECATED:") == 1

    (tmp_path / "inspect").write_text("target", encoding="utf-8")
    assert cli.main(["run", "inspect", "--json"]) == 2
    collision = capsys.readouterr()
    assert json.loads(collision.out)["error"]["code"] == "AMBIGUOUS_RUN_TARGET"
    assert collision.err == ""

    assert cli.main(["--json", "run", "--", "inspect"]) == 0
    explicit_target = capsys.readouterr()
    assert json.loads(explicit_target.out)["domain"] == "_fdf-run"
    assert explicit_target.err == ""


def test_command_spec_owns_unique_aliases_and_canonical_hierarchy() -> None:
    commands = cli.command_surface()
    aliases = [alias.path for command in commands for alias in command.aliases]

    assert len(aliases) == len(set(aliases))
    assert len({command.path for command in commands}) == len(commands)
    cli.validate_command_surface(commands)
    for command in commands:
        for alias in command.aliases:
            resolved = cli.resolve_command_route(list(alias.path))
            assert resolved is not None
            assert resolved.command.id == command.id
            assert resolved.is_legacy is True


def test_internal_fdf_adapter_remains_hidden_and_non_deprecated(capsys) -> None:
    parser = cli.build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert "_fdf-run" in subparsers.choices
    assert "_fdf-run" not in {action.dest for action in subparsers._choices_actions}

    with pytest.raises(SystemExit) as result:
        cli.main(["_fdf-run", "--help"])
    assert result.value.code == 0
    assert "DEPRECATED:" not in capsys.readouterr().err
