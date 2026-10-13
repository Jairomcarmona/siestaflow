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
from .execution.controller_reservation import ControllerReservation
from .execution.slurm_environment import ShutdownRequest
from .siesta_validation import SiestaContextualValidator
from .execution.authority import AuthorityBoundary, AuthorityCheck, AuthorityLost
from .execution.event_stream import NativeEventStream, NativeEventPage, NativeCursorError
from .scheduler_evidence import SchedulerJobIdentity, TerminalSchedulerEvidence, TerminalEvidenceVerifier
from .protocols.eos import EosProtocol
from .protocols.electronic_analysis import ElectronicAnalysisProtocol
from .protocols.electronic_properties import ElectronicPropertiesProtocol, ElectronicStateSource, PreparedElectronicProperties
from .engines.siesta.electronic_properties import BandPathSpec, DosSpec, PdosSpec, PropertySpec
from .scientific_policies import scientific_policy_document, scientific_policy_evidence
from .scientific_convergence import MeshConvergenceRule, MeshObservation, MeshConvergenceReport, MeshConvergenceEvaluator
from .scientific_kgrid import KGridConvergenceRule, KGridObservation, KGridConvergenceReport, KGridConvergenceEvaluator

API_VERSION = "1.0"
__all__ = [
    "API_VERSION", "ArtifactPortContract", "IntentIdentity", "RecipePolicy",
    "WorkflowComposer", "WorkflowFragment", "WorkflowCompiler", "WorkflowCompilation",
    "write_workflow_lock", "load_run_lock", "load_workflow_lock", "RunPreparationRequest",
    "RunPreparationResult", "RunPreparer", "PreparedRunInspection", "ResumePlan", "RunInspector",
    "CanonicalController", "CompiledWorkflowRuntime", "WorkflowRuntimeResult", "RuntimeAllocation",
    "ControllerReservation",
    "ShutdownRequest", "SiestaContextualValidator", "AuthorityBoundary", "AuthorityCheck", "AuthorityLost",
    "NativeEventStream", "NativeEventPage", "NativeCursorError",
    "SchedulerJobIdentity", "TerminalSchedulerEvidence", "TerminalEvidenceVerifier",
    "EosProtocol", "ElectronicAnalysisProtocol", "ElectronicPropertiesProtocol",
    "ElectronicStateSource", "PreparedElectronicProperties",
    "BandPathSpec", "DosSpec", "PdosSpec", "PropertySpec",
    "scientific_policy_document", "scientific_policy_evidence",
    "MeshConvergenceRule", "MeshObservation", "MeshConvergenceReport", "MeshConvergenceEvaluator",
    "KGridConvergenceRule", "KGridObservation", "KGridConvergenceReport", "KGridConvergenceEvaluator",
]
