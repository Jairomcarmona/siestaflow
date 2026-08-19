"""Bounded non-MPI launcher for hash-bound controller-side gate tasks."""

from __future__ import annotations

import os
import subprocess
import threading
import time

from .srun_launcher import StepLaunchSpec, StepOutcome, _ActiveProcess


class DirectLauncher:
    """Run a small gate/evaluator command directly inside the allocation."""

    def __init__(self, *, popen_factory=subprocess.Popen) -> None:
        self._popen_factory = popen_factory
        self._active: dict[str, _ActiveProcess] = {}
        self._lock = threading.Lock()

    def build_command(self, spec: StepLaunchSpec) -> tuple[str, ...]:
        if not spec.executable:
            raise ValueError("direct task executable is required")
        return (spec.executable, *spec.executable_arguments)

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        command = self.build_command(spec)
        spec.workdir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        stdout_handle = spec.stdout_path.open("xb")
        stderr_handle = spec.stderr_path.open("xb")
        env = os.environ.copy()
        if spec.environment:
            env.update({str(key): str(value) for key, value in spec.environment.items()})
        try:
            process = self._popen_factory(
                list(command),
                cwd=spec.workdir,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=env,
            )
        except Exception:
            stdout_handle.close()
            stderr_handle.close()
            raise
        active = _ActiveProcess(
            process, subprocess.DEVNULL, stdout_handle, stderr_handle
        )
        with self._lock:
            self._active[spec.attempt_id] = active
        try:
            exit_code = int(process.wait())
        finally:
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
