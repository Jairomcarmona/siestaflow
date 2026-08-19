"""Engine-neutral execution request and evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .artifacts import (
    ArtifactReference,
    ArtifactTransfer,
    require_relative_artifact_path,
)
from .serialization import canonical_primitive
from .status import FailureType
from .versioning import ContractVersion


class LauncherKind(str, Enum):
    HYDRA = "HYDRA"
    SRUN = "SRUN"
    DIRECT = "DIRECT"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class ResourceRequest:
    nodes: int
    mpi_processes: int
    cpus_per_process: int
    processes_per_node: int
    walltime_seconds: int
    memory_per_node_mb: int | None
    launcher: LauncherKind
    exclusive: bool = True

    def __post_init__(self) -> None:
        for name in (
            "nodes",
            "mpi_processes",
            "cpus_per_process",
            "processes_per_node",
            "walltime_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.memory_per_node_mb is not None and self.memory_per_node_mb <= 0:
            raise ValueError("memory_per_node_mb must be positive when declared")
        if self.nodes * self.processes_per_node != self.mpi_processes:
            raise ValueError(
                "nodes * processes_per_node must equal mpi_processes"
            )

    @property
    def allocated_cpus(self) -> int:
        return self.mpi_processes * self.cpus_per_process


@dataclass(frozen=True)
class ExecutionRequest:
    task_id: str
    attempt_id: str
    engine: str
    executable: str
    arguments: tuple[str, ...]
    working_directory: str
    input_path: str
    stdout_path: str
    stderr_path: str
    resources: ResourceRequest
    dependencies: tuple[str, ...] = ()
    transfers: tuple[ArtifactTransfer, ...] = ()
    required_artifact_roles: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    contract_version: ContractVersion = ContractVersion(1, 0)

    def __post_init__(self) -> None:
        for name in ("task_id", "attempt_id", "engine", "executable"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must be non-empty")
        for name in (
            "working_directory",
            "input_path",
            "stdout_path",
            "stderr_path",
        ):
            object.__setattr__(
                self,
                name,
                require_relative_artifact_path(
                    str(getattr(self, name)), field_name=name
                ),
            )
        if self.task_id in self.dependencies:
            raise ValueError("an execution request cannot depend on itself")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("execution dependencies must be unique")
        canonical_primitive(self.environment)


@dataclass(frozen=True)
class ExecutionEvidence:
    task_id: str
    attempt_id: str
    command: tuple[str, ...]
    exit_code: int | None
    elapsed_seconds: float
    failure: FailureType
    terminated_by_controller: bool
    artifacts: tuple[ArtifactReference, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    contract_version: ContractVersion = ContractVersion(1, 0)

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.attempt_id.strip() or not self.command:
            raise ValueError("execution evidence requires task, attempt, and command")
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        canonical_primitive(self.metrics)

