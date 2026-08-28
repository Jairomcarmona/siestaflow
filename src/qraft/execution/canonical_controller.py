"""New-production entry point for translated allocation-local execution."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Mapping

from ..contracts import CapabilityRegistry
from ..filesystem import RealFileSystem
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
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.slurm = slurm
        self.shutdown = shutdown or ShutdownRequest()
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self.launcher_adapter = launcher_registry.require(config.launcher_kind)
        self.launcher = launcher or self.launcher_adapter.create(
            command=config.srun_command,
            arguments=config.srun_arguments,
        )
        self.summary_path = self.root / "results" / "campaign_summary.json"
        self.plan: CanonicalLegacyPlan | None = None
        self.runtime: CompiledWorkflowRuntime | None = None
        self.result: WorkflowRuntimeResult | None = None

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
        )

    def _allocation(self) -> RuntimeAllocation:
        self.slurm.validate_capacity(
            nodes=self.config.nodes, total_cpus=self.config.total_cpus
        )
        hosts = (
            self.slurm.resolve_hostnames()
            if self.launcher_adapter.requires_hosts
            else ()
        )
        return RuntimeAllocation(
            total_cpus=self.config.total_cpus,
            total_nodes=self.config.nodes,
            max_parallel_steps=self.config.max_parallel_steps,
            hosts=hosts,
            shutdown_margin_seconds=self.config.shutdown_margin_seconds,
            termination_grace_seconds=self.config.termination_grace_seconds,
            allocation_id=self.slurm.job_id,
            remaining_time=self.slurm.remaining_seconds,
        )

    def run(self, *, install_signal_handlers: bool = True) -> ExecutionStatus:
        self.plan = translate_controller_config(self.config, root=self.root)
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
