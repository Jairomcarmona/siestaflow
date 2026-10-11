"""Installed isolated ADR-017 subreaper; never used as an MPI launcher."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import time

from .controller_contracts import validate_controller_descriptor
from .controller_files import atomic_controller_json, contained_path, read_controller_json
from .controller_processes import SupervisorChildren, process_identity
from .controller_state import controller_state_manifest, previous_controller_owner


def supervise(descriptor_relative: str, grace_seconds: float, command: list[str]) -> int:
    """Handshake, adopt descendants, and publish closure only after ECHILD."""
    children = SupervisorChildren()  # prctl BEFORE any child is created
    root = Path.cwd().resolve()
    descriptor_path = contained_path(root, descriptor_relative)
    ready_path = descriptor_path.with_name("controller-supervisor-ready.json")
    closure_path = descriptor_path.with_name("controller-closure.json")
    stopping = False
    stop_started: float | None = None

    def request_stop(number, frame) -> None:
        nonlocal stopping, stop_started
        stopping = True
        if stop_started is None:
            stop_started = time.monotonic()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    identity = process_identity(os.getpid())
    atomic_controller_json(ready_path, identity.to_mapping())
    startup_deadline = time.monotonic() + 10
    while not descriptor_path.exists() and not stopping:
        if time.monotonic() > startup_deadline:
            stopping = True
            break
        time.sleep(0.01)
    leader = None
    descriptor = None
    guard = None
    owner_claimed = False
    exit_code = 1
    try:
        if not stopping:
            descriptor = read_controller_json(descriptor_path)
            validate_controller_descriptor(descriptor)
            if descriptor["containment"]["supervisor"] != identity.to_mapping():
                raise ValueError("supervisor descriptor identity mismatch")
            import fcntl
            guard_path = root / "state" / "controller-owners" / (
                hashlib.sha256(descriptor["task_id"].encode()).hexdigest() + ".lock"
            )
            guard_path.parent.mkdir(parents=True, exist_ok=True)
            guard = guard_path.open("a+b")
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            state_dir = contained_path(root, descriptor["paths"]["state_dir"])
            previous = previous_controller_owner(
                root, state_dir, current_boot_id=identity.boot_id,
                current_host=descriptor["reserved"]["hosts"][0],
            )
            expected_previous = descriptor["previous_attempt"]
            if (previous is None) != (expected_previous is None) or (
                previous is not None and any(previous[name] != expected_previous[name]
                    for name in ("attempt_id", "closure", "state_manifest_sha256"))
            ):
                raise ValueError("controller owner changed after admission")
            atomic_controller_json(state_dir / "owner.json", {
                "attempt_id": descriptor["attempt_id"],
                "authority_generation": descriptor["authority_generation"],
                "host": descriptor["reserved"]["hosts"][0],
                "boot_id": identity.boot_id, "supervisor_pid": identity.pid,
                "supervisor_start_time_ticks": identity.start_time_ticks,
                "closure_ref": closure_path.relative_to(root).as_posix(),
            })
            owner_claimed = True
            env = os.environ.copy()
            env["QRAFT_CONTROLLER_RESERVATION"] = descriptor_relative
            leader = subprocess.Popen(command, stdin=subprocess.DEVNULL, env=env)
            # No setsid: the only new session is the QRAFT-owned supervisor.
            leader_identity = process_identity(leader.pid)
            term_sent = False
            while True:
                exits, empty = children.reap()
                if leader.pid in exits:
                    exit_code = exits[leader.pid]
                    leader.returncode = exit_code
                if empty and leader.returncode is not None:
                    break
                if datetime.now(timezone.utc) >= datetime.fromisoformat(descriptor["deadline"]["stop_launching_at"]):
                    if not stopping:
                        atomic_controller_json(contained_path(root, descriptor["paths"]["stop_request"]), {})
                        request_stop(signal.SIGTERM, None)
                if stopping and not term_sent:
                    children.signal_owned(leader_identity, signal.SIGTERM)
                    term_sent = True
                # A leader that exits normally may leave descendants behind.
                # It does not release the reservation: close those descendants
                # using the same grace sequence before recording ECHILD.
                if leader.returncode is not None and stop_started is None:
                    stop_started = time.monotonic()
                    children.signal_all(signal.SIGTERM)
                if stop_started is not None and time.monotonic() - stop_started >= grace_seconds:
                    children.signal_all(signal.SIGKILL)
                    if time.monotonic() - stop_started >= grace_seconds + 10:
                        raise ValueError("CONTROLLER_DESCENDANTS_ALIVE")
                time.sleep(0.01)
        else:
            _, empty = children.reap()
            if not empty:
                raise ValueError("unexpected children before controller launch")
        if descriptor is not None and guard is not None:
            atomic_controller_json(closure_path.with_name("controller-state-manifest.json"),
                                   controller_state_manifest(state_dir).to_mapping())
        atomic_controller_json(closure_path, {
            "state": "CLOSED", "method": "SUBREAPER_PIDFD", "remaining": [],
        })
    except Exception:
        children.signal_all(signal.SIGKILL)
        deadline = time.monotonic() + 10
        empty = False
        while time.monotonic() < deadline:
            _, empty = children.reap()
            if empty:
                break
            children.signal_all(signal.SIGKILL)
            time.sleep(0.01)
        if empty and owner_claimed:
            atomic_controller_json(closure_path.with_name("controller-state-manifest.json"),
                                   controller_state_manifest(state_dir).to_mapping())
        atomic_controller_json(closure_path, {
            "state": "CLOSED" if empty else "OPEN", "method": "SUBREAPER_PIDFD",
            "remaining": [item.to_mapping() for item in children.descendants().values()],
        })
        raise
    finally:
        if guard is not None:
            guard.close()
    return exit_code if 0 <= exit_code <= 255 else 128 - exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--grace", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not math.isfinite(args.grace) or args.grace < 0 or not args.command or args.command[0] != "--":
        parser.error("nonnegative grace and explicit controller command required")
    return supervise(args.descriptor, args.grace, args.command[1:])


if __name__ == "__main__":
    raise SystemExit(main())
