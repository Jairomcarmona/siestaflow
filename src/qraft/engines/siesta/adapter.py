"""SIESTA adapter and deterministic synthetic launcher."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from ...filesystem import FileSystem
from ...core import TechnicalValidation
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

    def select_primary_input(self, **kwargs: Any) -> str:
        """Select the FDF by explicit metadata, never by input-name ordering."""

        inputs = dict(kwargs.get("inputs", {}))
        bindings = dict(kwargs.get("bindings", {}))
        settings = dict(kwargs.get("settings", {}))
        declared = settings.get("primary_input")
        if declared is not None:
            selected = str(declared)
            if selected not in inputs:
                raise ValueError(f"unknown SIESTA primary input: {selected}")
            return selected
        candidates = [
            name
            for name, binding in bindings.items()
            if str(getattr(binding, "media_type", "")).casefold()
            == "application/x-siesta-fdf"
        ]
        if len(candidates) != 1:
            raise ValueError(
                "SIESTA multi-input execution requires one explicit FDF input"
            )
        return candidates[0]

    def mutable_input_names(self, **kwargs: Any) -> tuple[str, ...]:
        """Declare transferred density-matrix inputs as mutable engine inputs."""

        bindings = dict(kwargs.get("bindings", {}))
        return tuple(
            sorted(
                name
                for name, binding in bindings.items()
                if getattr(binding, "source_task_id", None) is not None
                and Path(str(getattr(binding, "destination", ""))).suffix.casefold()
                == ".dm"
            )
        )

    def validate_consumed_inputs(self, parsed: Any, **kwargs: Any):
        """Require parser evidence that a declared restart input was consumed."""

        classified = kwargs["classified"]
        mutable_inputs = tuple(kwargs.get("mutable_inputs", ()))
        if not mutable_inputs or str(getattr(classified, "status", "")).upper() != "PASS":
            return classified
        if bool(getattr(parsed, "dm_restart_succeeded", False)):
            return classified
        attempted = bool(getattr(parsed, "dm_restart_attempted", False))
        reason = (
            "SIESTA attempted restart input consumption without success"
            if attempted
            else "SIESTA output did not confirm restart input consumption"
        )
        return TechnicalValidation(
            status="FAIL",
            classification="RESTART_INPUT_NOT_CONSUMED",
            reasons=(reason,),
            parser_summary=asdict(parsed),
        )

    def validate_input(self, inspected: Any, **kwargs: Any):
        options = dict(kwargs.get("validation_options", {}))
        for name in ("pseudo_result", "require_pseudos"):
            if name in kwargs:
                options[name] = kwargs[name]
        return self.validator.validate(inspected, **options)

    def prepare_task(self, inspected: Any, workspace: Path, **kwargs: Any) -> PreparedInput:
        fs: FileSystem = kwargs["filesystem"]
        validation = self.validate_input(inspected, **kwargs.get("validation_options", {}))
        destination = workspace / Path(inspected.source).name
        if not destination.is_file():
            fs.write_text(destination, inspected.render())
        return PreparedInput(Path(inspected.source), destination, inspected.original_sha256, validation)

    def build_command(self, input_path: Path, **kwargs: Any) -> tuple[str, ...]:
        profile = kwargs.get("profile")
        if profile is None:
            execution_spec = kwargs.get("execution_spec")
            profile = EngineProfile(
                executable=(
                    str(execution_spec.executable)
                    if execution_spec is not None
                    else None
                )
            )
        return SiestaCommandBuilder().build(input_path, profile)

    def parse_output(self, lines: Iterable[str], **kwargs: Any):
        settings = kwargs.get("settings", {})
        return self.outputs.parse(
            lines,
            synthetic=bool(settings.get("synthetic", kwargs.get("synthetic", False))),
        )

    def discover_artifacts(self, workspace: Path, **kwargs: Any):
        return discover_siesta_artifacts(workspace, task_id=kwargs["task_id"], attempt_id=kwargs["attempt_id"])

    def classify_result(self, parsed: Any, **kwargs: Any):
        gate = self.outputs.gate(parsed)
        return TechnicalValidation(
            status=gate.status.value,
            classification=parsed.classification.value,
            reasons=(gate.reason, *gate.evidence),
            parser_summary=asdict(parsed),
        )


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
