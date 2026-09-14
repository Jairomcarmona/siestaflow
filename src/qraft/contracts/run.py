"""Engine-neutral identity for a prepared, manually submitted run package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .catalog import RUN_LOCK
from .serialization import ContractEnvelope, canonical_primitive
from .workflow import require_local_id


def _require_sha256(value: str, *, field_name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64:
        raise ValueError(f"{field_name} must contain 64 hexadecimal characters")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must contain 64 hexadecimal characters"
        ) from exc
    return normalized


@dataclass(frozen=True)
class PreparedRun:
    """Hash-bound bridge from a compiled workflow to an execution package."""

    run_id: str
    workflow_id: str
    project_id: str
    workflow_lock_sha256: str
    execution_profile_id: str
    execution_profile_sha256: str
    controller_campaign_sha256: str
    task_ids: tuple[str, ...]
    target: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    execution_authorized: bool = False
    submission_performed: bool = False

    def __post_init__(self) -> None:
        for field_name in ("run_id", "workflow_id", "project_id"):
            object.__setattr__(
                self,
                field_name,
                require_local_id(
                    str(getattr(self, field_name)),
                    field_name=field_name,
                ),
            )
        if not self.execution_profile_id.strip():
            raise ValueError("execution_profile_id must be non-empty")
        for field_name in (
            "workflow_lock_sha256",
            "execution_profile_sha256",
            "controller_campaign_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(
                    str(getattr(self, field_name)),
                    field_name=field_name,
                ),
            )
        if not self.task_ids or len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("prepared runs require unique task ids")
        for task_id in self.task_ids:
            require_local_id(task_id, field_name="run task id")
        if self.target not in {"slurm"}:
            raise ValueError(f"unsupported prepared-run target: {self.target}")
        if self.execution_authorized or self.submission_performed:
            raise ValueError(
                "run preparation cannot authorize or submit execution"
            )
        canonical_primitive(self.metadata)

    def payload(self) -> dict[str, Any]:
        return canonical_primitive(
            {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "workflow_id": self.workflow_id,
                "project_id": self.project_id,
                "workflow_lock_sha256": self.workflow_lock_sha256,
                "execution_profile_id": self.execution_profile_id,
                "execution_profile_sha256": self.execution_profile_sha256,
                "controller_campaign_sha256": (
                    self.controller_campaign_sha256
                ),
                "task_ids": self.task_ids,
                "target": self.target,
                "metadata": self.metadata,
                "execution_authorized": self.execution_authorized,
                "submission_performed": self.submission_performed,
            }
        )

    def envelope(
        self,
        *,
        producer: str = "siestaflow.run-preparer",
    ) -> ContractEnvelope:
        return ContractEnvelope.create(
            RUN_LOCK,
            producer=producer,
            payload=self.payload(),
        )
