"""Stable workflow-compiler diagnostics and validation reports."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..contracts import (
    CompiledWorkflow,
    DecisionStatus,
    EvidenceClass,
    FindingScope,
    ValidationFinding,
    ValidationReport,
    ValidationSubject,
    contract_sha256,
)
from .models import WorkflowCompilation


RULESET = (
    "siestaflow.workflow.schema@1.0",
    "siestaflow.workflow.graph@1.0",
    "siestaflow.workflow.artifacts@1.0",
    "siestaflow.workflow.resources@1.0",
)


def finding(
    code: str,
    message: str,
    *,
    location: str,
    hint: str | None = None,
    scope: FindingScope = FindingScope.STRUCTURE,
) -> ValidationFinding:
    return ValidationFinding(
        rule_id="siestaflow.workflow.compiler",
        code=code,
        status=DecisionStatus.BLOCKED,
        message=message,
        evidence_class=EvidenceClass.MATHEMATICAL_CONSISTENCY,
        scope=scope,
        subject_id="workflow",
        location=location,
        hint=hint,
    )


def compilation_result(
    source: Path,
    workflow_id: str | None,
    findings: list[ValidationFinding],
    compiled: CompiledWorkflow | None = None,
) -> WorkflowCompilation:
    subject = ValidationSubject(
        subject_id=workflow_id or source.name,
        subject_type="siestaflow.workflow-definition",
        source=str(source),
    )
    report = ValidationReport.build(
        report_id=f"workflow-validation:{workflow_id or source.name}",
        subject=subject,
        findings=tuple(
            replace(item, subject_id=subject.subject_id) for item in findings
        ),
        ruleset_sha256=contract_sha256({"rules": RULESET}),
        produced_by="siestaflow.workflow-compiler",
        metadata={"schema_version": "1.0"},
    )
    return WorkflowCompilation(report, compiled)
