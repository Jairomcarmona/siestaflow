"""Registries that keep scheduler and launcher policy outside QRAFT core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .direct_launcher import DirectLauncher
from .hydra_launcher import HydraLauncher
from .openmpi_launcher import OpenMpiLauncher
from .srun_launcher import SrunLauncher, StepLauncher


class LauncherAdapter(Protocol):
    name: str
    default_command: tuple[str, ...]
    scheduler: str
    requires_allocation: bool
    requires_hosts: bool
    requires_processes_per_node: bool
    max_mpi_ranks: int | None
    supports_controller_siesta: bool
    version_arguments: tuple[str, ...]
    probe_required: bool

    def create(
        self, *, command: Sequence[str] = (), arguments: Sequence[str] = (),
    ) -> StepLauncher: ...

    def validate_resources(self, *, mpi_ranks: int, nodes: int) -> None: ...

    def preview_command(
        self, *, command: Sequence[str], arguments: Sequence[str],
        executable: str, executable_arguments: Sequence[str],
        mpi_ranks: int, cpus_per_rank: int,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class RegisteredLauncher:
    name: str
    default_command: tuple[str, ...]
    factory: Callable[[tuple[str, ...], tuple[str, ...]], StepLauncher]
    scheduler: str = "local"
    requires_allocation: bool = False
    requires_hosts: bool = False
    requires_processes_per_node: bool = False
    max_mpi_ranks: int | None = None
    supports_controller_siesta: bool = True
    version_arguments: tuple[str, ...] = ("--version",)
    probe_required: bool = True
    preview_builder: Callable[
        [tuple[str, ...], tuple[str, ...], str, tuple[str, ...], int, int],
        tuple[str, ...],
    ] | None = None

    def create(
        self, *, command: Sequence[str] = (), arguments: Sequence[str] = (),
    ) -> StepLauncher:
        resolved = tuple(map(str, command)) or self.default_command
        return self.factory(resolved, tuple(map(str, arguments)))

    def validate_resources(self, *, mpi_ranks: int, nodes: int) -> None:
        if self.max_mpi_ranks is not None and mpi_ranks > self.max_mpi_ranks:
            raise ValueError(
                f"{self.name} launcher supports at most {self.max_mpi_ranks} MPI rank(s)"
            )

    def preview_command(
        self, *, command: Sequence[str] = (), arguments: Sequence[str] = (),
        executable: str, executable_arguments: Sequence[str] = (),
        mpi_ranks: int, cpus_per_rank: int,
    ) -> tuple[str, ...]:
        resolved = tuple(map(str, command)) or self.default_command
        values = (
            resolved, tuple(map(str, arguments)), str(executable),
            tuple(map(str, executable_arguments)), int(mpi_ranks), int(cpus_per_rank),
        )
        if self.preview_builder is not None:
            return self.preview_builder(*values)
        return (*resolved, *values[1], values[2], *values[3])


class LauncherRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, LauncherAdapter] = {}

    def register(self, adapter: LauncherAdapter, *, replace: bool = False) -> None:
        name = str(adapter.name).strip().casefold()
        if not name:
            raise ValueError("launcher adapter name must be non-empty")
        if name in self._adapters and not replace:
            raise ValueError(f"launcher adapter already registered: {name}")
        self._adapters[name] = adapter

    def require(self, name: str) -> LauncherAdapter:
        normalized = str(name).strip().casefold()
        try:
            return self._adapters[normalized]
        except KeyError as exc:
            available = ", ".join(self.names()) or "none"
            raise ValueError(
                f"unknown launcher adapter: {name}; available: {available}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


class SchedulerAdapter(Protocol):
    name: str
    command: tuple[str, ...]
    version_arguments: tuple[str, ...]
    environment_markers: tuple[str, ...]
    probe_required: bool

    def describe(self) -> str: ...


@dataclass(frozen=True)
class RegisteredScheduler:
    name: str
    description: str
    command: tuple[str, ...] = ()
    version_arguments: tuple[str, ...] = ("--version",)
    environment_markers: tuple[str, ...] = ()
    probe_required: bool = True

    def describe(self) -> str:
        return self.description


class SchedulerRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SchedulerAdapter] = {}

    def register(self, adapter: SchedulerAdapter, *, replace: bool = False) -> None:
        name = str(adapter.name).strip().casefold()
        if not name:
            raise ValueError("scheduler adapter name must be non-empty")
        if name in self._adapters and not replace:
            raise ValueError(f"scheduler adapter already registered: {name}")
        self._adapters[name] = adapter

    def require(self, name: str) -> SchedulerAdapter:
        normalized = str(name).strip().casefold()
        try:
            return self._adapters[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._adapters)) or "none"
            raise ValueError(
                f"unknown scheduler adapter: {name}; available: {available}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def _direct(command: tuple[str, ...], arguments: tuple[str, ...]) -> StepLauncher:
    return DirectLauncher()


def _srun(command: tuple[str, ...], arguments: tuple[str, ...]) -> StepLauncher:
    return SrunLauncher(srun_command=command, srun_arguments=arguments, exclusive=True)


def _hydra(command: tuple[str, ...], arguments: tuple[str, ...]) -> StepLauncher:
    return HydraLauncher(command=command, arguments=arguments)


def _openmpi(command: tuple[str, ...], arguments: tuple[str, ...]) -> StepLauncher:
    return OpenMpiLauncher(command=command, arguments=arguments)


def _preview_srun(
    command: tuple[str, ...], arguments: tuple[str, ...], executable: str,
    executable_arguments: tuple[str, ...], mpi_ranks: int, cpus_per_rank: int,
) -> tuple[str, ...]:
    return (
        *command, *arguments, f"--ntasks={mpi_ranks}",
        f"--cpus-per-task={cpus_per_rank}", executable, *executable_arguments,
    )


def _preview_mpi_np(
    command: tuple[str, ...], arguments: tuple[str, ...], executable: str,
    executable_arguments: tuple[str, ...], mpi_ranks: int, cpus_per_rank: int,
) -> tuple[str, ...]:
    return (*command, *arguments, "-np", str(mpi_ranks), executable, *executable_arguments)


launcher_registry = LauncherRegistry()
launcher_registry.register(RegisteredLauncher(
    "direct", (), _direct, max_mpi_ranks=1, supports_controller_siesta=False,
    version_arguments=(), probe_required=False,
))
launcher_registry.register(RegisteredLauncher(
    "srun", ("srun",), _srun, scheduler="slurm", requires_allocation=True,
    preview_builder=_preview_srun
))
launcher_registry.register(RegisteredLauncher(
    "hydra", ("mpiexec.hydra",), _hydra, scheduler="slurm",
    requires_allocation=True, requires_hosts=True, requires_processes_per_node=True,
    preview_builder=_preview_mpi_np,
))
launcher_registry.register(RegisteredLauncher(
    "openmpi", ("mpirun",), _openmpi, preview_builder=_preview_mpi_np
))

scheduler_registry = SchedulerRegistry()
scheduler_registry.register(RegisteredScheduler(
    "local", "local process environment", probe_required=False,
))
scheduler_registry.register(RegisteredScheduler(
    "slurm", "SLURM allocation and batch scheduler", command=("sbatch",),
    environment_markers=("SLURM_JOB_ID", "SLURM_JOB_NODELIST"),
))
