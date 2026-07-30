"""Intel MPI Hydra launcher used by the validated Yoltla runtime."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Sequence

from .srun_launcher import StepLaunchSpec, StepOutcome


@dataclass
class _ActiveProcess:
    process: subprocess.Popen[bytes]
    stdin_handle: object
    stdout_handle: object
    stderr_handle: object
    terminated: bool = False


class HydraLauncher:
    """Launch one SIESTA step through ``mpiexec.hydra -bootstrap ssh``."""

    def __init__(
        self,
        *,
        command: Sequence[str] = ("mpiexec.hydra",),
        arguments: Sequence[str] = (),
        bootstrap: str = "ssh",
        fabric_uuid_environment: str = "FI_PSM3_UUID",
        popen_factory=subprocess.Popen,
    ) -> None:
        if not command or any(not str(item) for item in command):
            raise ValueError("Hydra command must contain non-empty arguments")
        if not bootstrap:
            raise ValueError("Hydra bootstrap must be explicit")
        self.command = tuple(map(str, command))
        self.arguments = tuple(map(str, arguments))
        self.bootstrap = str(bootstrap)
        self.fabric_uuid_environment = str(fabric_uuid_environment)
        self._popen_factory = popen_factory
        self._active: dict[str, _ActiveProcess] = {}
        self._lock = threading.Lock()

    def build_command(self, spec: StepLaunchSpec, *, fabric_uuid: str | None = None) -> tuple[str, ...]:
        if spec.mpi_processes <= 0 or spec.cpus_per_process <= 0:
            raise ValueError("MPI processes and CPUs per process must be positive")
        if not spec.hosts:
            raise ValueError("Hydra requires an explicit non-empty host allocation")
        ppn = spec.processes_per_node
        if ppn is None or ppn <= 0:
            raise ValueError("Hydra requires a positive processes_per_node")
        if spec.mpi_processes != len(spec.hosts) * ppn:
            raise ValueError(
                "Hydra placement mismatch: "
                f"{spec.mpi_processes} ranks != {len(spec.hosts)} hosts * {ppn} ppn"
            )
        token = fabric_uuid or str(uuid.uuid4())
        return (
            *self.command,
            "-bootstrap",
            self.bootstrap,
            "-hosts",
            ",".join(spec.hosts),
            "-np",
            str(spec.mpi_processes),
            "-ppn",
            str(ppn),
            "-genv",
            self.fabric_uuid_environment,
            token,
            *self.arguments,
            spec.executable,
            *spec.executable_arguments,
        )

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
                list(command),
                cwd=spec.workdir,
                stdin=stdin_handle,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=env,
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
            spec.task_id,
            spec.attempt_id,
            command,
            exit_code,
            max(0.0, time.monotonic() - started),
            active.terminated,
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
