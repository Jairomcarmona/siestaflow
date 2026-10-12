"""Read-only ADR-017 checks before the existing coordinator grants a lease."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from typing import Mapping

from qraft.contracts import CapabilityDescriptor
from qraft.core import ExecutionSpec

from .controller_entrypoint import ControllerExtension, resolve_controller_entrypoint
from .controller_processes import PidfdSignals
from .controller_reservation import ControllerReservation
from .resource_coordinator import RuntimeAllocation


@dataclass(frozen=True)
class ControllerAdmission:
    entrypoint: Path
    extension: ControllerExtension
    runtime_host: str
    runtime_cpus: int
    scheduler_cpus_on_host: int
    scheduler_cpu_source: str


def expand_scheduler_cpus(value: str, nodes: int) -> tuple[int, ...]:
    """Expand SLURM_JOB_CPUS_PER_NODE in the existing scontrol host order."""
    expanded: list[int] = []
    for token in value.split(","):
        match = re.fullmatch(r"([1-9][0-9]*)(?:\(x([1-9][0-9]*)\))?", token.strip())
        if match is None:
            raise ValueError("CONTROLLER_ALLOCATION_MISMATCH: invalid SLURM_JOB_CPUS_PER_NODE")
        cpus, count = int(match.group(1)), int(match.group(2) or "1")
        if len(expanded) + count > nodes:
            raise ValueError("CONTROLLER_ALLOCATION_MISMATCH: CPU observations exceed hosts")
        expanded.extend([cpus] * count)
    if len(expanded) != nodes:
        raise ValueError("CONTROLLER_ALLOCATION_MISMATCH: CPU observations do not cover hosts")
    return tuple(expanded)


def probe_controller_containment() -> None:
    """Set subreaping in a dedicated installed child, never in the runtime itself."""
    try:
        PidfdSignals()
        completed = subprocess.run([
            sys.executable, "-I", "-c",
            "from qraft.execution.controller_processes import SupervisorChildren; "
            "host=SupervisorChildren(); assert host.reap()[1]",
        ], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError("CONTROLLER_CONTAINMENT_UNAVAILABLE") from exc
    if completed.returncode:
        raise ValueError("CONTROLLER_CONTAINMENT_UNAVAILABLE")


def admit_controller(
    reservation: ControllerReservation, descriptor: CapabilityDescriptor,
    allocation: RuntimeAllocation, execution: ExecutionSpec,
    *, scheduler: str, environment: Mapping[str, str],
) -> ControllerAdmission:
    """Resolve installed code, local host and grant arithmetic without acquiring resources."""
    if os.name != "posix":
        raise ValueError("CONTROLLER_REQUIRES_POSIX")
    extension = ControllerExtension.from_descriptor(descriptor)
    if reservation.inner_launcher not in extension.inner_launchers:
        raise ValueError("controller capability does not support the reserved inner launcher")
    entrypoint = resolve_controller_entrypoint(extension)
    request = reservation.resource_request("controller-admission", allocation)
    aliases = {"localhost", socket.gethostname(), socket.getfqdn()}
    aliases.update(host.split(".")[0] for host in tuple(aliases))
    local_hosts = [host for host in allocation.hosts if host in aliases]
    if len(local_hosts) != 1:
        raise ValueError("CONTROLLER_CONTAINMENT_UNAVAILABLE: runtime host is not uniquely allocated")
    host = local_hosts[0]
    if scheduler == "slurm":
        if environment.get("SLURM_JOB_ID") != allocation.allocation_id:
            raise ValueError("CONTROLLER_ALLOCATION_MISMATCH: allocation job identity disagrees")
        values = expand_scheduler_cpus(environment.get("SLURM_JOB_CPUS_PER_NODE", ""), allocation.total_nodes)
        cpus = values[allocation.hosts.index(host)]
        source = "SLURM_JOB_CPUS_PER_NODE"
        if cpus < request.cpus:
            raise ValueError("CONTROLLER_ALLOCATION_MISMATCH: observed CPUs below runtime capacity")
    elif scheduler == "local":
        cpus, source = request.cpus, "LOCAL_PROFILE_DECLARATION"
    else:
        raise ValueError("controller scheduler must be local or slurm")
    if execution.launcher != "controller":
        raise ValueError("controller execution must use the registered controller launcher")
    if len(execution.launcher_command) != 1 or not execution.launcher_command[0].startswith("/"):
        raise ValueError("controller inner launcher must be an absolute profile executable")
    # Scheduler evidence must come from the allocation environment, never from
    # profile values overlaid for the scientific subprocess.
    if any(key.startswith("SLURM_") for key in execution.environment):
        raise ValueError("controller profile must not override scheduler allocation evidence")
    probe_controller_containment()
    return ControllerAdmission(entrypoint, extension, host, request.cpus, cpus, source)
