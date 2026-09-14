"""Internal immutable values shared by workflow compiler components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..contracts import (
    CompiledWorkflow,
    DecisionStatus,
    ValidationReport,
    WorkflowOutputPort,
    WorkflowTaskKind,
)


@dataclass(frozen=True)
class WorkflowCompilation:
    report: ValidationReport
    compiled: CompiledWorkflow | None

    @property
    def valid(self) -> bool:
        return (
            self.compiled is not None
            and self.report.status is DecisionStatus.PASS
        )

    def lock_dict(self) -> dict[str, Any]:
        if not self.valid or self.compiled is None:
            raise ValueError("cannot create a workflow lock from invalid input")
        return self.compiled.envelope().to_dict()


@dataclass(frozen=True)
class InputDraft:
    name: str
    destination: str | None
    media_type: str | None
    source_path: str | None
    source_task: str | None
    source_output: str | None
    declared_sha256: str | None
    location: str


@dataclass(frozen=True)
class TaskDraft:
    task_id: str
    kind: WorkflowTaskKind
    capability: str
    dependencies: tuple[str, ...]
    inputs: tuple[InputDraft, ...]
    outputs: tuple[WorkflowOutputPort, ...]
    resources: Mapping[str, Any]
    settings: Mapping[str, Any]


@dataclass(frozen=True)
class ParsedWorkflow:
    source: Path
    definition_sha256: str
    workflow_id: str
    project_id: str
    description: str
    metadata: Mapping[str, Any]
    tasks: tuple[TaskDraft, ...]
