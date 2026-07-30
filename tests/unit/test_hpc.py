from __future__ import annotations

import pytest

from siestaflow.hpc import (
    BudgetStatus,
    FailureClassifier,
    FakeSlurmClient,
    LocalFakeLauncher,
    SlurmJobState,
    SlurmResolution,
    TimeBudget,
)
from siestaflow.models import AllocationContext, FailureType, RuntimeEstimate, TaskAttempt, TaskSpec, utc_now


@pytest.mark.parametrize(
    "state,resolution",
    [
        (SlurmJobState.COMPLETED, SlurmResolution.COMPLETED),
        (SlurmJobState.FAILED, SlurmResolution.FAILED),
        (SlurmJobState.CANCELLED, SlurmResolution.CANCELLED),
        (SlurmJobState.TIMEOUT, SlurmResolution.TIMEOUT),
        (SlurmJobState.NODE_FAIL, SlurmResolution.NODE_FAIL),
        (SlurmJobState.UNKNOWN, SlurmResolution.UNKNOWN),
    ],
)
def test_fake_slurm_states(state: SlurmJobState, resolution: SlurmResolution):
    client = FakeSlurmClient()
    allocation = client.submit_allocation("CAMPAIGN_001", 100)
    job = client.job_for_allocation[allocation.allocation_id]
    client.set_job_state(job, state, in_queue=True)
    assert client.resolve_terminal(job) is resolution


def test_empty_squeue_requires_terminal_evidence():
    client = FakeSlurmClient()
    allocation = client.submit_allocation("CAMPAIGN_001", 100)
    job = client.job_for_allocation[allocation.allocation_id]
    client.set_job_state(job, SlurmJobState.COMPLETED, in_queue=False)
    client.set_accounting(job, None)

    assert client.resolve_terminal(job) is SlurmResolution.TERMINAL_STATE_REQUIRES_EVIDENCE
    client.set_accounting(job, SlurmJobState.COMPLETED)
    assert client.resolve_terminal(job) is SlurmResolution.COMPLETED


def test_fake_allocation_time_signal_and_end():
    client = FakeSlurmClient()
    allocation = client.submit_allocation("C", 100)
    client.consume(allocation.allocation_id, 25)
    client.emit_signal(allocation.allocation_id)
    client.end_allocation(allocation.allocation_id)

    assert client.remaining_time(allocation.allocation_id) == 75
    assert client.signals == [(allocation.allocation_id, "USR1")]
    assert client.get_allocation(allocation.allocation_id).active is False


def test_time_budget_formula_unknown_and_strict_boundary():
    budget = TimeBudget(safety_factor=1.5, shutdown_margin_seconds=1800, checkpoint_margin_seconds=300)
    known = RuntimeEstimate(100, "static", True)
    assert budget.can_start(known, 2251).status is BudgetStatus.ALLOW
    assert budget.can_start(known, 2250).status is BudgetStatus.INSUFFICIENT_TIME
    assert budget.can_start(RuntimeEstimate(None, "none", False), 9999).status is BudgetStatus.UNKNOWN_RUNTIME


def test_failure_classifier_does_not_change_task_physics():
    record = FailureClassifier.classify(exit_code=137, stderr="OOM kill")
    assert record.failure_type is FailureType.OUT_OF_MEMORY
    assert record.retryable is False


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("success", FailureType.SUCCESS),
        ("failure", FailureType.PROCESS_FAILURE),
        ("timeout", FailureType.TIMEOUT),
        ("cancelled", FailureType.CANCELLED),
        ("truncated_output", FailureType.TRUNCATED_OUTPUT),
        ("unknown_warning", FailureType.UNKNOWN_WARNING),
        ("interruption", FailureType.INTERRUPTED),
    ],
)
def test_local_fake_launcher_simulates_every_required_mode(mode, expected):
    launcher = LocalFakeLauncher({"TASK_001": mode})
    task = TaskSpec("TASK_001", "SIMULATED", "TARGET_001", ("fake",), 1.0)
    allocation = AllocationContext("A", "C", 100, 100, utc_now())
    attempt = TaskAttempt("C", "TASK_001", "attempt_001", "A", "/fake")

    assert launcher.launch(task, attempt, allocation).failure is expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"exit_code": 0}, FailureType.SUCCESS),
        ({"exit_code": 2, "input_error": True}, FailureType.INPUT_ERROR),
        ({"exit_code": 2}, FailureType.PROCESS_FAILURE),
        ({"exit_code": None, "timed_out": True}, FailureType.TIMEOUT),
        ({"exit_code": 137, "stderr": "out of memory"}, FailureType.OUT_OF_MEMORY),
        ({"exit_code": 1, "stderr": "NODE_FAIL"}, FailureType.NODE_FAILURE),
        ({"exit_code": None, "cancelled": True}, FailureType.CANCELLED),
        ({"exit_code": None, "interrupted": True}, FailureType.INTERRUPTED),
        ({"exit_code": 0, "truncated_output": True}, FailureType.TRUNCATED_OUTPUT),
        ({"exit_code": 0, "unknown_warning": True}, FailureType.UNKNOWN_WARNING),
        ({"exit_code": None}, FailureType.UNKNOWN_FAILURE),
    ],
)
def test_failure_classifier_covers_all_required_types(kwargs, expected):
    assert FailureClassifier.classify(**kwargs).failure_type is expected
