"""Engine-neutral references for governed scientific artifacts and approvals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .versioning import require_namespaced_identifier
from .workflow import require_local_id


def _sha256(value: str, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64:
        raise ValueError(f"{field} must contain 64 hexadecimal characters")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must contain 64 hexadecimal characters") from exc
    return normalized


class ScientificAuthority(str, Enum):
    """Authority attached to a scientific input or derived decision."""

    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class ScientificArtifactReference:
    """Hash-bound reference whose artifact type remains plugin-extensible."""

    artifact_id: str
    artifact_type: str
    sha256: str
    provenance_sha256: str
    authority: ScientificAuthority = ScientificAuthority.PROVISIONAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", require_local_id(self.artifact_id, field_name="scientific artifact id"))
        object.__setattr__(self, "artifact_type", require_namespaced_identifier(self.artifact_type, field="scientific artifact type"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, field="scientific artifact sha256"))
        object.__setattr__(self, "provenance_sha256", _sha256(self.provenance_sha256, field="scientific artifact provenance_sha256"))
        object.__setattr__(self, "authority", ScientificAuthority(self.authority))


@dataclass(frozen=True)
class ScientificApproval:
    """Human decision bound to one exact subject and its evidence."""

    approval_id: str
    subject_sha256: str
    evidence_sha256: str
    decision: ApprovalDecision
    actor: str
    decided_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", require_local_id(self.approval_id, field_name="approval id"))
        object.__setattr__(self, "subject_sha256", _sha256(self.subject_sha256, field="approval subject_sha256"))
        object.__setattr__(self, "evidence_sha256", _sha256(self.evidence_sha256, field="approval evidence_sha256"))
        object.__setattr__(self, "decision", ApprovalDecision(self.decision))
        actor = str(self.actor).strip()
        decided_at = str(self.decided_at).strip()
        if not actor or not decided_at:
            raise ValueError("scientific approval requires actor and decided_at")
        try:
            parsed = datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("scientific approval decided_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("scientific approval decided_at must include a timezone")
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "decided_at", decided_at)


@dataclass(frozen=True)
class NumericalProfileReference:
    """A numerical profile may be used provisionally or through an approval."""

    profile_id: str
    sha256: str
    authority: ScientificAuthority
    approval_id: str | None = None
    approval_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", require_local_id(self.profile_id, field_name="numerical profile id"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, field="numerical profile sha256"))
        authority = ScientificAuthority(self.authority)
        object.__setattr__(self, "authority", authority)
        if authority is ScientificAuthority.APPROVED:
            if self.approval_id is None or self.approval_sha256 is None:
                raise ValueError("approved numerical profile requires hash-bound approval")
            object.__setattr__(self, "approval_id", require_local_id(self.approval_id, field_name="approval id"))
            object.__setattr__(self, "approval_sha256", _sha256(self.approval_sha256, field="approval sha256"))
        elif self.approval_id is not None or self.approval_sha256 is not None:
            raise ValueError("provisional numerical profile cannot claim approval")
