"""SIESTA adapter and deterministic synthetic launcher."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from ...filesystem import FileSystem
from ...hpc import ProcessLauncher
from ...models import AllocationContext, FailureType, TaskAttempt, TaskResult, TaskSpec
from ..base import EngineAdapter
from .artifacts import discover_siesta_artifacts
from .command import EngineProfile, SiestaCommandBuilder
from .fdf_parser import FDFParser
from .input_validator import SiestaInputValidator
from .models import OutputClassification, PreparedInput
from .output_parser import SiestaOutputParser


class SiestaEngineAdapter(EngineAdapter):
    def __init__(self) -> None:
        self.fdf = FDFParser()
        self.validator = SiestaInputValidator()
        self.outputs = SiestaOutputParser()

    def inspect_input(self, path: Path):
        return self.fdf.parse_path(path)

    def validate_input(self, inspected: Any, **kwargs: Any):
        return self.validator.validate(inspected, **kwargs)

    def prepare_task(self, inspected: Any, workspace: Path, **kwargs: Any) -> PreparedInput:
        fs: FileSystem = kwargs["filesystem"]
        validation = self.validate_input(inspected, **kwargs.get("validation_options", {}))
        destination = workspace / Path(inspected.source).name
        fs.write_text(destination, inspected.render())
        return PreparedInput(Path(inspected.source), destination, inspected.original_sha256, validation)

    def build_command(self, input_path: Path, **kwargs: Any) -> tuple[str, ...]:
        return SiestaCommandBuilder().build(input_path, kwargs.get("profile", EngineProfile()))

    def parse_output(self, lines: Iterable[str], **kwargs: Any):
        return self.outputs.parse(lines, synthetic=bool(kwargs.get("synthetic", False)))

    def discover_artifacts(self, workspace: Path, **kwargs: Any):
        return discover_siesta_artifacts(workspace, task_id=kwargs["task_id"], attempt_id=kwargs["attempt_id"])

    def classify_result(self, parsed: Any, **kwargs: Any):
        return self.outputs.gate(parsed)


class SyntheticSiestaLauncher(ProcessLauncher):
    """Returns parsed synthetic fixtures and never launches a process."""

    def __init__(self, fixtures: dict[str, str] | None = None) -> None:
        self.fixtures = dict(fixtures or {})
        self.launches: list[tuple[str, str, str]] = []
        self.parser = SiestaOutputParser()

    @staticmethod
    def normal_output(task_id: str) -> str:
        return (
            "Siesta Version : 5.4.2-SYNTHETIC\nSiesta started\nNumber of atoms: 54\n"
            "Number of species: 2\nSCF cycle 1\nSCF converged\n"
            f"siesta: Final energy -100.000000 # synthetic {task_id}\n"
            "Elapsed time: 1.0 s\nJob completed\n"
        )

    def launch(self, task: TaskSpec, attempt: TaskAttempt, allocation: AllocationContext) -> TaskResult:
        self.launches.append((allocation.allocation_id, task.task_id, attempt.attempt_id))
        text = self.fixtures.get(task.task_id, self.normal_output(task.task_id))
        parsed = self.parser.parse(text.splitlines(keepends=True), synthetic=True)
        gate = self.parser.gate(parsed)
        failure_map = {
            OutputClassification.COMPLETED: FailureType.SUCCESS,
            OutputClassification.TRUNCATED_OUTPUT: FailureType.TRUNCATED_OUTPUT,
            OutputClassification.UNKNOWN_WARNING: FailureType.UNKNOWN_WARNING,
            OutputClassification.TIMEOUT: FailureType.TIMEOUT,
            OutputClassification.CANCELLED: FailureType.CANCELLED,
            OutputClassification.INPUT_ERROR: FailureType.INPUT_ERROR,
            OutputClassification.NODE_FAILURE: FailureType.NODE_FAILURE,
        }
        failure = failure_map.get(parsed.classification, FailureType.PROCESS_FAILURE)
        warnings = tuple(parsed.warnings) if gate.status.value == "REVIEW" else ()
        return TaskResult(
            task.task_id, attempt.attempt_id, failure,
            0 if failure in {FailureType.SUCCESS, FailureType.UNKNOWN_WARNING, FailureType.TRUNCATED_OUTPUT} else None,
            text, "", float(task.estimated_runtime_seconds or 1.0), warnings,
        )
