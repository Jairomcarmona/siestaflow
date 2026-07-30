"""Subprocess launcher for scientific ``srun`` job steps."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


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


@dataclass
class _ActiveProcess:
    process: subprocess.Popen[bytes]
    stdin_handle: object
    stdout_handle: object
    stderr_handle: object
    terminated: bool = False


class SrunLauncher:
    """Launch SIESTA through an explicit, externally configured srun command."""

    def __init__(
        self,
        *,
        srun_command: Sequence[str],
        srun_arguments: Sequence[str] = (),
        exclusive: bool = True,
        popen_factory=subprocess.Popen,
    ) -> None:
        if not srun_command or any(not str(item) for item in srun_command):
            raise ValueError("srun_command must contain at least one non-empty argument")
        self.srun_command = tuple(map(str, srun_command))
        self.srun_arguments = tuple(map(str, srun_arguments))
        self.exclusive = bool(exclusive)
        self._popen_factory = popen_factory
        self._active: dict[str, _ActiveProcess] = {}
        self._lock = threading.Lock()

    def build_command(self, spec: StepLaunchSpec) -> tuple[str, ...]:
        if spec.mpi_processes <= 0 or spec.cpus_per_process <= 0:
            raise ValueError("MPI processes and CPUs per process must be positive")
        command = [*self.srun_command, *self.srun_arguments]
        if self.exclusive and "--exclusive" not in command:
            command.append("--exclusive")
        command.extend((f"--ntasks={spec.mpi_processes}", f"--cpus-per-task={spec.cpus_per_process}"))
        command.extend((spec.executable, *spec.executable_arguments))
        return tuple(command)

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        command = self.build_command(spec)
        spec.workdir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        stdin_handle = spec.input_path.open("rb")
        stdout_handle = spec.stdout_path.open("xb")
        stderr_handle = spec.stderr_path.open("xb")
        env = os.environ.copy()
        if spec.environment:
            env.update({str(key): str(value) for key, value in spec.environment.items()})
        try:
            process = self._popen_factory(
                list(command), cwd=spec.workdir, stdin=stdin_handle,
                stdout=stdout_handle, stderr=stderr_handle, env=env,
            )
        except Exception:
            stdin_handle.close()
            stdout_handle.close()
            stderr_handle.close()
            raise
        active = _ActiveProcess(process, stdin_handle, stdout_handle, stderr_handle)
        with self._lock:
            self._active[spec.attempt_id] = active
        try:
            exit_code = int(process.wait())
        finally:
            stdin_handle.close()
            stdout_handle.close()
            stderr_handle.close()
            with self._lock:
                active = self._active.pop(spec.attempt_id, active)
        return StepOutcome(
            spec.task_id, spec.attempt_id, command, exit_code,
            max(0.0, time.monotonic() - started), active.terminated,
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
                active.process.kill() if kill else active.process.terminate()
            except ProcessLookupError:
                pass
            affected.append(attempt_id)
        return tuple(affected)

    @property
    def active_attempts(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))
