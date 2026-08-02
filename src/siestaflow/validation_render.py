"""Human-readable rendering for Core Contracts validation reports."""

from __future__ import annotations

from .contracts import ValidationReport


def render_validation_report(
    report: ValidationReport,
    *,
    title: str = "VALIDATION",
) -> str:
    lines = [
        f"{title}: {report.status.value}",
        f"SUBJECT: {report.subject.subject_id}",
        f"PRODUCER: {report.produced_by}",
    ]
    if not report.findings:
        lines.append("No findings.")
    for finding in report.findings:
        location = f" @ {finding.location}" if finding.location else ""
        lines.append(
            f"[{finding.status.value}] {finding.code}"
            f" [{finding.scope.value}]{location}"
        )
        lines.append(f"  {finding.message}")
        for evidence in finding.evidence:
            lines.append(f"  Evidence: {evidence}")
        if finding.hint:
            lines.append(f"  Suggested action: {finding.hint}")
    return "\n".join(lines)
