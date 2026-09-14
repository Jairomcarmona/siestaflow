"""New-production entry point for translated allocation-local execution."""

from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path
from typing import Mapping

from ..contracts import CapabilityRegistry
from ..core import ExecutionSpec
from ..filesystem import RealFileSystem
from ..runtime_compatibility import INCOMPATIBLE, evaluate_runtime_compatibility
from ..runtime_evidence import RuntimeEvidenceProbe, observe_runtime_evidence
from .adapters import launcher_registry
from .allocation_controller_compat import (
    AllocationController as HistoricalAllocationController,
    ControllerConfig,
    ExecutionStatus,
    load_controller_config,
)
from .capability_plugins import register_generic_command, register_siesta_engine
from .capability_runtime import CompiledWorkflowRuntime, WorkflowRuntimeResult
from .direct_launcher import DirectLauncher
from .legacy_translation import CanonicalLegacyPlan, translate_controller_config
from .placement_validation import probe_launcher_placement
from .resource_coordinator import RuntimeAllocation
from .slurm_environment import ShutdownRequest, SignalHandlers, SlurmEnvironment
from .srun_launcher import StepLauncher


class CanonicalController:
    """Compose old package schema onto the one canonical DAG runtime."""

    def __init__(
        self,
        *,
        root: Path,
        config: ControllerConfig,
        slurm: SlurmEnvironment,
        launcher: StepLauncher | None = None,
        shutdown: ShutdownRequest | None = None,
        poll_interval_seconds: float = 0.05,
        runtime_evidence_probe: RuntimeEvidenceProbe = observe_runtime_evidence,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.slurm = slurm
        self.shutdown = shutdown or ShutdownRequest()
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self.runtime_evidence_probe = runtime_evidence_probe
        self.launcher_adapter = launcher_registry.require(config.launcher_kind)
        self.launcher = launcher or self.launcher_adapter.create(
            command=config.srun_command,
            arguments=config.srun_arguments,
        )
        self.summary_path = self.root / "results" / "campaign_summary.json"
        self.plan: CanonicalLegacyPlan | None = None
        self.runtime: CompiledWorkflowRuntime | None = None
        self.result: WorkflowRuntimeResult | None = None
        self._validated_hosts: tuple[str, ...] = ()

    @classmethod
    def from_file(
        cls,
        campaign_path: Path,
        *,
        root: Path | None = None,
        environment: Mapping[str, str] | None = None,
        launcher: StepLauncher | None = None,
        shutdown: ShutdownRequest | None = None,
        poll_interval_seconds: float = 0.05,
        runtime_evidence_probe: RuntimeEvidenceProbe = observe_runtime_evidence,
    ) -> "CanonicalController":
        campaign_path = campaign_path.resolve()
        selected_root = (root or campaign_path.parent).resolve()
        slurm = SlurmEnvironment.from_mapping(environment)
        if slurm.submit_dir != selected_root:
            raise ValueError(
                f"campaign root must equal SLURM_SUBMIT_DIR: "
                f"{selected_root} != {slurm.submit_dir}"
            )
        return cls(
            root=selected_root,
            config=load_controller_config(campaign_path),
            slurm=slurm,
            launcher=launcher,
            shutdown=shutdown,
            poll_interval_seconds=poll_interval_seconds,
            runtime_evidence_probe=runtime_evidence_probe,
        )

    def _validate_runtime_compatibility(self) -> None:
        components, conflicts = self.runtime_evidence_probe(
            self.config.siesta_executable,
            self.config.srun_command[0] if self.config.srun_command else None,
            {**os.environ, **self.config.environment},
        )
        decision = evaluate_runtime_compatibility(components, conflicts)
        if decision["status"] == INCOMPATIBLE:
            raise ValueError(
                "RUNTIME_COMPATIBILITY_INCOMPATIBLE: selected campaign runtime "
                "contradicts observed evidence"
            )

    def _allocation(self) -> RuntimeAllocation:
        if not self._validated_hosts:
            raise ValueError("ALLOCATION_PLACEMENT_MISMATCH: placement gate not run")
        return RuntimeAllocation(
            total_cpus=self.config.total_cpus,
            total_nodes=self.config.nodes,
            max_parallel_steps=self.config.max_parallel_steps,
            hosts=self._validated_hosts,
            shutdown_margin_seconds=self.config.shutdown_margin_seconds,
            termination_grace_seconds=self.config.termination_grace_seconds,
            allocation_id=self.slurm.job_id,
            remaining_time=self.slurm.remaining_seconds,
        )

    def _placement_execution(self) -> ExecutionSpec:
        if self.config.processes_per_node is None or self.config.ntasks is None:
            raise ValueError(
                "ALLOCATION_PLACEMENT_MISMATCH: campaign placement is incomplete"
            )
        if self.config.nodes * self.config.processes_per_node != self.config.ntasks:
            raise ValueError(
                "ALLOCATION_PLACEMENT_MISMATCH: campaign placement is inconsistent"
            )
        return ExecutionSpec(
            partition=self.config.partition,
            nodes=self.config.nodes,
            mpi_ranks=self.config.ntasks,
            cpus_per_rank=self.config.cpus_per_task,
            memory_mb=None,
            launcher=self.config.launcher_kind,
            executable="hostname",
            walltime_seconds=1,
            environment=self.config.environment,
            launcher_command=self.config.srun_command,
            launcher_arguments=self.config.srun_arguments,
        )

    def _validate_runtime_placement(self) -> None:
        execution = self._placement_execution()
        hosts = self.slurm.resolve_hostnames()
        self.slurm.validate_exact_placement(
            nodes=execution.nodes,
            ntasks=execution.mpi_ranks,
            cpus_per_task=execution.cpus_per_rank,
            tasks_per_node=execution.ranks_per_node,
            hosts=hosts,
        )
        probe_launcher_placement(
            launcher=self.launcher,
            execution=execution,
            hosts=hosts,
            root=self.root,
        )
        self._validated_hosts = hosts

    def run(self, *, install_signal_handlers: bool = True) -> ExecutionStatus:
        self._validate_runtime_compatibility()
        self.plan = translate_controller_config(self.config, root=self.root)
        self._validate_runtime_placement()
        registry = CapabilityRegistry()
        register_siesta_engine(registry)
        register_generic_command(registry)
        registry.freeze()
        launchers: dict[str, StepLauncher] = {
            self.config.launcher_kind: self.launcher,
            "direct": DirectLauncher(),
        }
        self.runtime = CompiledWorkflowRuntime(
            workflow=self.plan.workflow,
            registry=registry,
            root=self.root,
            source_root=self.root,
            scientific_identities=self.plan.scientific_identities,
            execution_specs=self.plan.execution_specs,
            launcher=launchers,
            allocation=self._allocation(),
            shutdown=self.shutdown,
            poll_interval_seconds=self.poll_interval_seconds,
        )
        handlers = SignalHandlers(self.shutdown) if install_signal_handlers else nullcontext()
        with handlers:
            self.result = self.runtime.run()
        status = ExecutionStatus(self.result.status)
        RealFileSystem().atomic_write_json(
            self.summary_path,
            {
                "schema_version": "2.0",
                "execution_authority": "CompiledWorkflowRuntime",
                "compatibility_translation": "allocation-controller-schema",
                "campaign_id": self.config.campaign_id,
                "system_id": self.config.system_id,
                "job_id": self.slurm.job_id,
                "status": status.value,
                "completed_tasks": sum(
                    item.result.execution_state == "COMPLETED"
                    for item in self.result.attempts.values()
                ),
                "total_tasks": len(self.plan.workflow.tasks),
                "peak_cpus": self.result.peak_cpus,
                "peak_parallel_steps": self.result.peak_parallel_steps,
                "remaining_seconds": self.slurm.remaining_seconds(),
                "shutdown_reason": self.shutdown.reason,
                "login_node_persistent_process_required": False,
            },
        )
        return status
