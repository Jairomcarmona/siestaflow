"""Append-only event contract used by CLI, monitoring, and future UIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .serialization import canonical_primitive, validate_extensions
from .versioning import ContractVersion, require_namespaced_identifier


@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    event_type: str
    source: str
    subject_id: str
    sequence: int
    timestamp: str
    payload: Mapping[str, Any]
    correlation_id: str | None = None
    causation_id: str | None = None
    contract_version: ContractVersion = ContractVersion(1, 0)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.source.strip() or not self.subject_id.strip():
            raise ValueError("events require event_id, source, and subject_id")
        require_namespaced_identifier(self.event_type, field="event_type")
        if self.sequence < 0:
            raise ValueError("event sequence cannot be negative")
        if not self.timestamp.strip():
            raise ValueError("event timestamp must be explicit")
        canonical_primitive(self.payload)
        canonical_primitive(self.extensions)
        validate_extensions(self.extensions)
