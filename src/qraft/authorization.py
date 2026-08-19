"""Immutable, hashed authorization envelopes evaluated before side effects."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .errors import AuthorizationError
from .models import AuthorizationEnvelope, DecisionStatus, GateDecision, TaskSpec
from .storage import canonical_json, sha256_text


def _authorization_payload(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key != "content_hash"}


class AuthorizationEngine:
    @staticmethod
    def issue(
        *,
        authorization_id: str,
        campaign_id: str,
        allowed_task_types: tuple[str, ...],
        generic_targets: tuple[str, ...],
        forbidden_operations: tuple[str, ...],
        stop_on_review: bool,
        issued_by: str,
        issued_at: str,
        expires_at: str,
    ) -> AuthorizationEnvelope:
        values = locals().copy()
        digest = sha256_text(canonical_json(values))
        return AuthorizationEnvelope(content_hash=digest, **values)

    @staticmethod
    def verify(envelope: AuthorizationEnvelope, *, now: datetime | None = None) -> None:
        values = _authorization_payload(envelope.__dict__)
        expected = sha256_text(canonical_json(values))
        if envelope.content_hash != expected:
            raise AuthorizationError("authorization hash mismatch")
        instant = now or datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(envelope.expires_at)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if instant >= expiry:
            raise AuthorizationError("authorization is stale")

    def authorize(
        self,
        envelope: AuthorizationEnvelope,
        task: TaskSpec,
        *,
        now: datetime | None = None,
    ) -> GateDecision:
        try:
            self.verify(envelope, now=now)
        except AuthorizationError as exc:
            return GateDecision(DecisionStatus.BLOCKED, str(exc), ("authorization",))
        if task.task_type not in envelope.allowed_task_types:
            return GateDecision(DecisionStatus.BLOCKED, "task type is not authorized", (task.task_type,))
        if task.target_id not in envelope.generic_targets:
            return GateDecision(DecisionStatus.BLOCKED, "target is not authorized", (task.target_id,))
        operation = str(task.metadata.get("operation", task.task_type))
        if operation in envelope.forbidden_operations:
            return GateDecision(DecisionStatus.BLOCKED, "operation is forbidden", (operation,))
        return GateDecision(DecisionStatus.PASS, "task is authorized", (envelope.authorization_id,))

    @staticmethod
    def tampered_copy(envelope: AuthorizationEnvelope, **changes: Any) -> AuthorizationEnvelope:
        """Test helper: mutate fields without recomputing the immutable content hash."""
        return replace(envelope, **changes)

