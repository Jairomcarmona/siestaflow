"""SIESTA-specific immutable domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ...models import DecisionStatus


@dataclass(frozen=True)
class SourceSpan:
    source: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ParseDiagnostic:
    code: str
    message: str
    severity: str
    span: SourceSpan


@dataclass
class FDFNode:
    raw: str
    span: SourceSpan


@dataclass
class FDFScalar(FDFNode):
    label: str
    value: str
    unit: str | None = None


@dataclass
class FDFBlock(FDFNode):
    name: str
    header: str
    body_lines: tuple[str, ...]
    footer: str | None
    closed: bool
    redirected_to: str | None = None


@dataclass
class FDFComment(FDFNode):
    text: str = ""


@dataclass
class FDFBlankLine(FDFNode):
    pass


@dataclass
class FDFInclude(FDFNode):
    target: str = ""
    directive: str = "%include"
    label: str | None = None


@dataclass
class FDFUnknown(FDFNode):
    reason: str = "unclassified content"


@dataclass
class FDFDocument:
    source: str
    nodes: list[FDFNode]
    diagnostics: list[ParseDiagnostic]
    newline_style: str
    original_sha256: str

    def render(self) -> str:
        return "".join(node.raw for node in self.nodes)

    def scalars(self, label: str | None = None) -> list[FDFScalar]:
        found = [node for node in self.nodes if isinstance(node, FDFScalar)]
        return found if label is None else [n for n in found if normalize_label(n.label) == normalize_label(label)]

    def blocks(self, name: str | None = None) -> list[FDFBlock]:
        found = [node for node in self.nodes if isinstance(node, FDFBlock)]
        return found if name is None else [n for n in found if normalize_label(n.name) == normalize_label(name)]


def normalize_label(label: str) -> str:
    return "".join(character.lower() for character in label if character not in ".-_ ")


class MutableStatus(str, Enum):
    PARSED_ONLY = "PARSED_ONLY"
    VALIDATED_READ_ONLY = "VALIDATED_READ_ONLY"
    MUTABLE_TECHNICAL = "MUTABLE_TECHNICAL"
    SCIENTIFICALLY_GOVERNED = "SCIENTIFICALLY_GOVERNED"
    PASSTHROUGH_UNKNOWN = "PASSTHROUGH_UNKNOWN"


@dataclass(frozen=True)
class FDFRegistryEntry:
    canonical_name: str
    kind: str
    value_type: str
    unit_policy: str
    repeat_policy: str
    mutable_status: MutableStatus
    scientific_scope: str
    evidence_class: str
    manual_reference: str
    notes: str


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    status: DecisionStatus
    message: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class InputValidationResult:
    status: DecisionStatus
    findings: tuple[ValidationFinding, ...]
    atoms: int | None
    species: tuple[str, ...]
    system_id: str | None


class OutputClassification(str, Enum):
    COMPLETED = "COMPLETED"
    SCF_NOT_CONVERGED = "SCF_NOT_CONVERGED"
    INPUT_ERROR = "INPUT_ERROR"
    PSEUDOPOTENTIAL_ERROR = "PSEUDOPOTENTIAL_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    TIMEOUT = "TIMEOUT"
    NODE_FAILURE = "NODE_FAILURE"
    CANCELLED = "CANCELLED"
    TRUNCATED_OUTPUT = "TRUNCATED_OUTPUT"
    UNKNOWN_WARNING = "UNKNOWN_WARNING"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass(frozen=True)
class SiestaOutputRecord:
    classification: OutputClassification
    provisional_status: str
    version: str | None
    started: bool
    normal_termination: bool
    scf_started: bool
    scf_converged: bool
    scf_iterations: int | None
    energies: tuple[float, ...]
    max_force: float | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    atoms: int | None
    species: int | None
    spin_evidence: str | None
    elapsed_seconds: float | None
    mentioned_artifacts: tuple[str, ...]
    line_count: int
    synthetic: bool = False


@dataclass(frozen=True)
class ArtifactDescriptor:
    path: str
    artifact_type: str
    size_bytes: int
    sha256: str
    task_id: str
    attempt_id: str
    automatic_reuse: bool = False
    default_compatibility: str = "DENY"


@dataclass(frozen=True)
class PreparedInput:
    source: Path
    destination: Path
    sha256: str
    validation: InputValidationResult
    metadata: Mapping[str, Any] = field(default_factory=dict)
