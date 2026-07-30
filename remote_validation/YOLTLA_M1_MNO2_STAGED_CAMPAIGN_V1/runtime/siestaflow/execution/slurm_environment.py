"""Read-only view of the SLURM allocation and cooperative shutdown signals."""

from __future__ import annotations

import os
import signal
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Callable, Mapping


def _positive_int(value: str | None, name: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"missing or invalid SLURM value: {name}") from exc
    if parsed <= 0:
        raise ValueError(f"SLURM value must be positive: {name}")
    return parsed


@dataclass(frozen=True)
class SlurmEnvironment:
    """Allocation identity and capacity derived only from the process environment."""

    job_id: str
    submit_dir: Path
    end_time_epoch: float
    total_cpus: int
    nodes: int
    ntasks: int
    cpus_per_task: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, str] | None = None) -> "SlurmEnvironment":
        env = os.environ if values is None else values
        job_id = str(env.get("SLURM_JOB_ID", "")).strip()
        if not job_id:
            raise ValueError("SLURM_JOB_ID is required inside campaign worker")
        submit_raw = str(env.get("SLURM_SUBMIT_DIR", "")).strip()
        if not submit_raw:
            raise ValueError("SLURM_SUBMIT_DIR is required inside campaign worker")
        submit_dir = Path(submit_raw).resolve()
        if not submit_dir.is_dir():
            raise ValueError(f"SLURM_SUBMIT_DIR does not exist: {submit_dir}")
        try:
            end_time = float(str(env.get("SLURM_JOB_END_TIME", "")))
        except ValueError as exc:
            raise ValueError("SLURM_JOB_END_TIME must be a Unix timestamp") from exc
        if end_time <= 0:
            raise ValueError("SLURM_JOB_END_TIME must be a positive Unix timestamp")
        nodes = _positive_int(env.get("SLURM_NNODES", "1"), "SLURM_NNODES")
        ntasks = _positive_int(env.get("SLURM_NTASKS"), "SLURM_NTASKS")
        cpus_per_task = _positive_int(env.get("SLURM_CPUS_PER_TASK", "1"), "SLURM_CPUS_PER_TASK")
        total_cpus = ntasks * cpus_per_task
        return cls(job_id, submit_dir, end_time, total_cpus, nodes, ntasks, cpus_per_task)

    def remaining_seconds(self, *, now: float | None = None) -> float:
        current = time.time() if now is None else float(now)
        return max(0.0, self.end_time_epoch - current)

    def validate_capacity(self, *, nodes: int, total_cpus: int) -> None:
        if nodes > self.nodes:
            raise ValueError(f"configured nodes exceed allocation: {nodes}>{self.nodes}")
        if total_cpus > self.total_cpus:
            raise ValueError(f"configured CPUs exceed allocation: {total_cpus}>{self.total_cpus}")


class ShutdownRequest:
    """Thread-safe, first-signal-wins request used by the controller scheduler."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None
        self._requested_at: float | None = None

    def request(self, reason: str) -> None:
        with self._lock:
            if self._reason is None:
                self._reason = reason
                self._requested_at = time.monotonic()
            self._event.set()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    @property
    def elapsed_seconds(self) -> float:
        with self._lock:
            started = self._requested_at
        return 0.0 if started is None else max(0.0, time.monotonic() - started)


class SignalHandlers(AbstractContextManager["SignalHandlers"]):
    """Install SIGUSR1/SIGTERM handlers and restore previous handlers on exit."""

    def __init__(self, shutdown: ShutdownRequest, callback: Callable[[str], None] | None = None) -> None:
        self.shutdown = shutdown
        self.callback = callback
        self._previous: dict[int, signal.Handlers] = {}

    def __enter__(self) -> "SignalHandlers":
        for name in ("SIGUSR1", "SIGTERM"):
            number = getattr(signal, name, None)
            if number is None:
                continue
            self._previous[number] = signal.getsignal(number)
            signal.signal(number, self._handle)
        return self

    def _handle(self, number: int, _frame: FrameType | None) -> None:
        reason = signal.Signals(number).name
        self.shutdown.request(reason)
        if self.callback is not None:
            self.callback(reason)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        for number, previous in self._previous.items():
            signal.signal(number, previous)
        self._previous.clear()
