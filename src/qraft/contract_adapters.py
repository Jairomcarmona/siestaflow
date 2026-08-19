"""Compatibility adapters from current runtime models to core contracts.

This module is intentionally outside :mod:`qraft.contracts`: dependency
arrows point from integrations toward the engine-neutral contract kernel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import (
    ArtifactReference,
    ArtifactRole,
    EvidenceClass,
    ExecutionEvidence,
    ExecutionRequest,
    FailureType,
    FindingScope,
    ValidationFinding,
    ValidationReport,
    ValidationSubject,
    contract_sha256,
)
from .engines.siesta.models import (
    ArtifactDescriptor as SiestaArtifactDescriptor,
    InputValidationResult,
)
from .execution.srun_launcher import StepLaunchSpec, StepOutcome


_ARTIFACT_ROLE_BY_TYPE = {
    "XV": ArtifactRole.GEOMETRY,
    "DM": ArtifactRole.RESTART,
    "RHO": ArtifactRole.DENSITY,
    "PSML": ArtifactRole.PSEUDOPOTENTIAL,
    "PSF": ArtifactRole.PSEUDOPOTENTIAL,
}

_INPUT_HINTS = {
    "UNKNOWN_LABEL": (
        "Verify the spelling against the SIESTA manual for the selected "
        "version; unknown labels are preserved but not trusted."
    ),
    "UNRESOLVED_INCLUDE": (
        "Resolve includes into an authorized package root before execution."
    ),
    "INVALID_SPECIES_ROW": "Use: species-index atomic-number chemical-label.",
    "INVALID_SPECIES_INDEX": "Use a positive integer species index.",
    "SPECIES_COUNT_MISMATCH": (
        "Make NumberOfSpecies equal the ChemicalSpeciesLabel row count."
    ),
    "ATOM_COUNT_MISMATCH": (
        "Make NumberOfAtoms equal the coordinate row count."
    ),
    "INVALID_COORDINATE_ROW": (
        "Provide three coordinates followed by a declared species index."
    ),
    "INVALID_COORDINATE_SPECIES": "Use an integer species index in each coordinate row.",
    "UNKNOWN_SPECIES_INDEX": (
        "Reference only indices declared in ChemicalSpeciesLabel."
    ),
    "MISSING_REQUIRED_BLOCK": "Add the named block before preparing execution.",
    "UNDECLARED_GOVERNED_VALUE": (
        "Declare the value explicitly so no engine default is silently assumed."
    ),
    "INVALID_INTEGER": "Replace the value with an integer accepted by SIESTA.",
    "PSEUDOPOTENTIAL_AUDIT": (
        "Resolve every manifest finding and hash mismatch before execution."
    ),
    "PSEUDOPOTENTIAL_MANIFEST_REQUIRED": (
        "Pass a verified pseudopotential manifest covering every species."
    ),
    "DUPLICATE_BLOCK": (
        "Keep one authoritative block or document why repetition is valid."
    ),
}


def _input_scope(code: str) -> FindingScope:
    if "PSEUDOPOTENTIAL" in code:
        return FindingScope.PSEUDOPOTENTIAL
    if code in {"UNKNOWN_LABEL", "UNRESOLVED_INCLUDE"}:
        return FindingScope.SYNTAX
    if code in {"INVALID_INTEGER", "UNDECLARED_GOVERNED_VALUE"}:
        return FindingScope.NUMERICAL
    return FindingScope.STRUCTURE


def _input_location(evidence: tuple[str, ...]) -> str | None:
    return next(
        (item for item in evidence if item.startswith("line:")),
        None,
    )


def validation_report_from_siesta(
    result: InputValidationResult,
    *,
    subject_id: str,
    source: str,
    producer: str = "siestaflow.siesta-input-adapter",
) -> ValidationReport:
    """Map the existing SIESTA validation result without losing its decision."""

    subject = ValidationSubject(
        subject_id=subject_id,
        subject_type="siesta.fdf",
        engine="siesta",
        source=source,
        attributes={
            "atoms": result.atoms,
            "species": result.species,
            "system_id": result.system_id,
        },
    )
    findings = tuple(
        ValidationFinding(
            rule_id="siestaflow.siesta.legacy-input",
            code=item.code,
            status=item.status,
            message=item.message,
            evidence_class=(
                EvidenceClass.PSEUDOPOTENTIAL_METADATA
                if "PSEUDOPOTENTIAL" in item.code
                else EvidenceClass.ENGINE_MANUAL
            ),
            scope=_input_scope(item.code),
            subject_id=subject_id,
            location=_input_location(item.evidence),
            hint=_INPUT_HINTS.get(
                item.code,
                "Inspect the reported value and the corresponding SIESTA manual section.",
            ),
            evidence=item.evidence,
        )
        for item in result.findings
    )
    ruleset_sha256 = contract_sha256(
        {
            "adapter": "siestaflow.siesta.legacy-input",
            "codes": sorted(item.code for item in result.findings),
        }
    )
    report = ValidationReport.build(
        report_id=f"{subject_id}:siesta-input",
        subject=subject,
        findings=findings,
        ruleset_sha256=ruleset_sha256,
        produced_by=producer,
        metadata={"legacy_status": result.status.value},
    )
    if report.status is not result.status:
        raise ValueError(
            "legacy validation status does not agree with its findings"
        )
    return report


def artifact_reference_from_siesta(
    descriptor: SiestaArtifactDescriptor,
) -> ArtifactReference:
    artifact_type = descriptor.artifact_type.upper()
    return ArtifactReference(
        artifact_id=(
            f"{descriptor.task_id}:{descriptor.attempt_id}:"
            f"{descriptor.sha256[:12]}"
        ),
        role=_ARTIFACT_ROLE_BY_TYPE.get(artifact_type, ArtifactRole.OTHER),
        relative_path=descriptor.path,
        sha256=descriptor.sha256,
        size_bytes=descriptor.size_bytes,
        media_type=f"application/x-siesta-{artifact_type.lower()}",
        producer_task_id=descriptor.task_id,
        producer_attempt_id=descriptor.attempt_id,
        metadata={
            "automatic_reuse": descriptor.automatic_reuse,
            "default_compatibility": descriptor.default_compatibility,
            "siesta_artifact_type": descriptor.artifact_type,
        },
    )


def step_launch_spec_from_execution_request(
    request: ExecutionRequest,
    *,
    root: Path,
    hosts: tuple[str, ...],
) -> StepLaunchSpec:
    """Adapt a path-safe execution request to the current launcher protocol."""

    resolved_root = root.resolve()

    def resolve(relative: str) -> Path:
        candidate = (resolved_root / Path(*relative.split("/"))).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"execution path escapes root: {relative}") from exc
        return candidate

    if hosts and len(hosts) != request.resources.nodes:
        raise ValueError("host count does not match requested nodes")
    return StepLaunchSpec(
        task_id=request.task_id,
        attempt_id=request.attempt_id,
        workdir=resolve(request.working_directory),
        input_path=resolve(request.input_path),
        stdout_path=resolve(request.stdout_path),
        stderr_path=resolve(request.stderr_path),
        mpi_processes=request.resources.mpi_processes,
        cpus_per_process=request.resources.cpus_per_process,
        executable=request.executable,
        executable_arguments=request.arguments,
        environment=request.environment,
        hosts=hosts,
        processes_per_node=request.resources.processes_per_node,
    )


def execution_evidence_from_step_outcome(
    outcome: StepOutcome,
    *,
    artifacts: tuple[ArtifactReference, ...] = (),
    metrics: dict[str, Any] | None = None,
) -> ExecutionEvidence:
    if outcome.terminated_by_controller:
        failure = FailureType.INTERRUPTED
    elif outcome.exit_code == 0:
        failure = FailureType.SUCCESS
    else:
        failure = FailureType.PROCESS_FAILURE
    return ExecutionEvidence(
        task_id=outcome.task_id,
        attempt_id=outcome.attempt_id,
        command=outcome.command,
        exit_code=outcome.exit_code,
        elapsed_seconds=outcome.elapsed_seconds,
        failure=failure,
        terminated_by_controller=outcome.terminated_by_controller,
        artifacts=artifacts,
        metrics=dict(metrics or {}),
    )
