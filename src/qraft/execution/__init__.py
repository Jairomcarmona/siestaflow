"""Real, allocation-local execution primitives.

The modules in this package never submit allocations.  They are entered by a
batch script that is already running on a compute node and reserve ``srun``
exclusively for scientific job steps.
"""

from .allocation_controller import AllocationController, ExecutionStatus
from .slurm_environment import ShutdownRequest, SlurmEnvironment
from .srun_launcher import SrunLauncher, StepLaunchSpec, StepOutcome

__all__ = (
    "AllocationController",
    "ExecutionStatus",
    "ShutdownRequest",
    "SlurmEnvironment",
    "SrunLauncher",
    "StepLaunchSpec",
    "StepOutcome",
)
"""Allocation-local execution primitives."""

from .direct_launcher import DirectLauncher
from .hydra_launcher import HydraLauncher
from .openmpi_launcher import OpenMpiLauncher
from .adapters import (
    LauncherAdapter, LauncherRegistry, SchedulerAdapter, SchedulerRegistry,
    launcher_registry, scheduler_registry,
)
from .srun_launcher import SrunLauncher, StepLauncher

__all__ = [
    "AllocationController", "DirectLauncher", "ExecutionStatus", "HydraLauncher",
    "LauncherAdapter", "LauncherRegistry", "OpenMpiLauncher", "SchedulerAdapter",
    "SchedulerRegistry", "ShutdownRequest", "SlurmEnvironment", "SrunLauncher",
    "StepLaunchSpec", "StepLauncher", "StepOutcome", "launcher_registry",
    "scheduler_registry",
]
