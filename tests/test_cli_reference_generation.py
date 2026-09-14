from pathlib import Path

from qraft.cli_reference import render_cli_reference


def test_committed_cli_reference_matches_the_command_specification() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "user" / "CLI_REFERENCE.md").read_text(encoding="utf-8") == render_cli_reference()
