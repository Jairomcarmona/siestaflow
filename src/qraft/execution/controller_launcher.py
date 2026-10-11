"""Direct controller launch under the installed isolated QRAFT supervisor."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping

from .controller_contracts import validate_controller_descriptor
from .controller_entrypoint import validate_controller_command
from .controller_files import atomic_controller_json, contained_path, read_controller_json
from .controller_processes import PidfdSignals, ProcessIdentity, process_identity
from .srun_launcher import StepLaunchSpec, StepOutcome


@dataclass
class _Supervisor:
    process: subprocess.Popen
    identity: ProcessIdentity
    stop_request: Path
    terminated: bool = False


class ControllerLauncher:
    """Own process lifecycle only; the existing coordinator still owns leases."""

    def __init__(self, *, root: Path | None = None, grace_seconds: float = 0) -> None:
        self.root = root.resolve() if root is not None else None
        if not math.isfinite(grace_seconds) or grace_seconds < 0:
            raise ValueError("controller grace must be finite and nonnegative")
        self.grace_seconds = grace_seconds
        self._templates: dict[tuple[str, str], tuple[dict[str, Any], Path, Callable[[], None]]] = {}
        self._active: dict[tuple[str, str], _Supervisor] = {}
        self._closures: dict[tuple[str, str], bool] = {}
        self._lock = threading.RLock()

    def bind_attempt(
        self, spec: StepLaunchSpec, descriptor: Mapping[str, Any],
        *, entrypoint: Path, check_authority: Callable[[], None] = lambda: None,
    ) -> None:
        """Compose a native descriptor; only the supervisor birth identity is deferred."""
        if descriptor["task_id"] != spec.task_id or descriptor["attempt_id"] != spec.attempt_id:
            raise ValueError("controller attempt identity mismatch")
        with self._lock:
            key = (spec.task_id, spec.attempt_id)
            if key in self._templates or key in self._active:
                raise ValueError("controller attempt is already bound")
            self._templates[key] = (copy.deepcopy(dict(descriptor)), entrypoint, check_authority)

    def closure_proven(self, task_id: str, attempt_id: str) -> bool:
        with self._lock:
            return self._closures.get((task_id, attempt_id), False)

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        if os.name != "posix":
            raise ValueError("CONTROLLER_REQUIRES_POSIX")
        signals = PidfdSignals()  # unsupported containment rejected before Popen
        key = (spec.task_id, spec.attempt_id)
        with self._lock:
            template, entrypoint, check_authority = self._templates.pop(key)
            self._closures[key] = False
        root = self.root or spec.workdir.parents[2].resolve()
        descriptor_path = spec.workdir / ".qraft" / "controller-reservation.json"
        relative = descriptor_path.relative_to(root).as_posix()
        command = validate_controller_command(
            (spec.executable, *spec.executable_arguments), entrypoint, relative,
        )
        environment = os.environ.copy()
        environment.update(spec.environment or {})
        environment["QRAFT_CONTROLLER_RESERVATION"] = relative
        started = time.monotonic()
        active = None
        process = None
        with spec.stdout_path.open("xb") as stdout, spec.stderr_path.open("xb") as stderr:
            check_authority()
            process = subprocess.Popen(
                [sys.executable, "-I", "-m", "qraft.execution.controller_supervisor",
                 "--descriptor", relative, "--grace", str(self.grace_seconds), "--", *command],
                cwd=root, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                env=environment, start_new_session=True,
            )
            ready_path = descriptor_path.with_name("controller-supervisor-ready.json")
            deadline = time.monotonic() + 10
            try:
                while not ready_path.exists():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise ValueError("CONTROLLER_CONTAINMENT_UNAVAILABLE: supervisor handshake failed")
                    time.sleep(0.01)
                identity = ProcessIdentity(**read_controller_json(ready_path))
                if identity.pid != process.pid or identity != process_identity(process.pid):
                    raise ValueError("controller supervisor identity mismatch")
                descriptor = {**template, "containment": {
                    "method": "SUBREAPER_PIDFD", "supervisor": identity.to_mapping(),
                    "cgroup_path": None,
                }}
                validate_controller_descriptor(descriptor)
                stop_request = contained_path(root, descriptor["paths"]["stop_request"])
                active = _Supervisor(process, identity, stop_request)
                with self._lock:
                    self._active[key] = active
                check_authority()
                # The supervisor claims the state under its own OS lock and
                # publishes owner.json before Popen. The runtime cannot own
                # this lock: it must survive a crash of the runtime parent.
                atomic_controller_json(descriptor_path, descriptor)
                exit_code = int(process.wait())
            except BaseException:
                # Do not kill a supervisor: it owns the closure proof. An
                # already-owned process is signalled only through a checked pidfd.
                if process.poll() is None:
                    identity = process_identity(process.pid)
                    signals.signal_identity(identity, signal.SIGTERM)
                    process.wait(timeout=self.grace_seconds + 25)
                raise
            finally:
                with self._lock:
                    self._active.pop(key, None)
                    try:
                        closure = read_controller_json(descriptor_path.with_name("controller-closure.json"))
                        self._closures[key] = (
                            set(closure) == {"state", "method", "remaining"}
                            and closure == {"state": "CLOSED", "method": "SUBREAPER_PIDFD", "remaining": []}
                        )
                    except (OSError, ValueError):
                        self._closures[key] = False
        return StepOutcome(spec.task_id, spec.attempt_id, command, exit_code,
                           time.monotonic() - started, bool(active and active.terminated))

    def terminate_all(self, *, kill: bool = False) -> tuple[str, ...]:
        """Even `kill=True` requests supervisor TERM; descendant KILL is its job."""
        affected: list[str] = []
        with self._lock:
            for (_, attempt_id), active in self._active.items():
                if active.process.poll() is not None or active.terminated:
                    continue
                active.terminated = True
                atomic_controller_json(active.stop_request, {})
                try:
                    PidfdSignals().signal_identity(active.identity, signal.SIGTERM)
                except (ProcessLookupError, FileNotFoundError):
                    # Absence is NOT closure. The launch finalizer reads the
                    # supervisor proof; missing proof keeps the lease held.
                    pass
                affected.append(attempt_id)
        return tuple(affected)
