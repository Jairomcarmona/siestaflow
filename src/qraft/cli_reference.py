"""Deterministic Markdown rendering of the canonical CLI presentation model."""

from __future__ import annotations

from .cli import CommandClassification, CommandVisibility, command_surface


def render_cli_reference() -> str:
    """Render the committed CLI reference without filesystem or clock inputs."""
    commands = tuple(command_surface())
    public = tuple(item for item in commands if item.visibility is not CommandVisibility.HIDDEN)
    lines = [
        "# QRAFT CLI reference", "",
        "<!-- Generated from `src/qraft/cli.py`; do not edit manually. -->", "",
        "The core workflow is `init`, `check`, `run`, `status`, `results`, and `examples`. "
        "Use `qraft --help` for task-oriented discovery.", "",
        "## Core commands", "",
    ]
    for command in public:
        if command.classification is not CommandClassification.CORE:
            continue
        _append_command(lines, command)
    for classification, heading in (
        (CommandClassification.GROUPED_PUBLIC, "## Setup and inspection"),
        (CommandClassification.ADVANCED, "## Advanced commands"),
    ):
        lines.extend((heading, ""))
        for command in public:
            if command.classification is classification:
                _append_command(lines, command)
    lines.extend(("## Compatibility", ""))
    for command in commands:
        if command.classification is CommandClassification.LEGACY_ALIAS:
            replacement = " ".join(command.canonical_replacement or ())
            lines.append(f"- `qraft {' '.join(command.path)}` remains available; canonical replacement: `qraft {replacement}`.")
    lines.append("")
    return "\n".join(lines)


def _append_command(lines: list[str], command) -> None:
    path = " ".join(command.path)
    lines.extend((f"### `qraft {path}`", "", command.summary, ""))
    if command.usage:
        lines.extend(("**Usage:**", "", f"`{command.usage}`", ""))
    lines.extend(("**Example:**", "", f"`qraft {path} --help`", ""))
    if command.aliases:
        aliases = ", ".join(f"`qraft {' '.join(alias.path)}`" for alias in command.aliases)
        lines.extend((f"**Compatibility aliases:** {aliases}", ""))
