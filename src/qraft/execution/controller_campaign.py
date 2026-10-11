"""ADR-017 campaign declarations and explicit lock binding checks, without I/O.

These checks are independent helpers until the campaign loader/preparer and the
compiled runtime are connected. Importing this module does not enable execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping

from qraft.contracts.versioning import require_namespaced_identifier

from .controller_reservation import ControllerReservation


@dataclass(frozen=True)
class ControllerTaskDeclaration:
    task_id: str
    capability_id: str
    reservation: ControllerReservation


def controller_task_declarations(campaign: Mapping[str, Any]) -> tuple[ControllerTaskDeclaration, ...]:
    """Validate only the new declarations, preserving the legacy schema boundary."""
    tasks = campaign.get("tasks")
    if not isinstance(tasks, list) or any(not isinstance(task, Mapping) for task in tasks):
        raise ValueError("controller campaign tasks must be mappings")
    controllers = [task for task in tasks if task.get("kind") == "controller"]
    version = campaign.get("schema_version")
    if bool(controllers) != (version == "2.1"):
        raise ValueError("campaign schema 2.1 is required exactly when a controller exists")
    if not controllers:
        return ()
    if os.name != "posix":
        raise ValueError("CONTROLLER_REQUIRES_POSIX")
    declarations: list[ControllerTaskDeclaration] = []
    seen: set[str] = set()
    for task in tasks:
        task_id = task.get("task_id")
        if (not isinstance(task_id, str) or not task_id.strip() or task_id in {".", ".."}
                or any(char in task_id for char in ("/", "\\", "\x00")) or task_id in seen):
            raise ValueError("invalid or duplicate controller campaign task id")
        seen.add(task_id)
        if task.get("kind") != "controller":
            continue
        for field, expected in (("mpi_processes", 1), ("cpus_per_process", 1), ("nodes", 0)):
            value = task.get(field)
            if type(value) is not int or value != expected:
                raise ValueError("controller outer placement requires processes=1, CPUs=1, nodes=0")
        if any(field in task for field in (
            "command", "require_scf_converged", "executable", "siesta_executable", "executable_arguments",
        )):
            raise ValueError("controller task commands, SCF conditions and executable overrides are forbidden")
        capability_id = task.get("capability_id")
        if not isinstance(capability_id, str):
            raise ValueError("controller capability_id is required")
        require_namespaced_identifier(capability_id, field="capability_id")
        reservation = ControllerReservation.from_mapping(task.get("reservation"))
        declarations.append(ControllerTaskDeclaration(task_id, capability_id, reservation))
    return tuple(declarations)


def validate_controller_bindings(
    declarations: tuple[ControllerTaskDeclaration, ...],
    capability_bindings: Mapping[str, str] | None,
    locked_capabilities: Mapping[str, str],
) -> None:
    """Require every new controller's declaration, explicit binding and lock to agree.

    The caller must obtain locked_capabilities from the verified native workflow
    lock; this helper never discovers plugins, reads arbitrary files, or replaces
    the run/workflow lock checksum verification.
    """
    for task in declarations:
        if capability_bindings is None or capability_bindings.get(task.task_id) != task.capability_id:
            raise ValueError("controller capability_bindings are mandatory and must match the declaration")
        if locked_capabilities.get(task.task_id) != task.capability_id:
            raise ValueError("controller capability_id disagrees with the verified workflow lock")
