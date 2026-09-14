"""Generic command capability for translated non-engine legacy tasks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..core import TechnicalValidation


@dataclass(frozen=True)
class CommandArtifact:
    path: str
    sha256: str


class GenericCommandCapability:
    """Execute a declared argv without interpreting its scientific meaning."""

    def select_primary_input(self, **kwargs: Any) -> str:
        inputs = dict(kwargs.get("inputs", {}))
        selected = str(dict(kwargs.get("settings", {})).get("primary_input", ""))
        if not selected or selected not in inputs:
            raise ValueError("generic command requires an explicit primary_input")
        return selected

    def inspect_input(self, path: Path) -> Path:
        resolved = Path(path)
        if not resolved.is_file():
            raise ValueError(f"command input is missing: {resolved}")
        return resolved

    def validate_input(self, inspected: Path, **kwargs: Any) -> TechnicalValidation:
        return TechnicalValidation(
            "PASS", "COMMAND_INPUT_PRESENT", (f"input present: {inspected.name}",)
        )

    def prepare_task(self, inspected: Path, workspace: Path, **kwargs: Any) -> Path:
        try:
            inspected.resolve().relative_to(workspace.resolve())
        except ValueError as exc:
            raise ValueError("prepared command input escapes attempt workspace") from exc
        return inspected

    def build_command(self, input_path: Path, **kwargs: Any) -> tuple[str, ...]:
        raw = dict(kwargs.get("settings", {})).get("command", ())
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError("generic command capability requires declared argv")
        command = tuple(str(item) for item in raw)
        if any(not item for item in command):
            raise ValueError("generic command argv contains an empty value")
        return command

    def parse_output(self, lines: Iterable[str], **kwargs: Any) -> Mapping[str, Any]:
        outcome = kwargs.get("outcome")
        return {
            "stdout": "".join(lines),
            "stderr": str(kwargs.get("stderr", "")),
            "exit_code": getattr(outcome, "exit_code", None),
        }

    def discover_artifacts(self, workspace: Path, **kwargs: Any):
        declared = dict(kwargs.get("settings", {})).get("declared_outputs", ())
        artifacts: list[CommandArtifact] = []
        for relative in declared:
            path = workspace / str(relative)
            if path.is_file():
                artifacts.append(
                    CommandArtifact(
                        str(relative), hashlib.sha256(path.read_bytes()).hexdigest()
                    )
                )
        return tuple(artifacts)

    def classify_result(
        self, parsed: Mapping[str, Any], **kwargs: Any
    ) -> TechnicalValidation:
        passed = parsed.get("exit_code") == 0
        return TechnicalValidation(
            "PASS" if passed else "FAIL",
            "COMMAND_COMPLETED" if passed else "COMMAND_FAILED",
            ("declared command exited successfully",)
            if passed
            else (f"declared command exit code {parsed.get('exit_code')}",),
            {"exit_code": parsed.get("exit_code")},
        )
