"""Generic execution contracts and fully local HPC simulations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import Enum

from .models import (
    AllocationContext,
    FailureRecord,
    FailureType,
    RuntimeEstimate,
    TaskAttempt,
    TaskResult,
    TaskSpec,
    utc_now,
)


class ProcessLauncher(ABC):
    @abstractmethod
    def launch(
        self,
        task: TaskSpec,
        attempt: TaskAttempt,
        allocation: AllocationContext,
    ) -> TaskResult: ...


class LocalFakeLauncher(ProcessLauncher):
    """Deterministic launcher; it never calls subprocess or a scientific engine."""

    MODES = {
        "success",
        "failure",
        "timeout",
        "cancelled",
        "truncated_output",
        "unknown_warning",
        "interruption",
    }

    def __init__(self, scenarios: dict[str, str] | None = None) -> None:
        self.scenarios = dict(scenarios or {})
        self.launches: list[tuple[str, str, str]] = []

    def set_scenario(self, task_id: str, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(f"unsupported fake mode: {mode}")
        self.scenarios[task_id] = mode

    def launch(
        self,
        task: TaskSpec,
        attempt: TaskAttempt,
        allocation: AllocationContext,
    ) -> TaskResult:
        mode = self.scenarios.get(task.task_id, "success")
        if mode not in self.MODES:
            raise ValueError(f"unsupported fake mode: {mode}")
        self.launches.append((allocation.allocation_id, task.task_id, attempt.attempt_id))
        runtime = float(task.estimated_runtime_seconds or 0.0)
        outcomes = {
            "success": (FailureType.SUCCESS, 0, "SIMULATED_SUCCESS\n", "", ()),
            "failure": (FailureType.PROCESS_FAILURE, 2, "", "simulated failure\n", ()),
            "timeout": (FailureType.TIMEOUT, None, "", "simulated timeout\n", ()),
            "cancelled": (FailureType.CANCELLED, None, "", "simulated cancellation\n", ()),
            "truncated_output": (FailureType.TRUNCATED_OUTPUT, 0, "TRUNCATED", "", ()),
            "unknown_warning": (
                FailureType.UNKNOWN_WARNING,
                0,
                "SIMULATED_SUCCESS\n",
                "unknown warning\n",
                ("UNKNOWN_WARNING",),
            ),
            "interruption": (FailureType.INTERRUPTED, None, "PARTIAL", "interrupted\n", ()),
        }
        failure, exit_code, stdout, stderr, warnings = outcomes[mode]
        return TaskResult(
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            failure=failure,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            runtime_seconds=runtime,
            warnings=warnings,
        )


class SlurmJobState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    NODE_FAIL = "NODE_FAIL"
    UNKNOWN = "UNKNOWN"


class SlurmResolution(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    NODE_FAIL = "NODE_FAIL"
    UNKNOWN = "UNKNOWN"
    NON_TERMINAL = "NON_TERMINAL"
    TERMINAL_STATE_REQUIRES_EVIDENCE = "TERMINAL_STATE_REQUIRES_EVIDENCE"


class SlurmClient(ABC):
    @abstractmethod
    def submit_allocation(self, campaign_id: str, total_seconds: float) -> AllocationContext: ...

    @abstractmethod
    def remaining_time(self, allocation_id: str) -> float: ...

    @abstractmethod
    def resolve_terminal(self, job_id: str) -> SlurmResolution: ...


class FakeSlurmClient(SlurmClient):
    """In-memory SLURM lifecycle with independent queue and accounting evidence."""

    TERMINAL = {
        SlurmJobState.COMPLETED,
        SlurmJobState.FAILED,
        SlurmJobState.CANCELLED,
        SlurmJobState.TIMEOUT,
        SlurmJobState.NODE_FAIL,
    }

    def __init__(self) -> None:
        self._counter = 0
        self.allocations: dict[str, AllocationContext] = {}
        self.jobs: dict[str, SlurmJobState] = {}
        self.job_for_allocation: dict[str, str] = {}
        self.queue_presence: dict[str, bool] = {}
        self.accounting: dict[str, SlurmJobState] = {}
        self.signals: list[tuple[str, str]] = []
        self.submissions = 0

    def submit_allocation(self, campaign_id: str, total_seconds: float) -> AllocationContext:
        if total_seconds <= 0:
            raise ValueError("allocation duration must be positive")
        self._counter += 1
        allocation_id = f"FAKE_ALLOCATION_{self._counter:04d}"
        job_id = f"FAKE_JOB_{self._counter:04d}"
        context = AllocationContext(
            allocation_id=allocation_id,
            campaign_id=campaign_id,
            total_seconds=float(total_seconds),
            remaining_seconds=float(total_seconds),
            started_at=utc_now(),
        )
        self.allocations[allocation_id] = context
        self.jobs[job_id] = SlurmJobState.RUNNING
        self.job_for_allocation[allocation_id] = job_id
        self.queue_presence[job_id] = True
        self.submissions += 1
        return context

    def get_allocation(self, allocation_id: str) -> AllocationContext:
        return self.allocations[allocation_id]

    def remaining_time(self, allocation_id: str) -> float:
        return self.allocations[allocation_id].remaining_seconds

    def consume(self, allocation_id: str, seconds: float) -> None:
        current = self.allocations[allocation_id]
        remaining = max(0.0, current.remaining_seconds - max(0.0, seconds))
        self.allocations[allocation_id] = replace(current, remaining_seconds=remaining)

    def set_remaining(self, allocation_id: str, seconds: float) -> None:
        current = self.allocations[allocation_id]
        self.allocations[allocation_id] = replace(current, remaining_seconds=max(0.0, seconds))

    def end_allocation(self, allocation_id: str, state: SlurmJobState = SlurmJobState.COMPLETED) -> None:
        current = self.allocations[allocation_id]
        self.allocations[allocation_id] = replace(current, active=False)
        job_id = self.job_for_allocation[allocation_id]
        self.jobs[job_id] = state
        self.queue_presence[job_id] = False
        self.accounting[job_id] = state

    def emit_signal(self, allocation_id: str, signal: str = "USR1") -> None:
        self.signals.append((allocation_id, signal))

    def set_job_state(self, job_id: str, state: SlurmJobState, *, in_queue: bool = True) -> None:
        self.jobs[job_id] = state
        self.queue_presence[job_id] = in_queue

    def set_accounting(self, job_id: str, state: SlurmJobState | None) -> None:
        if state is None:
            self.accounting.pop(job_id, None)
        else:
            self.accounting[job_id] = state

    def resolve_terminal(self, job_id: str) -> SlurmResolution:
        if self.queue_presence.get(job_id, False):
            state = self.jobs.get(job_id, SlurmJobState.UNKNOWN)
            if state in self.TERMINAL:
                return SlurmResolution(state.value)
            if state is SlurmJobState.UNKNOWN:
                return SlurmResolution.UNKNOWN
            return SlurmResolution.NON_TERMINAL
        evidence = self.accounting.get(job_id)
        if evidence in self.TERMINAL:
            return SlurmResolution(evidence.value)
        return SlurmResolution.TERMINAL_STATE_REQUIRES_EVIDENCE


class BudgetStatus(str, Enum):
    ALLOW = "ALLOW"
    INSUFFICIENT_TIME = "INSUFFICIENT_TIME"
    UNKNOWN_RUNTIME = "UNKNOWN_RUNTIME"
    UNAUTHORIZED_ESTIMATE = "UNAUTHORIZED_ESTIMATE"


@dataclass(frozen=True)
class BudgetDecision:
    status: BudgetStatus
    required_seconds: float | None
    remaining_seconds: float
    reason: str


class TimeBudget:
    def __init__(
        self,
        *,
        safety_factor: float = 1.5,
        shutdown_margin_seconds: float = 1800,
        checkpoint_margin_seconds: float = 300,
    ) -> None:
        if safety_factor < 1 or shutdown_margin_seconds < 0 or checkpoint_margin_seconds < 0:
            raise ValueError("invalid time budget policy")
        self.safety_factor = safety_factor
        self.shutdown_margin_seconds = shutdown_margin_seconds
        self.checkpoint_margin_seconds = checkpoint_margin_seconds

    def can_start(self, estimate: RuntimeEstimate, remaining_seconds: float) -> BudgetDecision:
        if estimate.estimated_seconds is None:
            return BudgetDecision(BudgetStatus.UNKNOWN_RUNTIME, None, remaining_seconds, "UNKNOWN_RUNTIME")
        if not estimate.authorized:
            return BudgetDecision(
                BudgetStatus.UNAUTHORIZED_ESTIMATE,
                None,
                remaining_seconds,
                "runtime estimate is not authorized",
            )
        required = (
            estimate.estimated_seconds * self.safety_factor
            + self.shutdown_margin_seconds
            + self.checkpoint_margin_seconds
        )
        if required < remaining_seconds:
            return BudgetDecision(BudgetStatus.ALLOW, required, remaining_seconds, "sufficient time")
        return BudgetDecision(
            BudgetStatus.INSUFFICIENT_TIME,
            required,
            remaining_seconds,
            "insufficient remaining allocation time",
        )


class FailureClassifier:
    """Classify process evidence without mutating task parameters."""

    @staticmethod
    def classify(
        *,
        exit_code: int | None,
        input_error: bool = False,
        timed_out: bool = False,
        cancelled: bool = False,
        interrupted: bool = False,
        truncated_output: bool = False,
        unknown_warning: bool = False,
        stderr: str = "",
    ) -> FailureRecord:
        lowered = stderr.lower()
        if input_error:
            return FailureRecord(FailureType.INPUT_ERROR, "input validation failed")
        if timed_out:
            return FailureRecord(FailureType.TIMEOUT, "process timeout")
        if cancelled:
            return FailureRecord(FailureType.CANCELLED, "process cancelled")
        if interrupted:
            return FailureRecord(FailureType.INTERRUPTED, "process interrupted", retryable=True)
        if "out of memory" in lowered or "oom" in lowered:
            return FailureRecord(FailureType.OUT_OF_MEMORY, "out of memory")
        if "node_fail" in lowered or "node failure" in lowered:
            return FailureRecord(FailureType.NODE_FAILURE, "node failure", retryable=True)
        if truncated_output:
            return FailureRecord(FailureType.TRUNCATED_OUTPUT, "output truncated")
        if unknown_warning:
            return FailureRecord(FailureType.UNKNOWN_WARNING, "unknown warning")
        if exit_code == 0:
            return FailureRecord(FailureType.SUCCESS, "exit code zero")
        if exit_code is None:
            return FailureRecord(FailureType.UNKNOWN_FAILURE, "missing terminal evidence")
        return FailureRecord(FailureType.PROCESS_FAILURE, f"exit code {exit_code}")
