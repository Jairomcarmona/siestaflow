"""Typed domain models shared by all M1 kernel layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def primitive(value: Any) -> Any:
    """Convert dataclasses/enums into deterministic JSON-compatible values."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return primitive(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [primitive(item) for item in value]
    return value


class TaskState(str, Enum):
    PLANNED = "PLANNED"
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REVIEW = "REVIEW"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    INTERRUPTED = "INTERRUPTED"
    SKIPPED = "SKIPPED"


class DecisionStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class FailureType(str, Enum):
    SUCCESS = "SUCCESS"
    INPUT_ERROR = "INPUT_ERROR"
    PROCESS_FAILURE = "PROCESS_FAILURE"
    TIMEOUT = "TIMEOUT"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    NODE_FAILURE = "NODE_FAILURE"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    TRUNCATED_OUTPUT = "TRUNCATED_OUTPUT"
    UNKNOWN_WARNING = "UNKNOWN_WARNING"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass(frozen=True)
class ProjectManifest:
    project_id: str
    name: str
    schema_version: str = "1.0"
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class WorkspaceRecord:
    campaign_id: str
    task_id: str
    attempt_id: str
    path: str
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    task_type: str
    target_id: str
    command: tuple[str, ...]
    estimated_runtime_seconds: float | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CampaignManifest:
    campaign_id: str
    project_id: str
    tasks: tuple[TaskSpec, ...]
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"


@dataclass
class CampaignState:
    campaign_id: str
    allocation_id: str | None = None
    task_states: dict[str, TaskState] = field(default_factory=dict)
    attempt_counts: dict[str, int] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    final_decision: DecisionStatus | None = None
    revision: int = 0
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CampaignState":
        return cls(
            campaign_id=str(data["campaign_id"]),
            allocation_id=data.get("allocation_id"),
            task_states={
                key: TaskState(value) for key, value in data.get("task_states", {}).items()
            },
            attempt_counts={
                key: int(value) for key, value in data.get("attempt_counts", {}).items()
            },
            results=dict(data.get("results", {})),
            final_decision=(
                DecisionStatus(data["final_decision"])
                if data.get("final_decision")
                else None
            ),
            revision=int(data.get("revision", 0)),
            updated_at=str(data.get("updated_at", utc_now())),
        )


@dataclass(frozen=True)
class TaskAttempt:
    campaign_id: str
    task_id: str
    attempt_id: str
    allocation_id: str
    workspace: str
    started_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    attempt_id: str
    failure: FailureType
    exit_code: int | None
    stdout: str
    stderr: str
    runtime_seconds: float
    warnings: tuple[str, ...] = ()
    completed_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class AuthorizationEnvelope:
    authorization_id: str
    campaign_id: str
    allowed_task_types: tuple[str, ...]
    generic_targets: tuple[str, ...]
    forbidden_operations: tuple[str, ...]
    stop_on_review: bool
    issued_by: str
    issued_at: str
    expires_at: str
    content_hash: str


@dataclass(frozen=True)
class GateDecision:
    status: DecisionStatus
    reason: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class AllocationContext:
    allocation_id: str
    campaign_id: str
    total_seconds: float
    remaining_seconds: float
    started_at: str
    active: bool = True


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    campaign_id: str
    task_id: str
    attempt_id: str
    relative_path: str
    size_bytes: int
    sha256: str
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class EventRecord:
    timestamp: str
    campaign_id: str
    task_id: str
    attempt_id: str
    event_type: str
    previous_state: str | None
    new_state: str | None
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureRecord:
    failure_type: FailureType
    reason: str
    retryable: bool = False


@dataclass(frozen=True)
class RuntimeEstimate:
    estimated_seconds: float | None
    source: str
    authorized: bool

