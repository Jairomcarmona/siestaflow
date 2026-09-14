"""Stable decision and execution status vocabularies.

These enums belong to the contract kernel.  Higher-level modules may re-export
them, but must not define competing representations or replace them with
booleans.
"""

from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    PENDING = "PENDING"
    PLANNED = "PLANNED"
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REVIEW = "REVIEW"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"
    INCOMPLETE = "INCOMPLETE"
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


DECISION_RANK = {
    DecisionStatus.PASS: 0,
    DecisionStatus.REVIEW: 1,
    DecisionStatus.BLOCKED: 2,
    DecisionStatus.FAIL: 3,
}


def aggregate_decisions(
    decisions: tuple[DecisionStatus, ...] | list[DecisionStatus],
) -> DecisionStatus:
    """Return the most restrictive decision using the public contract order."""

    return max(decisions, key=DECISION_RANK.get, default=DecisionStatus.PASS)

