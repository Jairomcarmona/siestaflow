"""Generic SIESTA campaign construction from external project packages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .authorization import AuthorizationEngine
from .campaign import BasicCampaignPlanner, CampaignRunner
from .engines.siesta.adapter import SyntheticSiestaLauncher
from .engines.siesta.fdf_variants import FDFVariant, FDFVariantGenerator, VariantAuthorization
from .filesystem import FileSystem, RealFileSystem
from .gates import GateEngine
from .hpc import FakeSlurmClient, SlurmJobState, TimeBudget
from .models import AllocationContext, AuthorizationEnvelope, CampaignManifest, CampaignState, TaskSpec, utc_now
from .project_packages import ProjectPackage, load_structured
from .slurm_renderer import SlurmProfile, SlurmRenderResult, SlurmRenderer
from .workspace import WorkspaceManager


@dataclass(frozen=True)
class CampaignDefinition:
    manifest: CampaignManifest
    authorization: AuthorizationEnvelope
    status: str
    input_sha256: str
    metadata: dict[str, object]


def issue_authorization(
    campaign_id: str,
    task_types: tuple[str, ...],
    *,
    targets: tuple[str, ...],
    synthetic: bool,
    authorization_data: dict[str, Any] | None = None,
) -> AuthorizationEnvelope:
    data = authorization_data or {}
    now = datetime.now(timezone.utc)
    return AuthorizationEngine.issue(
        authorization_id=str(data.get("authorization_id", f"AUTH_{campaign_id}")),
        campaign_id=campaign_id,
        allowed_task_types=tuple(map(str, data.get("allowed_task_types", task_types))),
        generic_targets=tuple(map(str, data.get("targets", targets))),
        forbidden_operations=tuple(map(str, data.get("forbidden_operations", ("REAL_ENGINE", "SBATCH", "SSH", "AUTO_RESTART")))),
        stop_on_review=bool(data.get("stop_on_review", True)),
        issued_by=str(data.get("issued_by", "PROJECT_PACKAGE")),
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(days=int(data.get("valid_days", 30)))).isoformat(),
    )


class SiestaCampaignFactory:
    """Interpret a declarative campaign without project-specific constants."""

    def from_package(self, package: ProjectPackage, campaign_id: str) -> tuple[CampaignDefinition, tuple[FDFVariant, ...]]:
        campaign = package.campaign(campaign_id)
        system = package.system(campaign.system_id)
        input_path = package.root / system.input_template
        text = input_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()
        auth_data = load_structured(package.root / campaign.authorization)
        authorization = issue_authorization(
            campaign_id, (campaign.task_type,), targets=(system.system_id,),
            synthetic=campaign.synthetic_only, authorization_data=auth_data,
        )
        variants: tuple[FDFVariant, ...] = ()
        if campaign.parameter:
            variant_auth = VariantAuthorization.issue(
                authorization, base_fdf_sha256=digest,
                allowed_parameter=campaign.parameter, allowed_values=campaign.values,
                synthetic_only=campaign.synthetic_only,
            )
            variants = FDFVariantGenerator().generate_series(text, variant_auth)
        task_values = campaign.values if variants else (None,)
        variant_hashes = [variant.sha256 for variant in variants]
        tasks = [
            TaskSpec(
                f"task_{index:03d}", campaign.task_type, system.system_id,
                ("synthetic-siesta", input_path.name), 1.0,
                {
                    "operation": campaign.task_type, "synthetic_only": campaign.synthetic_only,
                    "parameter": campaign.parameter, "value": value,
                    "variant_sha256": variant_hashes[index - 1] if variants else digest,
                },
            )
            for index, value in enumerate(task_values, start=1)
        ]
        manifest = BasicCampaignPlanner().create(campaign_id=campaign_id, project_id=package.project_id, tasks=tasks)
        metadata: dict[str, object] = {
            "mode": campaign.mode, "planned_tasks": len(tasks),
            "synthetic_only": campaign.synthetic_only, "real_execution_authorized": False,
            "system_id": system.system_id, "species": list(system.species),
            "input_path": system.input_template, "parameter": campaign.parameter,
            "values": list(campaign.values), "project_root": str(package.root),
            **dict(campaign.metadata),
        }
        return CampaignDefinition(manifest, authorization, "EXECUTION_READY_PENDING_PREFLIGHT", digest, metadata), variants


def simulate_definition(
    definition: CampaignDefinition,
    root: Path,
    *,
    filesystem: FileSystem | None = None,
    fixtures: dict[str, str] | None = None,
    allocation_seconds: float = 100.0,
) -> tuple[CampaignState, SyntheticSiestaLauncher, FakeSlurmClient]:
    fs = filesystem or RealFileSystem()
    launcher = SyntheticSiestaLauncher(fixtures)
    slurm = FakeSlurmClient()
    state_path = root / "campaigns" / definition.manifest.campaign_id / "state.json"
    if state_path.is_file():
        stored = json.loads(state_path.read_text(encoding="utf-8"))
        allocation_id = stored.get("payload", stored).get("allocation_id")
        if allocation_id:
            slurm.allocations[allocation_id] = AllocationContext(
                allocation_id, definition.manifest.campaign_id, allocation_seconds,
                allocation_seconds, utc_now(), True,
            )
            job_id = f"RESUMED_JOB_{allocation_id}"
            slurm.job_for_allocation[allocation_id] = job_id
            slurm.jobs[job_id] = SlurmJobState.RUNNING
            slurm.queue_presence[job_id] = True
    runner = CampaignRunner(
        workspace=WorkspaceManager(root, fs), filesystem=fs,
        authorization=AuthorizationEngine(), gates=GateEngine(), launcher=launcher,
        slurm=slurm, time_budget=TimeBudget(safety_factor=1, shutdown_margin_seconds=0, checkpoint_margin_seconds=0),
    )
    state = runner.run(definition.manifest, definition.authorization, allocation_seconds=allocation_seconds)
    return state, launcher, slurm


def render_campaign_slurm(definition: CampaignDefinition, profile: SlurmProfile | None = None) -> SlurmRenderResult:
    return SlurmRenderer().render(
        profile or SlurmProfile(), job_name=definition.manifest.campaign_id,
        worker_command=f"siestaflow campaign worker {definition.manifest.campaign_id}",
    )
