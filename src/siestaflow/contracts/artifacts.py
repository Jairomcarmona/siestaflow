"""Artifact identity, integrity, transfer, and provenance contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping

from .serialization import canonical_primitive


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def require_relative_artifact_path(value: str, *, field_name: str) -> str:
    raw = str(value).replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.parts[0].endswith(":")
    ):
        raise ValueError(f"unsafe relative path in {field_name}: {value!r}")
    return path.as_posix()


class ArtifactRole(str, Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    RESTART = "RESTART"
    GEOMETRY = "GEOMETRY"
    DENSITY = "DENSITY"
    PSEUDOPOTENTIAL = "PSEUDOPOTENTIAL"
    EVIDENCE = "EVIDENCE"
    REPORT = "REPORT"
    OTHER = "OTHER"


class ProvenanceRelation(str, Enum):
    GENERATED_BY = "GENERATED_BY"
    DERIVED_FROM = "DERIVED_FROM"
    TRANSFERRED_FROM = "TRANSFERRED_FROM"
    VALIDATED_BY = "VALIDATED_BY"
    SELECTED_BY = "SELECTED_BY"


@dataclass(frozen=True)
class ArtifactReference:
    artifact_id: str
    role: ArtifactRole
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str
    producer_task_id: str | None = None
    producer_attempt_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id.strip() or not self.media_type.strip():
            raise ValueError("artifacts require id and media_type")
        object.__setattr__(
            self,
            "relative_path",
            require_relative_artifact_path(
                self.relative_path, field_name="relative_path"
            ),
        )
        normalized_hash = self.sha256.lower()
        if not _SHA256.fullmatch(normalized_hash):
            raise ValueError("artifact sha256 must contain 64 hexadecimal characters")
        object.__setattr__(self, "sha256", normalized_hash)
        if self.size_bytes < 0:
            raise ValueError("artifact size cannot be negative")
        if bool(self.producer_task_id) != bool(self.producer_attempt_id):
            raise ValueError(
                "producer_task_id and producer_attempt_id must be declared together"
            )
        canonical_primitive(self.metadata)


@dataclass(frozen=True)
class ArtifactTransfer:
    source_artifact_id: str
    source_task_id: str
    destination_relative_path: str
    expected_sha256: str
    required: bool = True

    def __post_init__(self) -> None:
        if not self.source_artifact_id.strip() or not self.source_task_id.strip():
            raise ValueError("artifact transfers require source artifact and task")
        object.__setattr__(
            self,
            "destination_relative_path",
            require_relative_artifact_path(
                self.destination_relative_path,
                field_name="destination_relative_path",
            ),
        )
        normalized_hash = self.expected_sha256.lower()
        if not _SHA256.fullmatch(normalized_hash):
            raise ValueError("transfer expected_sha256 is invalid")
        object.__setattr__(self, "expected_sha256", normalized_hash)


@dataclass(frozen=True)
class ProvenanceLink:
    subject_artifact_id: str
    relation: ProvenanceRelation
    object_id: str
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.subject_artifact_id.strip() or not self.object_id.strip():
            raise ValueError("provenance links require subject and object")
        if self.evidence_sha256 is not None:
            normalized_hash = self.evidence_sha256.lower()
            if not _SHA256.fullmatch(normalized_hash):
                raise ValueError("provenance evidence_sha256 is invalid")
            object.__setattr__(self, "evidence_sha256", normalized_hash)

