"""Read-only view of the SLURM allocation and cooperative shutdown signals."""

from __future__ import annotations

import os
import re
import signal
import subprocess
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


def parse_slurm_tasks_per_node(value: str) -> tuple[int, ...]:
    """Expand Slurm counts such as ``20(x4),16,8(x2)`` exactly."""

    text = str(value).strip()
    if not text:
        raise ValueError("missing or invalid SLURM value: SLURM_TASKS_PER_NODE")
    expanded: list[int] = []
    for raw in text.split(","):
        token = raw.strip()
        match = re.fullmatch(r"([1-9][0-9]*)(?:\(x([1-9][0-9]*)\))?", token, re.I)
        if match is None:
            raise ValueError(
                "missing or invalid SLURM value: SLURM_TASKS_PER_NODE"
            )
        tasks = int(match.group(1))
        repeat = int(match.group(2) or 1)
        expanded.extend([tasks] * repeat)
    return tuple(expanded)


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
    tasks_per_node: tuple[int, ...] = ()
    node_list_expression: str | None = None
    declared_hostnames: tuple[str, ...] = ()

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
        tasks_per_node_raw = str(env.get("SLURM_TASKS_PER_NODE", "")).strip()
        tasks_per_node = (
            parse_slurm_tasks_per_node(tasks_per_node_raw)
            if tasks_per_node_raw
            else ()
        )
        node_list = str(env.get("SLURM_JOB_NODELIST", "")).strip() or None
        explicit_hosts = tuple(
            item.strip()
            for item in str(env.get("QRAFT_HOSTS", "")).split(",")
            if item.strip()
        )
        if explicit_hosts and (len(explicit_hosts) != nodes or len(set(explicit_hosts)) != nodes):
            raise ValueError(
                "QRAFT_HOSTS must declare exactly one unique hostname per allocated node"
            )
        return cls(
            job_id, submit_dir, end_time, total_cpus, nodes, ntasks,
            cpus_per_task, tasks_per_node, node_list, explicit_hosts,
        )

    def remaining_seconds(self, *, now: float | None = None) -> float:
        current = time.time() if now is None else float(now)
        return max(0.0, self.end_time_epoch - current)

    def validate_capacity(self, *, nodes: int, total_cpus: int) -> None:
        if nodes > self.nodes:
            raise ValueError(f"configured nodes exceed allocation: {nodes}>{self.nodes}")
        if total_cpus > self.total_cpus:
            raise ValueError(f"configured CPUs exceed allocation: {total_cpus}>{self.total_cpus}")

    def validate_exact_placement(
        self,
        *,
        nodes: int,
        ntasks: int,
        cpus_per_task: int,
        tasks_per_node: int,
        hosts: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        """Validate the granted allocation exactly before any engine launch."""

        resolved_hosts = self.resolve_hostnames() if hosts is None else tuple(hosts)
        expected_distribution = tuple([int(tasks_per_node)] * int(nodes))
        mismatches: list[str] = []
        if self.nodes != nodes:
            mismatches.append(f"nodes expected={nodes} actual={self.nodes}")
        if self.ntasks != ntasks:
            mismatches.append(f"ntasks expected={ntasks} actual={self.ntasks}")
        if self.cpus_per_task != cpus_per_task:
            mismatches.append(
                "cpus_per_task "
                f"expected={cpus_per_task} actual={self.cpus_per_task}"
            )
        if self.tasks_per_node != expected_distribution:
            mismatches.append(
                "tasks_per_node "
                f"expected={expected_distribution} actual={self.tasks_per_node}"
            )
        if len(resolved_hosts) != nodes or len(set(resolved_hosts)) != nodes:
            mismatches.append(
                f"hosts expected={nodes} actual={len(set(resolved_hosts))}"
            )
        if mismatches:
            raise ValueError(
                "ALLOCATION_PLACEMENT_MISMATCH: " + "; ".join(mismatches)
            )
        return resolved_hosts

    def resolve_hostnames(
        self,
        *,
        command: tuple[str, ...] = ("scontrol", "show", "hostnames"),
        timeout_seconds: float = 30.0,
    ) -> tuple[str, ...]:
        """Return the exact allocated hosts, failing closed on ambiguity."""
        if self.declared_hostnames:
            return self.declared_hostnames
        if not self.node_list_expression:
            raise ValueError(
                "SLURM_JOB_NODELIST or explicit QRAFT_HOSTS is required "
                "for a host-aware launcher"
            )
        result = subprocess.run(
            [*command, self.node_list_expression],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        hosts = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
        if result.returncode != 0:
            raise ValueError(
                f"allocated host resolution failed with exit {result.returncode}: "
                f"{result.stderr.strip()}"
            )
        if len(hosts) != self.nodes or len(set(hosts)) != self.nodes:
            raise ValueError(
                f"allocated host resolution mismatch: expected {self.nodes}, got {hosts}"
            )
        return hosts


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
