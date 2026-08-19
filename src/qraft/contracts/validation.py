"""Engine-neutral validation and scientific-review contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from .serialization import canonical_primitive, contract_sha256
from .status import DecisionStatus, aggregate_decisions
from .versioning import ContractVersion, require_namespaced_identifier


class EvidenceClass(str, Enum):
    MATHEMATICAL_CONSISTENCY = "MATHEMATICAL_CONSISTENCY"
    ENGINE_MANUAL = "ENGINE_MANUAL"
    PSEUDOPOTENTIAL_METADATA = "PSEUDOPOTENTIAL_METADATA"
    PROJECT_POLICY = "PROJECT_POLICY"
    LITERATURE_BACKED = "LITERATURE_BACKED"
    RUNTIME_EVIDENCE = "RUNTIME_EVIDENCE"
    HEURISTIC_REVIEW = "HEURISTIC_REVIEW"
    HUMAN_DECISION = "HUMAN_DECISION"


class FindingScope(str, Enum):
    SYNTAX = "SYNTAX"
    STRUCTURE = "STRUCTURE"
    PSEUDOPOTENTIAL = "PSEUDOPOTENTIAL"
    NUMERICAL = "NUMERICAL"
    PHYSICAL = "PHYSICAL"
    EXECUTION = "EXECUTION"
    PROVENANCE = "PROVENANCE"
    POLICY = "POLICY"


@dataclass(frozen=True)
class RuleDescriptor:
    rule_id: str
    version: ContractVersion
    summary: str
    evidence_class: EvidenceClass
    scopes: tuple[FindingScope, ...]
    supported_subjects: tuple[str, ...]
    deterministic: bool

    def __post_init__(self) -> None:
        require_namespaced_identifier(self.rule_id, field="rule_id")
        object.__setattr__(self, "version", ContractVersion.parse(self.version))
        if not self.summary.strip() or not self.scopes or not self.supported_subjects:
            raise ValueError("rules require summary, scopes, and supported subjects")

    @property
    def fingerprint(self) -> str:
        return contract_sha256(self)


@dataclass(frozen=True)
class ValidationSubject:
    subject_id: str
    subject_type: str
    engine: str | None = None
    engine_version: str | None = None
    source: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.subject_type.strip():
            raise ValueError("validation subjects require id and type")
        canonical_primitive(self.attributes)


@dataclass(frozen=True)
class ValidationFinding:
    rule_id: str
    code: str
    status: DecisionStatus
    message: str
    evidence_class: EvidenceClass
    scope: FindingScope
    subject_id: str
    location: str | None = None
    hint: str | None = None
    evidence: tuple[str, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_namespaced_identifier(self.rule_id, field="rule_id")
        if not self.code.strip() or not self.message.strip() or not self.subject_id.strip():
            raise ValueError("findings require code, message, and subject_id")
        canonical_primitive(self.data)


@dataclass(frozen=True)
class ValidationReport:
    report_id: str
    subject: ValidationSubject
    findings: tuple[ValidationFinding, ...]
    status: DecisionStatus
    ruleset_sha256: str
    produced_by: str
    contract_version: ContractVersion = ContractVersion(1, 0)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.report_id.strip() or not self.produced_by.strip():
            raise ValueError("validation reports require id and producer")
        if len(self.ruleset_sha256) != 64:
            raise ValueError("ruleset_sha256 must contain 64 hexadecimal characters")
        int(self.ruleset_sha256, 16)
        expected = aggregate_decisions([finding.status for finding in self.findings])
        if self.status is not expected:
            raise ValueError(
                f"report status {self.status.value} does not match findings {expected.value}"
            )
        canonical_primitive(self.metadata)

    @classmethod
    def build(
        cls,
        *,
        report_id: str,
        subject: ValidationSubject,
        findings: tuple[ValidationFinding, ...],
        ruleset_sha256: str,
        produced_by: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ValidationReport":
        return cls(
            report_id=report_id,
            subject=subject,
            findings=findings,
            status=aggregate_decisions([item.status for item in findings]),
            ruleset_sha256=ruleset_sha256.lower(),
            produced_by=produced_by,
            metadata=dict(metadata or {}),
        )


@runtime_checkable
class ValidationRule(Protocol):
    descriptor: RuleDescriptor

    def evaluate(
        self, subject: ValidationSubject
    ) -> tuple[ValidationFinding, ...]: ...

