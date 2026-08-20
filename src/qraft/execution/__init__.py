"""Engine-neutral execution primitives and legacy compatibility access."""

from __future__ import annotations

from .adapters import (
    LauncherAdapter,
    LauncherRegistry,
    SchedulerAdapter,
    SchedulerRegistry,
    launcher_registry,
    scheduler_registry,
)
from .capability_runtime import CompiledWorkflowRuntime, WorkflowRuntimeResult
from .direct_launcher import DirectLauncher
from .hydra_launcher import HydraLauncher
from .openmpi_launcher import OpenMpiLauncher
from .slurm_environment import ShutdownRequest, SlurmEnvironment
from .srun_launcher import SrunLauncher, StepLaunchSpec, StepLauncher, StepOutcome


def __getattr__(name: str):
    if name in {"AllocationController", "ExecutionStatus"}:
        from .allocation_controller import AllocationController, ExecutionStatus

        return {
            "AllocationController": AllocationController,
            "ExecutionStatus": ExecutionStatus,
        }[name]
    raise AttributeError(name)


__all__ = [
    "AllocationController",
    "CompiledWorkflowRuntime",
    "DirectLauncher",
    "ExecutionStatus",
    "HydraLauncher",
    "LauncherAdapter",
    "LauncherRegistry",
    "OpenMpiLauncher",
    "SchedulerAdapter",
    "SchedulerRegistry",
    "ShutdownRequest",
    "SlurmEnvironment",
    "SrunLauncher",
    "StepLaunchSpec",
    "StepLauncher",
    "StepOutcome",
    "WorkflowRuntimeResult",
    "launcher_registry",
    "scheduler_registry",
]
