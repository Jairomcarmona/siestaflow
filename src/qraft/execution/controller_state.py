"""ADR-017 task state integrity and positive proof of prior owner closure."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

from qraft.contracts.serialization import contract_sha256

from .controller_files import contained_path, read_controller_json


class ControllerStateError(ValueError):
    """Persistent controller state cannot be claimed by a new attempt."""


@dataclass(frozen=True)
class ControllerStateManifest:
    files: tuple[tuple[str, str], ...]
    directories: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {"files": dict(self.files), "directories": list(self.directories)}

    @property
    def sha256(self) -> str:
        return contract_sha256(self.to_mapping())


def controller_state_manifest(state_dir: Path) -> ControllerStateManifest:
    """Hash all persistent native state, rejecting symbolic links and special files."""
    files: list[tuple[str, str]] = []
    directories: list[str] = []
    for path in sorted(state_dir.rglob("*")):
        relative = path.relative_to(state_dir).as_posix()
        if path.is_symlink():
            raise ControllerStateError("CONTROLLER_STATE_TAMPERED: symlink in controller state")
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            files.append((relative, digest.hexdigest()))
        else:
            raise ControllerStateError("CONTROLLER_STATE_TAMPERED: unsupported state file")
    return ControllerStateManifest(tuple(files), tuple(directories))


def previous_controller_owner(
    root: Path, state_dir: Path, *, current_boot_id: str, current_host: str,
) -> dict[str, Any] | None:
    """No PID/group/queue absence is ever evidence that the prior owner died.

    Scheduler-terminal proof is deliberately not accepted by this local helper:
    a verified U-Q5 terminal record and positive proctrack/cgroup probe must be
    composed by the scheduler adapter before that alternative can be used.
    """
    owner_path = state_dir / "owner.json"
    if not owner_path.exists():
        if state_dir.exists() and any(state_dir.iterdir()):
            raise ControllerStateError("CONTROLLER_STATE_TAMPERED: state without an owner")
        return None
    try:
        owner = read_controller_json(owner_path)
        expected = {"attempt_id", "authority_generation", "host", "boot_id",
                    "supervisor_pid", "supervisor_start_time_ticks", "closure_ref"}
        if set(owner) != expected or owner["host"] != current_host:
            raise ValueError("invalid owner identity or remote host")
        if (not isinstance(owner["attempt_id"], str) or not owner["attempt_id"]
                or type(owner["supervisor_pid"]) is not int
                or not 1 <= owner["supervisor_pid"] <= 9007199254740991
                or not isinstance(owner["boot_id"], str)
                or re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", owner["boot_id"]) is None
                or not isinstance(owner["supervisor_start_time_ticks"], str)
                or re.fullmatch(r"-?(0|[1-9][0-9]*)", owner["supervisor_start_time_ticks"]) is None):
            raise ValueError("invalid owner process birth identity")
        generation = owner["authority_generation"]
        if generation is not None and (
            not isinstance(generation, str) or re.fullmatch(r"-?(0|[1-9][0-9]*)", generation) is None
        ):
            raise ValueError("invalid owner authority generation")
        closure_path = contained_path(root, owner["closure_ref"])
        closure = None
        try:
            closure = read_controller_json(closure_path)
        except (OSError, ValueError):
            pass
        if closure == {"state": "CLOSED", "method": "SUBREAPER_PIDFD", "remaining": []}:
            proof = "CLOSED"
        elif owner["boot_id"] != current_boot_id:
            proof = "OWNER_DEAD_BY_BOOT_CHANGE"
        else:
            raise ControllerStateError("CONTROLLER_PREVIOUS_OWNER_ALIVE")
        # The supervisor seals the final state independently of the parent
        # runtime, so a runtime crash cannot lose an otherwise proved closure.
        seal_path = closure_path.with_name("controller-state-manifest.json")
        seal_present = seal_path.exists() or seal_path.is_symlink()
        closure_present = closure_path.exists() or closure_path.is_symlink()
        manifest = controller_state_manifest(state_dir)
        state_seal = None
        if seal_present:
            recorded = read_controller_json(seal_path)
            if recorded != manifest.to_mapping():
                raise ControllerStateError("CONTROLLER_STATE_TAMPERED")
        elif proof == "CLOSED" or closure_present:
            # A clean supervisor closure always writes a seal before closure.
            # Likewise, an unsealed closure is not the signature of a host
            # restart and cannot be treated as a crash-recovery case.
            raise ControllerStateError("CONTROLLER_STATE_TAMPERED")
        else:
            # A changed boot ID is positive proof that the old owner cannot
            # still hold the host. The current manifest becomes the measured
            # admission baseline; the caller records this marker as attempt
            # evidence without extending the reservation schema.
            state_seal = "ABSENT_AFTER_BOOT_CHANGE"
        previous = {"attempt_id": owner["attempt_id"], "outcome": "INTERRUPTED",
                    "closure": proof, "state_manifest_sha256": manifest.sha256}
        if state_seal is not None:
            previous["state_seal"] = state_seal
        return previous
    except ControllerStateError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ControllerStateError("CONTROLLER_STATE_TAMPERED") from exc
