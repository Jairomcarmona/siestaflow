"""Write the deterministic CLI reference used by documentation drift tests."""

from pathlib import Path

from qraft.cli_reference import render_cli_reference


ROOT = Path(__file__).resolve().parents[1]
(ROOT / "docs" / "user" / "CLI_REFERENCE.md").write_text(
    render_cli_reference(), encoding="utf-8", newline="\n"
)
