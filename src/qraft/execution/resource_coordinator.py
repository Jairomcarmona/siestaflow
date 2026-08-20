"""Generic allocation capacity and resource leasing for the DAG runtime.

This module is deliberately unaware of scientific engines and schedulers.  An
infrastructure adapter supplies allocation capacity, hosts and remaining time;
the canonical runtime asks for and releases leases around immutable attempts.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol


def _unlimited_time() -> float:
    return math.inf


class ShutdownControl(Protocol):
    """Infrastructure-owned cooperative stop signal consumed by the runtime."""

    @property
    def requested(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...

    @property
    def elapsed_seconds(self) -> float: ...

    def request(self, reason: str) -> None: ...


class CooperativeShutdown:
    """Thread-safe first-reason-wins shutdown control for local composition."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None
        self._requested_at: float | None = None

    def request(self, reason: str) -> None:
        with self._lock:
            if self._reason is None:
                self._reason = str(reason)
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


@dataclass(frozen=True)
class RuntimeAllocation:
    """Generic capacity visible to one invocation of the canonical runtime."""

    total_cpus: int
    total_nodes: int
    max_parallel_steps: int = 1
    hosts: tuple[str, ...] = ()
    shutdown_margin_seconds: float = 0.0
    termination_grace_seconds: float = 0.0
    allocation_id: str = "local"
    remaining_time: Callable[[], float] = field(
        default=_unlimited_time, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for name in ("total_cpus", "total_nodes", "max_parallel_steps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.shutdown_margin_seconds < 0 or self.termination_grace_seconds < 0:
            raise ValueError("shutdown and termination margins cannot be negative")
        normalized_hosts = tuple(str(item).strip() for item in self.hosts)
        if any(not item for item in normalized_hosts):
            raise ValueError("allocation hosts must be non-empty")
        if len(set(normalized_hosts)) != len(normalized_hosts):
            raise ValueError("allocation hosts must be unique")
        if normalized_hosts and len(normalized_hosts) != self.total_nodes:
            raise ValueError("allocation hosts must cover total_nodes exactly")
        if not str(self.allocation_id).strip():
            raise ValueError("allocation_id must be non-empty")
        if not callable(self.remaining_time):
            raise TypeError("remaining_time must be callable")
        object.__setattr__(self, "hosts", normalized_hosts)

    def remaining_seconds(self) -> float:
        return max(0.0, float(self.remaining_time()))


@dataclass(frozen=True)
class ResourceRequest:
    task_id: str
    cpus: int
    nodes: int
    exclusive_hosts: bool = False

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("resource request requires task_id")
        for name in ("cpus", "nodes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"resource request {name} must be positive")


@dataclass(frozen=True)
class ResourceLease:
    task_id: str
    cpus: int
    nodes: int
    hosts: tuple[str, ...] = ()


class ResourceCoordinator:
    """Deterministic, thread-safe capacity arbiter reused from the HPC policy."""

    def __init__(self, allocation: RuntimeAllocation) -> None:
        self.allocation = allocation
        self._used_cpus = 0
        self._used_nodes = 0
        self._used_hosts: set[str] = set()
        self._leases: dict[str, ResourceLease] = {}
        self._lock = threading.Lock()
        self._peak_cpus = 0
        self._peak_nodes = 0
        self._peak_steps = 0

    def can_ever_fit(self, request: ResourceRequest) -> bool:
        if request.cpus > self.allocation.total_cpus:
            return False
        if request.nodes > self.allocation.total_nodes:
            return False
        if request.exclusive_hosts and len(self.allocation.hosts) < request.nodes:
            return False
        return True

    def try_acquire(self, request: ResourceRequest) -> ResourceLease | None:
        """Return a lease when capacity fits; temporary pressure returns ``None``."""

        with self._lock:
            if request.task_id in self._leases:
                raise RuntimeError(f"duplicate resource lease: {request.task_id}")
            if len(self._leases) >= self.allocation.max_parallel_steps:
                return None
            if request.cpus > self.allocation.total_cpus - self._used_cpus:
                return None
            if request.nodes > self.allocation.total_nodes - self._used_nodes:
                return None
            hosts: tuple[str, ...] = ()
            if request.exclusive_hosts:
                available = tuple(
                    host
                    for host in self.allocation.hosts
                    if host not in self._used_hosts
                )
                if len(available) < request.nodes:
                    return None
                hosts = available[: request.nodes]
            lease = ResourceLease(request.task_id, request.cpus, request.nodes, hosts)
            self._leases[request.task_id] = lease
            self._used_cpus += request.cpus
            self._used_nodes += request.nodes
            self._used_hosts.update(hosts)
            self._peak_cpus = max(self._peak_cpus, self._used_cpus)
            self._peak_nodes = max(self._peak_nodes, self._used_nodes)
            self._peak_steps = max(self._peak_steps, len(self._leases))
            return lease

    def release(self, lease: ResourceLease) -> None:
        with self._lock:
            current = self._leases.pop(lease.task_id, None)
            if current != lease:
                raise RuntimeError(f"unknown or mismatched resource lease: {lease.task_id}")
            self._used_cpus -= lease.cpus
            self._used_nodes -= lease.nodes
            self._used_hosts.difference_update(lease.hosts)

    @property
    def active_task_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._leases))

    @property
    def used_cpus(self) -> int:
        with self._lock:
            return self._used_cpus

    @property
    def used_nodes(self) -> int:
        with self._lock:
            return self._used_nodes

    @property
    def used_hosts(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._used_hosts))

    @property
    def peak_cpus(self) -> int:
        with self._lock:
            return self._peak_cpus

    @property
    def peak_nodes(self) -> int:
        with self._lock:
            return self._peak_nodes

    @property
    def peak_steps(self) -> int:
        with self._lock:
            return self._peak_steps

    def assert_released(self) -> None:
        with self._lock:
            if self._leases or self._used_cpus or self._used_nodes or self._used_hosts:
                raise RuntimeError("resource leases remain active after runtime completion")


def local_allocation(requests: Iterable[ResourceRequest]) -> RuntimeAllocation:
    """Sequential default for callers without an external allocation context."""

    values = tuple(requests)
    if not values:
        raise ValueError("at least one resource request is required")
    return RuntimeAllocation(
        total_cpus=max(item.cpus for item in values),
        total_nodes=max(item.nodes for item in values),
        max_parallel_steps=1,
    )
