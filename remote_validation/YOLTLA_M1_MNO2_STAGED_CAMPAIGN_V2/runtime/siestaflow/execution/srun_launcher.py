"""Explicit Srun and Hydra-SSH launchers for allocation-local job steps."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .resource_manager import ResourceReservation


@dataclass(frozen=True)
class StepLaunchSpec:
    task_id: str
    attempt_id: str
    workdir: Path
    input_path: Path
    stdout_path: Path
    stderr_path: Path
    mpi_processes: int
    cpus_per_process: int
    executable: str
    executable_arguments: tuple[str, ...] = ()
    environment: Mapping[str, str] | None = None
    reservation: ResourceReservation | None = None

    @property
    def allocated_cpus(self) -> int:
        return self.mpi_processes * self.cpus_per_process


@dataclass(frozen=True)
class StepOutcome:
    task_id: str
    attempt_id: str
    command: tuple[str, ...]
    exit_code: int
    elapsed_seconds: float
    terminated_by_controller: bool
    launcher_backend: str
    placement: Mapping[str, object]
    hostfile_sha256: str | None = None


@dataclass
class _ActiveProcess:
    process: subprocess.Popen[bytes]
    handles: tuple[object, ...]
    terminated: bool = False


class Launcher(Protocol):
    backend: str

    def build_command(self, spec: StepLaunchSpec) -> tuple[str, ...]: ...
    def launch(self, spec: StepLaunchSpec) -> StepOutcome: ...
    def terminate_all(self, *, kill: bool = False) -> tuple[str, ...]: ...


class _SubprocessLauncher:
    backend = "abstract"

    def __init__(self, *, popen_factory=subprocess.Popen) -> None:
        self._popen_factory = popen_factory
        self._active: dict[str, _ActiveProcess] = {}
        self._lock = threading.Lock()

    def build_command(self, spec: StepLaunchSpec) -> tuple[str, ...]:
        raise NotImplementedError

    def _hostfile(self, _spec: StepLaunchSpec) -> Path | None:
        return None

    def _environment(self, spec: StepLaunchSpec) -> dict[str, str]:
        env = os.environ.copy()
        if spec.environment:
            env.update({str(key): str(value) for key, value in spec.environment.items()})
        return env

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        if spec.reservation is None:
            raise ValueError("explicit resource reservation is required")
        if spec.reservation.mpi_processes != spec.mpi_processes:
            raise ValueError("reservation and MPI process count disagree")
        spec.workdir.mkdir(parents=True, exist_ok=True)
        command = self.build_command(spec)
        hostfile = self._hostfile(spec)
        hostfile_hash = (
            hashlib.sha256(hostfile.read_bytes()).hexdigest()
            if hostfile is not None
            else None
        )
        started = time.monotonic()
        stdin_handle = spec.input_path.open("rb")
        stdout_handle = spec.stdout_path.open("xb")
        stderr_handle = spec.stderr_path.open("xb")
        handles = (stdin_handle, stdout_handle, stderr_handle)
        try:
            process = self._popen_factory(
                list(command),
                cwd=spec.workdir,
                stdin=stdin_handle,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=self._environment(spec),
                start_new_session=True,
            )
        except TypeError:
            process = self._popen_factory(
                list(command),
                cwd=spec.workdir,
                stdin=stdin_handle,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=self._environment(spec),
            )
        except Exception:
            for handle in handles:
                handle.close()
            raise
        active = _ActiveProcess(process, handles)
        with self._lock:
            self._active[spec.attempt_id] = active
        try:
            exit_code = int(process.wait())
        finally:
            for handle in handles:
                handle.close()
            with self._lock:
                active = self._active.pop(spec.attempt_id, active)
        return StepOutcome(
            spec.task_id,
            spec.attempt_id,
            command,
            exit_code,
            max(0.0, time.monotonic() - started),
            active.terminated,
            self.backend,
            spec.reservation.as_dict(),
            hostfile_hash,
        )

    def terminate_all(self, *, kill: bool = False) -> tuple[str, ...]:
        with self._lock:
            items = tuple(self._active.items())
        affected: list[str] = []
        for attempt_id, active in items:
            if active.process.poll() is not None:
                continue
            active.terminated = True
            try:
                pid = int(getattr(active.process, "pid"))
                os.killpg(pid, signal.SIGKILL if kill else signal.SIGTERM)
            except (AttributeError, OSError, ProcessLookupError, TypeError, ValueError):
                try:
                    active.process.kill() if kill else active.process.terminate()
                except ProcessLookupError:
                    pass
            affected.append(attempt_id)
        return tuple(affected)

    @property
    def active_attempts(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))


class SrunLauncher(_SubprocessLauncher):
    backend = "srun"

    def __init__(
        self,
        *,
        srun_command: Sequence[str],
        srun_arguments: Sequence[str] = (),
        exclusive: bool = True,
        exact: bool = True,
        distribution: str = "block:block",
        cpu_bind: bool = True,
        popen_factory=subprocess.Popen,
    ) -> None:
        super().__init__(popen_factory=popen_factory)
        if not srun_command or any(not str(item) for item in srun_command):
            raise ValueError("srun_command must be non-empty")
        self.command = tuple(map(str, srun_command))
        self.arguments = tuple(map(str, srun_arguments))
        self.exclusive = bool(exclusive)
        self.exact = bool(exact)
        self.distribution = str(distribution)
        self.cpu_bind = bool(cpu_bind)

    def build_command(self, spec: StepLaunchSpec) -> tuple[str, ...]:
        reservation = spec.reservation
        if reservation is None:
            raise ValueError("srun requires explicit placement")
        ranges = reservation.ranges
        counts = {item.count for item in ranges}
        if len(counts) != 1:
            raise ValueError("srun placement must be balanced across nodes")
        command = [*self.command, *self.arguments]
        if self.exclusive and "--exclusive" not in command:
            command.append("--exclusive")
        if self.exact and "--exact" not in command:
            command.append("--exact")
        command.extend(
            (
                f"--nodes={len(ranges)}",
                f"--ntasks={spec.mpi_processes}",
                f"--ntasks-per-node={ranges[0].count}",
                f"--cpus-per-task={spec.cpus_per_process}",
                f"--nodelist={','.join(item.host for item in ranges)}",
                f"--distribution={self.distribution}",
            )
        )
        if self.cpu_bind:
            first = ranges[0]
            if any((item.first, item.last) != (first.first, first.last) for item in ranges):
                raise ValueError("srun cpu map must be identical on each selected node")
            cpu_list = ",".join(str(index) for index in range(first.first, first.last + 1))
            command.append(f"--cpu-bind=map_cpu:{cpu_list}")
        command.extend((spec.executable, *spec.executable_arguments))
        return tuple(command)


class HydraSshLauncher(_SubprocessLauncher):
    backend = "hydra_ssh"

    def __init__(
        self,
        *,
        hydra_command: Sequence[str],
        hydra_arguments: Sequence[str] = (),
        bootstrap: str = "ssh",
        affinity_environment_key: str = "I_MPI_PIN_PROCESSOR_LIST",
        popen_factory=subprocess.Popen,
    ) -> None:
        super().__init__(popen_factory=popen_factory)
        if not hydra_command or any(not str(item) for item in hydra_command):
            raise ValueError("hydra_command must be non-empty")
        if str(bootstrap).lower() != "ssh":
            raise ValueError("Hydra backend must use bootstrap ssh")
        arguments = tuple(map(str, hydra_arguments))
        joined = " ".join(arguments).lower()
        if "bootstrap slurm" in joined or "-bootstrap=slurm" in joined:
            raise ValueError("Hydra bootstrap slurm is forbidden")
        self.command = tuple(map(str, hydra_command))
        self.arguments = arguments
        self.bootstrap = "ssh"
        self.affinity_environment_key = str(affinity_environment_key)

    def _hostfile(self, spec: StepLaunchSpec) -> Path:
        reservation = spec.reservation
        if reservation is None:
            raise ValueError("Hydra requires explicit placement")
        path = spec.workdir / f"{spec.attempt_id}.hydra.hosts"
        content = "".join(f"{item.host}:{item.count}\n" for item in reservation.ranges)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def _environment(self, spec: StepLaunchSpec) -> dict[str, str]:
        env = super()._environment(spec)
        reservation = spec.reservation
        if reservation is None:
            raise ValueError("Hydra requires explicit placement")
        first = reservation.ranges[0]
        if any((item.first, item.last) != (first.first, first.last) for item in reservation.ranges):
            raise ValueError("Hydra affinity range must match on selected nodes")
        env[self.affinity_environment_key] = (
            f"{first.first}-{first.last}" if first.first != first.last else str(first.first)
        )
        return env

    def build_command(self, spec: StepLaunchSpec) -> tuple[str, ...]:
        reservation = spec.reservation
        if reservation is None:
            raise ValueError("Hydra requires explicit placement")
        counts = {item.count for item in reservation.ranges}
        if len(counts) != 1:
            raise ValueError("Hydra placement must be balanced across nodes")
        hostfile = self._hostfile(spec)
        return (
            *self.command,
            "-bootstrap",
            "ssh",
            *self.arguments,
            "-f",
            str(hostfile),
            "-n",
            str(spec.mpi_processes),
            "-ppn",
            str(reservation.ranges[0].count),
            spec.executable,
            *spec.executable_arguments,
        )


def launcher_from_config(config: Mapping[str, object], *, popen_factory=subprocess.Popen) -> Launcher:
    backend = str(config.get("backend") or "")
    command = config.get("command")
    arguments = config.get("arguments", [])
    if not isinstance(command, list) or not isinstance(arguments, list):
        raise ValueError("launcher command and arguments must be lists")
    if backend == "srun":
        return SrunLauncher(
            srun_command=command,
            srun_arguments=arguments,
            exclusive=bool(config.get("exclusive", True)),
            exact=bool(config.get("exact", True)),
            distribution=str(config.get("distribution", "block:block")),
            cpu_bind=bool(config.get("cpu_bind", True)),
            popen_factory=popen_factory,
        )
    if backend == "hydra_ssh":
        return HydraSshLauncher(
            hydra_command=command,
            hydra_arguments=arguments,
            bootstrap=str(config.get("bootstrap", "")),
            affinity_environment_key=str(
                config.get("affinity_environment_key", "I_MPI_PIN_PROCESSOR_LIST")
            ),
            popen_factory=popen_factory,
        )
    raise ValueError(f"unsupported launcher backend: {backend}")


__all__ = [
    "HydraSshLauncher",
    "Launcher",
    "SrunLauncher",
    "StepLaunchSpec",
    "StepOutcome",
    "launcher_from_config",
]
