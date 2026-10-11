"""Versioned public integration surface; no import-time plugin registration.

API 1.0 preserves native contract versions and native digest algorithms.
Only names in __all__ are public; implementation modules remain internal.
"""

from .workflow_composition import ArtifactPortContract, IntentIdentity, RecipePolicy, WorkflowComposer, WorkflowFragment
from .workflows.compiler import WorkflowCompiler, write_workflow_lock
from .workflows.models import WorkflowCompilation
from .workflows.lock_loader import load_run_lock, load_workflow_lock
from .run_preparation import RunPreparationRequest, RunPreparationResult, RunPreparer
from .run_inspection import PreparedRunInspection, ResumePlan, RunInspector
from .execution.canonical_controller import CanonicalController
from .execution.capability_runtime import CompiledWorkflowRuntime, WorkflowRuntimeResult
from .execution.resource_coordinator import RuntimeAllocation
from .execution.slurm_environment import ShutdownRequest
from .siesta_validation import SiestaContextualValidator

API_VERSION = "1.0"
__all__ = [
    "API_VERSION", "ArtifactPortContract", "IntentIdentity", "RecipePolicy",
    "WorkflowComposer", "WorkflowFragment", "WorkflowCompiler", "WorkflowCompilation",
    "write_workflow_lock", "load_run_lock", "load_workflow_lock", "RunPreparationRequest",
    "RunPreparationResult", "RunPreparer", "PreparedRunInspection", "ResumePlan", "RunInspector",
    "CanonicalController", "CompiledWorkflowRuntime", "WorkflowRuntimeResult", "RuntimeAllocation",
    "ShutdownRequest", "SiestaContextualValidator",
]
