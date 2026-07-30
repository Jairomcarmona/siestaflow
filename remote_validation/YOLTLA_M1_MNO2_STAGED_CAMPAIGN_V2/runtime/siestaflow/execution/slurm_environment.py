"""Read-only allocation identity, capacity, hosts and walltime source."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import FrameType
from typing import Callable, Mapping

from .time_utils import parse_slurm_walltime


def _positive_int(value: str | None, name: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"missing or invalid SLURM value: {name}") from exc
    if parsed <= 0:
        raise ValueError(f"SLURM value must be positive: {name}")
    return parsed


def _expand_hosts(env: Mapping[str, str], runner=subprocess.run) -> tuple[str, ...]:
    explicit = str(env.get("SIESTAFLOW_ALLOCATED_HOSTS", "")).strip()
    if explicit:
        hosts = tuple(item.strip() for item in explicit.split(",") if item.strip())
    else:
        nodelist = str(env.get("SLURM_JOB_NODELIST", "")).strip()
        if not nodelist:
            raise ValueError("SLURM_JOB_NODELIST is required")
        result = runner(
            ["scontrol", "show", "hostnames", nodelist],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(f"cannot expand SLURM_JOB_NODELIST: {result.stderr.strip()}")
        hosts = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    if not hosts or len(hosts) != len(set(hosts)):
        raise ValueError("allocated host expansion is empty or contains duplicates")
    return hosts


def _end_time(
    env: Mapping[str, str],
    *,
    now: float,
    configured_walltime: str | None,
    runner=subprocess.run,
) -> tuple[float, str]:
    raw = str(env.get("SLURM_JOB_END_TIME", "")).strip()
    if raw:
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("SLURM_JOB_END_TIME must be a Unix timestamp") from exc
        if value <= now:
            raise ValueError("SLURM_JOB_END_TIME is not in the future")
        return value, "SLURM_JOB_END_TIME"

    start_raw = str(env.get("SLURM_JOB_START_TIME", "")).strip()
    limit_raw = str(env.get("SLURM_TIMELIMIT", "")).strip() or configured_walltime
    if start_raw and limit_raw:
        try:
            start = float(start_raw)
        except ValueError as exc:
            raise ValueError("SLURM_JOB_START_TIME must be a Unix timestamp") from exc
        return start + parse_slurm_walltime(limit_raw), "SLURM_JOB_START_TIME+TIMELIMIT"

    job_id = str(env.get("SLURM_JOB_ID", "")).strip()
    result = runner(
        ["scontrol", "show", "job", "-o", job_id],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        fields = dict(
            token.split("=", 1)
            for token in result.stdout.split()
            if "=" in token
        )
        end_text = fields.get("EndTime")
        if end_text and end_text not in {"Unknown", "N/A"}:
            try:
                parsed = datetime.fromisoformat(end_text).timestamp()
            except ValueError:
                parsed = 0.0
            if parsed > now:
                return parsed, "SCONTROL_END_TIME"

    if configured_walltime:
        # Conservative: controller starts after allocation start, so this fallback
        # subtracts 60 seconds rather than assuming the full configured limit.
        return (
            now + max(1, parse_slurm_walltime(configured_walltime) - 60),
            "CONFIGURED_WALLTIME_CONSERVATIVE_FALLBACK",
        )
    raise ValueError("cannot determine allocation end time safely")


@dataclass(frozen=True)
class SlurmEnvironment:
    job_id: str
    submit_dir: Path
    end_time_epoch: float
    end_time_source: str
    total_cpus: int
    nodes: int
    ntasks: int
    cpus_per_task: int
    tasks_per_node: int
    hosts: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str] | None = None,
        *,
        configured_walltime: str | None = None,
        runner=subprocess.run,
        now: float | None = None,
    ) -> "SlurmEnvironment":
        env = os.environ if values is None else values
        current = time.time() if now is None else float(now)
        job_id = str(env.get("SLURM_JOB_ID", "")).strip()
        if not job_id:
            raise ValueError("SLURM_JOB_ID is required inside campaign worker")
        submit_raw = str(env.get("SLURM_SUBMIT_DIR", "")).strip()
        if not submit_raw:
            raise ValueError("SLURM_SUBMIT_DIR is required inside campaign worker")
        submit_dir = Path(submit_raw).resolve()
        if not submit_dir.is_dir():
            raise ValueError(f"SLURM_SUBMIT_DIR does not exist: {submit_dir}")
        nodes = _positive_int(env.get("SLURM_NNODES"), "SLURM_NNODES")
        ntasks = _positive_int(env.get("SLURM_NTASKS"), "SLURM_NTASKS")
        cpus_per_task = _positive_int(
            env.get("SLURM_CPUS_PER_TASK", "1"), "SLURM_CPUS_PER_TASK"
        )
        tasks_per_node = _positive_int(
            env.get("SLURM_NTASKS_PER_NODE"), "SLURM_NTASKS_PER_NODE"
        )
        hosts = _expand_hosts(env, runner)
        if len(hosts) != nodes:
            raise ValueError(f"allocated host count mismatch: {len(hosts)} != {nodes}")
        if ntasks != nodes * tasks_per_node:
            raise ValueError("SLURM_NTASKS must equal nodes * tasks_per_node")
        end_epoch, source = _end_time(
            env,
            now=current,
            configured_walltime=configured_walltime,
            runner=runner,
        )
        return cls(
            job_id,
            submit_dir,
            end_epoch,
            source,
            ntasks * cpus_per_task,
            nodes,
            ntasks,
            cpus_per_task,
            tasks_per_node,
            hosts,
        )

    def remaining_seconds(self, *, now: float | None = None) -> float:
        current = time.time() if now is None else float(now)
        return max(0.0, self.end_time_epoch - current)

    def validate_capacity(
        self, *, nodes: int, total_cpus: int, tasks_per_node: int
    ) -> None:
        if nodes != self.nodes:
            raise ValueError(f"configured nodes differ from allocation: {nodes}!={self.nodes}")
        if total_cpus != self.total_cpus:
            raise ValueError(
                f"configured CPUs differ from allocation: {total_cpus}!={self.total_cpus}"
            )
        if tasks_per_node != self.tasks_per_node:
            raise ValueError(
                "configured tasks_per_node differs from allocation: "
                f"{tasks_per_node}!={self.tasks_per_node}"
            )


class ShutdownRequest:
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
    def __init__(
        self,
        shutdown: ShutdownRequest,
        callback: Callable[[str], None] | None = None,
    ) -> None:
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


__all__ = ["ShutdownRequest", "SignalHandlers", "SlurmEnvironment"]

