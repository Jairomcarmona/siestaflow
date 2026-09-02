"""Generic composition of an execution placement for the canonical runtime."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..core import ExecutionSpec
from ..runtime_compatibility import INCOMPATIBLE, evaluate_runtime_compatibility
from ..runtime_evidence import observe_runtime_evidence
from .adapters import launcher_registry
from .placement_validation import probe_launcher_placement
from .resource_coordinator import RuntimeAllocation
from .slurm_environment import SlurmEnvironment
from .srun_launcher import StepLauncher


@dataclass(frozen=True)
class RuntimeComposition:
    """Launcher and capacity selected from one resolved execution contract."""

    launcher: StepLauncher
    allocation: RuntimeAllocation


def compose_runtime(
    execution: ExecutionSpec,
    *,
    max_parallel_steps: int = 1,
    environment: Mapping[str, str] | None = None,
    placement_probe_root: Path | None = None,
) -> RuntimeComposition:
    """Compose registered launch infrastructure without scientific policy."""

    adapter = launcher_registry.require(execution.launcher)
    values = dict(os.environ if environment is None else environment)
    launcher_command = execution.launcher_command or adapter.default_command
    components, conflicts = observe_runtime_evidence(
        execution.executable,
        launcher_command[0] if launcher_command else None,
        {**values, **execution.environment},
    )
    if evaluate_runtime_compatibility(components, conflicts)["status"] == INCOMPATIBLE:
        raise ValueError(
            "RUNTIME_COMPATIBILITY_INCOMPATIBLE: resolved execution runtime "
            "contradicts observed evidence"
        )
    launcher = adapter.create(
        command=execution.launcher_command,
        arguments=execution.launcher_arguments,
    )
    active_slurm = str(values.get("SLURM_JOB_ID", "")).strip()
    slurm: SlurmEnvironment | None = None
    if active_slurm:
        partition = str(values.get("SLURM_JOB_PARTITION", "")).strip()
        if partition and partition != execution.partition:
            raise ValueError(
                "execution partition does not match active allocation: "
                f"{execution.partition}!={partition}"
            )
        values.setdefault("SLURM_SUBMIT_DIR", str(Path.cwd()))
        values.setdefault(
            "SLURM_JOB_END_TIME", str(time.time() + execution.walltime_seconds)
        )
        slurm = SlurmEnvironment.from_mapping(values)
        if placement_probe_root is None:
            raise ValueError(
                "exact Slurm placement requires an evidence root"
            )
    if adapter.requires_allocation and slurm is None:
        raise ValueError(
            f"{adapter.name} launcher requires an active "
            f"{adapter.scheduler.upper()} allocation"
        )
    hosts = (
        slurm.resolve_hostnames()
        if slurm and (adapter.requires_hosts or placement_probe_root is not None)
        else ()
    )
    if slurm is not None and placement_probe_root is not None:
        slurm.validate_exact_placement(
            nodes=execution.nodes,
            ntasks=execution.mpi_ranks,
            cpus_per_task=execution.cpus_per_rank,
            tasks_per_node=execution.ranks_per_node,
            hosts=hosts,
        )
        probe_launcher_placement(
            launcher=launcher,
            execution=execution,
            hosts=hosts,
            root=placement_probe_root,
        )
    return RuntimeComposition(
        launcher=launcher,
        allocation=RuntimeAllocation(
            total_cpus=execution.allocated_cpus,
            total_nodes=execution.nodes,
            max_parallel_steps=max_parallel_steps,
            hosts=hosts,
            allocation_id=slurm.job_id if slurm else "local",
            remaining_time=slurm.remaining_seconds if slurm else (lambda: float("inf")),
        ),
    )
