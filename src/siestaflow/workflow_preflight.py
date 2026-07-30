"""Read-only engine-aware validation of external inputs in a workflow DAG."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath

from .contracts import (
    ValidationReport,
    ValidationSubject,
    contract_sha256,
)
from .engines.siesta.fdf_parser import FDFParser
from .engines.siesta.input_validator import SiestaInputValidator
from .engines.siesta.pseudopotentials import (
    PseudopotentialManifest,
    PseudopotentialVerifier,
)
from .engines.siesta.validation_profile import SiestaValidationProfile
from .siesta_validation import SiestaContextualValidator
from .workflows import WorkflowCompiler


_SIESTA_FDF_MEDIA_TYPES = {
    "text/x-siesta-fdf",
    "application/x-siesta-fdf",
}


class WorkflowPreflightValidator:
    """Validate every hash-resolved external SIESTA FDF in a compiled DAG."""

    def __init__(
        self,
        *,
        compiler: WorkflowCompiler | None = None,
        siesta_validator: SiestaContextualValidator | None = None,
    ) -> None:
        self.compiler = compiler or WorkflowCompiler()
        self.siesta_validator = (
            siesta_validator or SiestaContextualValidator()
        )

    def validate(
        self,
        definition: Path,
        *,
        profile: SiestaValidationProfile | None = None,
        pseudopotential_manifest: PseudopotentialManifest | None = None,
        require_pseudos: bool = False,
    ) -> ValidationReport:
        compilation = self.compiler.compile(definition)
        if not compilation.valid or compilation.compiled is None:
            return compilation.report
        compiled = compilation.compiled
        findings = []
        reports: list[ValidationReport] = []
        root = definition.resolve().parent
        for artifact in compiled.external_artifacts:
            if artifact.media_type.casefold() not in _SIESTA_FDF_MEDIA_TYPES:
                continue
            path = (
                root
                / Path(*PurePosixPath(artifact.relative_path).parts)
            ).resolve()
            document = FDFParser().parse_path(path)
            pseudo_result = None
            if pseudopotential_manifest is not None:
                structural = SiestaInputValidator().validate(document)
                pseudo_result = PseudopotentialVerifier().verify(
                    pseudopotential_manifest,
                    structural.species,
                )
            report = self.siesta_validator.validate(
                document,
                pseudo_result=pseudo_result,
                require_pseudos=require_pseudos,
                profile=profile,
                subject_id=artifact.artifact_id,
            )
            reports.append(report)
            for finding in report.findings:
                location = (
                    f"{artifact.relative_path}:{finding.location}"
                    if finding.location
                    else artifact.relative_path
                )
                findings.append(
                    replace(
                        finding,
                        subject_id=compiled.workflow_id,
                        location=location,
                        data={
                            **dict(finding.data),
                            "artifact_id": artifact.artifact_id,
                            "artifact_sha256": artifact.sha256,
                        },
                    )
                )
        ruleset = contract_sha256(
            {
                "workflow_ruleset": compilation.report.ruleset_sha256,
                "input_rulesets": sorted(
                    {item.ruleset_sha256 for item in reports}
                ),
            }
        )
        subject = ValidationSubject(
            subject_id=compiled.workflow_id,
            subject_type="siestaflow.workflow-preflight",
            source=str(definition.resolve()),
            attributes={
                "definition_sha256": compiled.definition_sha256,
                "task_count": len(compiled.tasks),
                "external_artifact_count": len(
                    compiled.external_artifacts
                ),
                "siesta_fdf_count": len(reports),
                "profile_id": profile.profile_id if profile else None,
            },
        )
        return ValidationReport.build(
            report_id=f"{compiled.workflow_id}:preflight",
            subject=subject,
            findings=tuple(findings),
            ruleset_sha256=ruleset,
            produced_by="siestaflow.workflow-preflight",
            metadata={
                "workflow_valid": True,
                "input_reports": len(reports),
                "execution_authorized": False,
                "filesystem_changes": 0,
            },
        )
