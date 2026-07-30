from __future__ import annotations

from datetime import datetime, timedelta, timezone

from siestaflow.authorization import AuthorizationEngine
from siestaflow.gates import GateEngine
from siestaflow.models import DecisionStatus, FailureType, TaskResult, TaskSpec


def _envelope(*, expires_delta: timedelta = timedelta(hours=1)):
    now = datetime.now(timezone.utc)
    return AuthorizationEngine.issue(
        authorization_id="AUTH_001",
        campaign_id="CAMPAIGN_001",
        allowed_task_types=("SIMULATED",),
        generic_targets=("TARGET_001",),
        forbidden_operations=("DELETE",),
        stop_on_review=True,
        issued_by="human-reviewer",
        issued_at=now.isoformat(),
        expires_at=(now + expires_delta).isoformat(),
    )


def _task(task_type: str = "SIMULATED", target: str = "TARGET_001"):
    return TaskSpec("TASK_001", task_type, target, ("fake",), 10.0)


def test_authorized_task_passes_without_boolean_decision():
    decision = AuthorizationEngine().authorize(_envelope(), _task())
    assert decision.status is DecisionStatus.PASS


def test_unauthorized_stale_and_hash_mismatch_are_blocked():
    engine = AuthorizationEngine()
    assert engine.authorize(_envelope(), _task("NOT_ALLOWED")).status is DecisionStatus.BLOCKED
    assert engine.authorize(_envelope(expires_delta=timedelta(seconds=-1)), _task()).status is DecisionStatus.BLOCKED
    tampered = engine.tampered_copy(_envelope(), issued_by="attacker")
    assert engine.authorize(tampered, _task()).status is DecisionStatus.BLOCKED


def _result(failure: FailureType, warnings=()):
    return TaskResult("T", "A", failure, 0, "", "", 1.0, tuple(warnings))


def test_gate_only_pass_advances_and_review_never_becomes_pass():
    gates = GateEngine()
    assert gates.evaluate(_result(FailureType.SUCCESS)).status is DecisionStatus.PASS
    assert gates.evaluate(_result(FailureType.UNKNOWN_WARNING, ("new",))).status is DecisionStatus.REVIEW
    assert gates.evaluate(_result(FailureType.PROCESS_FAILURE)).status is DecisionStatus.FAIL
    assert gates.evaluate(_result(FailureType.INTERRUPTED)).status is DecisionStatus.BLOCKED

