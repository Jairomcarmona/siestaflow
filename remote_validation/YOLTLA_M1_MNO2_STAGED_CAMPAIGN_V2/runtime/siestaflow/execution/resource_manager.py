"""Allocation-local, node-aware reservation of MPI process slots."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class SlotRange:
    host: str
    first: int
    last: int

    @property
    def count(self) -> int:
        return self.last - self.first + 1


@dataclass(frozen=True)
class ResourceReservation:
    task_id: str
    ranges: tuple[SlotRange, ...]

    @property
    def hosts(self) -> tuple[str, ...]:
        return tuple(item.host for item in self.ranges)

    @property
    def mpi_processes(self) -> int:
        return sum(item.count for item in self.ranges)

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "mpi_processes": self.mpi_processes,
            "hosts": list(self.hosts),
            "slot_ranges": [
                {"host": item.host, "first": item.first, "last": item.last}
                for item in self.ranges
            ],
        }


class ResourceManager:
    """Reserve contiguous, non-overlapping slots on allocated nodes."""

    def __init__(self, hosts: tuple[str, ...], slots_per_node: int) -> None:
        if not hosts or len(hosts) != len(set(hosts)):
            raise ValueError("allocated hosts must be unique and non-empty")
        if slots_per_node <= 0:
            raise ValueError("slots_per_node must be positive")
        self.hosts = tuple(hosts)
        self.slots_per_node = int(slots_per_node)
        self._owners: dict[str, list[str | None]] = {
            host: [None] * self.slots_per_node for host in self.hosts
        }
        self._reservations: dict[str, ResourceReservation] = {}
        self._lock = threading.Lock()

    def _free_runs(self, host: str) -> list[tuple[int, int]]:
        slots = self._owners[host]
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for index, owner in enumerate((*slots, "SENTINEL")):
            if owner is None and start is None:
                start = index
            elif owner is not None and start is not None:
                runs.append((start, index - 1))
                start = None
        return runs

    def reserve(
        self,
        task_id: str,
        mpi_processes: int,
        nodes_required: int,
    ) -> ResourceReservation | None:
        if not task_id or mpi_processes <= 0 or nodes_required <= 0:
            raise ValueError("invalid reservation request")
        if nodes_required > len(self.hosts):
            raise ValueError("nodes_required exceeds allocation")
        if mpi_processes > nodes_required * self.slots_per_node:
            raise ValueError("MPI request exceeds requested node slots")
        if mpi_processes % nodes_required:
            raise ValueError("MPI processes must divide evenly across requested nodes")
        per_node = mpi_processes // nodes_required
        if per_node > self.slots_per_node:
            raise ValueError("per-node MPI request exceeds slot capacity")
        with self._lock:
            if task_id in self._reservations:
                raise ValueError(f"duplicate active task reservation: {task_id}")
            chosen: list[SlotRange] = []
            for host in self.hosts:
                matching = [
                    (first, last)
                    for first, last in self._free_runs(host)
                    if last - first + 1 >= per_node
                ]
                if matching:
                    first, _ = matching[0]
                    chosen.append(SlotRange(host, first, first + per_node - 1))
                    if len(chosen) == nodes_required:
                        break
            if len(chosen) != nodes_required:
                return None
            reservation = ResourceReservation(task_id, tuple(chosen))
            for item in chosen:
                for slot in range(item.first, item.last + 1):
                    if self._owners[item.host][slot] is not None:
                        raise RuntimeError("internal resource overlap")
                    self._owners[item.host][slot] = task_id
            self._reservations[task_id] = reservation
            return reservation

    def release(self, task_id: str) -> ResourceReservation:
        with self._lock:
            reservation = self._reservations.pop(task_id)
            for item in reservation.ranges:
                for slot in range(item.first, item.last + 1):
                    if self._owners[item.host][slot] != task_id:
                        raise RuntimeError("resource ownership corruption")
                    self._owners[item.host][slot] = None
            return reservation

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "hosts": list(self.hosts),
                "slots_per_node": self.slots_per_node,
                "active": {
                    key: value.as_dict()
                    for key, value in sorted(self._reservations.items())
                },
                "owners": {host: list(slots) for host, slots in self._owners.items()},
            }


__all__ = ["ResourceManager", "ResourceReservation", "SlotRange"]

