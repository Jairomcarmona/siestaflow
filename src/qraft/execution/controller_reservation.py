"""ADR-017 reservation value, independent of controller execution/recovery.

This type does not grant a lease, attest scheduler capacity or enable a launcher.
The allocation supplied by the caller remains the source of capacity; physical
host capacity and inner MPI ranks are never used as substitutes.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Mapping

from .resource_coordinator import ResourceRequest, RuntimeAllocation


@dataclass(frozen=True)
class ControllerReservation:
    """The five reservation fields in ADR-017 Adenda 1, without coercion."""

    nodes: int
    inner_launcher: str
    inner_processes_per_node: int
    inner_cpus_per_process: int
    max_concurrent_inner_launches: int

    def __post_init__(self) -> None:
        for name in (
            "nodes", "inner_processes_per_node",
            "inner_cpus_per_process", "max_concurrent_inner_launches",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"controller reservation {name} must be a positive integer")
        if self.inner_launcher not in ("hydra", "openmpi"):
            raise ValueError("controller inner_launcher must be hydra or openmpi")
        if self.nodes != 1:
            raise ValueError("CONTROLLER_CONTAINMENT_UNAVAILABLE: v1 requires one host")
        if self.inner_cpus_per_process != 1:
            raise ValueError("controller inner_cpus_per_process must be 1")

    @property
    def min_cpus(self) -> int:
        return (self.inner_processes_per_node * self.inner_cpus_per_process
                * self.max_concurrent_inner_launches)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ControllerReservation:
        names = {item.name for item in fields(cls)}
        if not isinstance(value, Mapping) or set(value) != names:
            raise ValueError("controller reservation fields are missing or unknown")
        return cls(**value)

    def to_mapping(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}

    def resource_request(
        self, task_id: str, allocation: RuntimeAllocation,
    ) -> ResourceRequest:
        """Validate allocation arithmetic and build an ungranted native request.

        This deliberately does not infer allocation authority or process
        containment. Those admission/recovery gates require the ADR resolution.
        """
        if allocation.total_cpus % allocation.total_nodes:
            raise ValueError("controller allocation must have integral CPUs per node")
        runtime_cpus = allocation.total_cpus // allocation.total_nodes
        if self.min_cpus > runtime_cpus:
            raise ValueError("CONTROLLER_ALLOCATION_INSUFFICIENT")
        if len(allocation.hosts) != allocation.total_nodes:
            raise ValueError("controller reservation requires explicit allocation hosts")
        return ResourceRequest(task_id, runtime_cpus, self.nodes, exclusive_hosts=True)
