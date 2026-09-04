"""Installed CLI discovery remains aligned across help, REPL, and guide."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import re

import pytest

from qraft.cli import (
    build_parser,
    main,
    public_command_help,
    public_command_metavar,
    public_command_surface,
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
        assert command.classification in {"PUBLIC", "ADVANCED_PUBLIC"}
        assert f"    {command.name}" in text
        assert command.description in compact_help
    assert "_fdf-run" not in text
    assert "    environment" not in text


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
