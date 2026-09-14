"""Stable facade for the legacy allocation-controller compatibility path.

The production API remains import-compatible for existing packages. The
SIESTA-shaped persisted schemas and parser/restart compatibility live in the
explicitly named ``allocation_controller_compat`` module. New compiled
workflows execute through the engine-neutral ``CompiledWorkflowRuntime``.
"""

from .allocation_controller_compat import (
    AllocationController as HistoricalAllocationController,
    ArtifactTransfer,
    ControllerConfig,
    ControllerTask,
    ExecutionStatus,
    load_controller_config,
)

# Backward-compatible import only. New production CLI/package entry points use
# CanonicalController and never select this historical scheduler implicitly.
AllocationController = HistoricalAllocationController

__all__ = [
    "AllocationController",
    "ArtifactTransfer",
    "ControllerConfig",
    "ControllerTask",
    "ExecutionStatus",
    "HistoricalAllocationController",
    "load_controller_config",
]
