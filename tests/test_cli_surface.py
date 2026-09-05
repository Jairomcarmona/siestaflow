"""Installed CLI discovery remains aligned across help, REPL, and guide."""

from __future__ import annotations

import argparse
from dataclasses import replace
from io import StringIO
from pathlib import Path
import re

import pytest

from qraft.cli import (
    CommandAlias,
    CommandClassification,
    CommandVisibility,
    build_parser,
    command_surface,
    main,
    parser_visible_command_surface,
    public_command_help,
    public_command_metavar,
    public_command_surface,
    shared_command_options,
    validate_command_option_references,
    validate_command_surface,
)
from qraft.repl import QraftShell


REPO = Path(__file__).resolve().parents[1]


def test_public_surface_has_one_visible_help_authority() -> None:
    parser = build_parser()
    text = parser.format_help()

    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert subparsers.metavar == public_command_metavar()
    assert "{init,env,config,profile,validate,plan,render,run,status,resume}" not in text
    compact_help = " ".join(text.split())
    for command in public_command_surface():
        assert command.classification in {
            "CORE", "GROUPED_PUBLIC", "ADVANCED",
        }
        assert f"    {command.name}" in text
        assert command.description in compact_help
    assert "_fdf-run" not in text
    assert "    environment" not in text


def test_phase3_public_surface_introduces_canonical_groups() -> None:
    assert tuple(command.name for command in public_command_surface()) == (
        "init", "run", "status", "resume", "results", "examples",
        "setup", "inspect", "advanced",
    )
    assert {
        command.classification for command in public_command_surface()
    } == {
        CommandClassification.CORE,
        CommandClassification.GROUPED_PUBLIC,
        CommandClassification.ADVANCED,
    }


def test_command_specification_has_unique_current_ids_and_paths() -> None:
    commands = command_surface()
    assert len({command.id for command in commands}) == len(commands)
    assert len({command.path for command in commands}) == len(commands)
    validate_command_option_references(commands, shared_command_options())


@pytest.mark.parametrize(
    ("commands", "message"),
    [
        (
            lambda specs: (
                specs[0],
                replace(specs[1], id="qraft.duplicate-path", path=specs[0].path),
            ),
            "duplicate canonical command path",
        ),
        (
            lambda specs: (specs[0], replace(specs[1], id=specs[0].id)),
            "duplicate command id",
        ),
        (
            lambda specs: (
                replace(specs[0], aliases=(CommandAlias(specs[1].path),)),
                specs[1],
            ),
            "alias collides with canonical command path",
        ),
        (
            lambda specs: (
                replace(specs[0], aliases=(CommandAlias(("legacy",)),)),
                replace(specs[1], aliases=(CommandAlias(("legacy",)),)),
            ),
            "ambiguous alias ownership",
        ),
        (
            lambda specs: (
                replace(specs[-1], visibility=CommandVisibility.PRIMARY),
            ),
            "internal command must be hidden",
        ),
        (
            lambda specs: (replace(specs[0], parent_id="qraft.unknown"),),
            "references unknown parent",
        ),
    ],
)
def test_command_specification_rejects_programmer_collisions(
    commands, message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_command_surface(commands(command_surface()))


def test_hidden_and_internal_commands_remain_dispatchable_but_undiscoverable() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    visible_names = {action.dest for action in subparsers._choices_actions}

    assert "environment" not in visible_names
    assert "_fdf-run" not in visible_names
    assert {"environment", "_fdf-run"} <= set(subparsers.choices)
    assert all(
        command.visibility is CommandVisibility.HIDDEN
        for command in command_surface()
        if command.classification in {
                CommandClassification.LEGACY_ALIAS,
            CommandClassification.INTERNAL,
        }
    )


def test_every_parser_command_has_one_specification_record() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    expected_roots = {
        command.path[0]
        for command in command_surface()
        if len(command.path) == 1
    } | {
        command.dispatch_path[0]
        for command in command_surface()
        if command.dispatch_path is not None
    }
    assert set(subparsers.choices) == expected_roots
    assert {action.dest for action in subparsers._choices_actions} == {
        command.name for command in parser_visible_command_surface()
    }


def test_parser_help_and_repl_discovery_consume_command_specification() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    action_help = {
        action.dest: action.help for action in subparsers._choices_actions
    }

    for command in parser_visible_command_surface():
        assert action_help[command.name] == command.summary
    assert public_command_help() == tuple(
        (command.name, command.summary) for command in public_command_surface()
    )


@pytest.mark.parametrize("command", [item.name for item in public_command_surface()])
def test_every_public_top_level_command_has_help(command: str) -> None:
    with pytest.raises(SystemExit) as result:
        main([command, "--help"])
    assert result.value.code == 0


def test_repl_cli_discovery_uses_the_public_surface_authority() -> None:
    output = StringIO()
    shell = QraftShell(stdout=output)
    assert shell.onecmd("cli") is False
    text = output.getvalue()

    for name, description in public_command_help():
        assert name in text
        assert description in text
    assert "_fdf-run" not in text


def test_user_guide_documents_every_public_top_level_command() -> None:
    text = (REPO / "docs/user-guide/13-cli-reference.md").read_text(encoding="utf-8")
    for command in public_command_surface():
        assert re.search(rf"`{re.escape(command.name)}(?:[ `])", text)
    assert "`_fdf-run`" not in text
