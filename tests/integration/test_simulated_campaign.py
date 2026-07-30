from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from siestaflow.authorization import AuthorizationEngine
from siestaflow.campaign import BasicCampaignPlanner, CampaignRunner
from siestaflow.errors import AuthorizationError, IntegrityError
from siestaflow.filesystem import RealFileSystem
from siestaflow.gates import GateEngine
from siestaflow.hpc import FakeSlurmClient, LocalFakeLauncher, TimeBudget
from siestaflow.models import DecisionStatus, ProjectManifest, TaskSpec, TaskState
from siestaflow.project import ProjectManager
from siestaflow.storage import EventStore, StateStore
from siestaflow.workspace import WorkspaceManager


def tasks(*, runtime: float = 10.0) -> list[TaskSpec]:
    return [
        TaskSpec(f"TASK_{index:03d}", "SIMULATED", f"TARGET_{index:03d}", ("fake", "run"), runtime)
        for index in range(1, 4)
    ]


def authorization(*, targets=("TARGET_001", "TARGET_002", "TARGET_003")):
    now = datetime.now(timezone.utc)
    return AuthorizationEngine.issue(
        authorization_id="AUTH_SIM_001",
        campaign_id="SIMULATED_CAMPAIGN_001",
        allowed_task_types=("SIMULATED",),
        generic_targets=tuple(targets),
        forbidden_operations=("SCIENTIFIC_ENGINE", "DELETE"),
        stop_on_review=True,
        issued_by="M1_TEST",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )


def kernel(tmp_path: Path, *, scenarios=None, runtime: float = 10.0, budget=None):
    fs = RealFileSystem()
    project_root = ProjectManager(fs).create(tmp_path, ProjectManifest("PROJECT_001", "M1 test"))
    manifest = BasicCampaignPlanner().create(
        campaign_id="SIMULATED_CAMPAIGN_001",
        project_id="PROJECT_001",
        tasks=tasks(runtime=runtime),
    )
    launcher = LocalFakeLauncher(scenarios)
    slurm = FakeSlurmClient()
    workspace = WorkspaceManager(project_root, fs)
    runner = CampaignRunner(
        workspace=workspace,
        filesystem=fs,
        authorization=AuthorizationEngine(),
        gates=GateEngine(),
        launcher=launcher,
        slurm=slurm,
        time_budget=budget or TimeBudget(),
    )
    return runner, manifest, launcher, slurm, workspace


def test_one_allocation_three_sequential_tasks(tmp_path: Path):
    runner, manifest, launcher, slurm, workspace = kernel(tmp_path)

    state = runner.run(manifest, authorization(), allocation_seconds=10_000)

    assert state.final_decision is DecisionStatus.PASS
    assert list(state.task_states.values()) == [TaskState.COMPLETED] * 3
    assert state.attempt_counts == {f"TASK_{i:03d}": 1 for i in range(1, 4)}
    assert len(state.results) == 3
    assert slurm.submissions == 1
    assert {allocation for allocation, _, _ in launcher.launches} == {state.allocation_id}
    campaign = workspace.campaign_path(manifest.campaign_id)
    for index in range(1, 4):
        assert (campaign / "tasks" / f"TASK_{index:03d}" / "attempt_001").is_dir()
    assert len((campaign / "artifacts.jsonl").read_text(encoding="utf-8").splitlines()) == 6
    EventStore(campaign / "events.jsonl", runner.fs).assert_matches(state)


def test_review_on_task_two_stops_before_task_three(tmp_path: Path):
    runner, manifest, launcher, _, _ = kernel(tmp_path, scenarios={"TASK_002": "unknown_warning"})

    state = runner.run(manifest, authorization(), allocation_seconds=10_000)

    assert state.task_states["TASK_002"] is TaskState.REVIEW
    assert state.task_states["TASK_003"] is TaskState.PLANNED
    assert [task for _, task, _ in launcher.launches] == ["TASK_001", "TASK_002"]
    assert state.final_decision is DecisionStatus.REVIEW


def test_failure_on_task_two_stops_campaign(tmp_path: Path):
    runner, manifest, launcher, _, _ = kernel(tmp_path, scenarios={"TASK_002": "failure"})

    state = runner.run(manifest, authorization(), allocation_seconds=10_000)

    assert state.task_states["TASK_002"] is TaskState.FAILED
    assert state.task_states["TASK_003"] is TaskState.PLANNED
    assert len(launcher.launches) == 2


def test_low_time_blocks_task_three_without_attempt(tmp_path: Path):
    runner, manifest, launcher, _, workspace = kernel(tmp_path, runtime=700.0)

    state = runner.run(manifest, authorization(), allocation_seconds=4_000)

    assert state.task_states["TASK_001"] is TaskState.COMPLETED
    assert state.task_states["TASK_002"] is TaskState.COMPLETED
    assert state.task_states["TASK_003"] is TaskState.BLOCKED
    assert "TASK_003" not in state.attempt_counts
    assert [task for _, task, _ in launcher.launches] == ["TASK_001", "TASK_002"]
    task_three = workspace.campaign_path(manifest.campaign_id) / "tasks" / "TASK_003"
    assert not task_three.exists()


def test_interruption_resumes_new_attempt_same_allocation(tmp_path: Path):
    runner, manifest, launcher, slurm, workspace = kernel(
        tmp_path, scenarios={"TASK_002": "interruption"}
    )
    envelope = authorization()
    first = runner.run(manifest, envelope, allocation_seconds=10_000)
    allocation_id = first.allocation_id
    assert first.task_states["TASK_002"] is TaskState.INTERRUPTED

    launcher.set_scenario("TASK_002", "success")
    resumed = runner.run(manifest, envelope, allocation_seconds=10_000)

    assert resumed.final_decision is DecisionStatus.PASS
    assert resumed.attempt_counts["TASK_002"] == 2
    assert slurm.submissions == 1
    assert {item[0] for item in launcher.launches} == {allocation_id}
    task_two = workspace.campaign_path(manifest.campaign_id) / "tasks" / "TASK_002"
    assert (task_two / "attempt_001" / "stdout.txt").read_text() == "PARTIAL"
    assert (task_two / "attempt_002" / "stdout.txt").read_text() == "SIMULATED_SUCCESS\n"


def test_authorization_blocks_task_three_before_workspace_or_launcher(tmp_path: Path):
    runner, manifest, launcher, _, workspace = kernel(tmp_path)

    state = runner.run(
        manifest,
        authorization(targets=("TARGET_001", "TARGET_002")),
        allocation_seconds=10_000,
    )

    assert state.task_states["TASK_003"] is TaskState.BLOCKED
    assert [task for _, task, _ in launcher.launches] == ["TASK_001", "TASK_002"]
    assert not (workspace.campaign_path(manifest.campaign_id) / "tasks" / "TASK_003").exists()


def test_tampered_authorization_has_zero_campaign_side_effects(tmp_path: Path):
    runner, manifest, launcher, slurm, workspace = kernel(tmp_path)
    bad = AuthorizationEngine.tampered_copy(authorization(), issued_by="tampered")

    with pytest.raises(AuthorizationError, match="hash mismatch"):
        runner.run(manifest, bad, allocation_seconds=10_000)

    assert not workspace.campaign_path(manifest.campaign_id).exists()
    assert launcher.launches == []
    assert slurm.submissions == 0


def test_existing_campaign_rejects_different_immutable_authorization(tmp_path: Path):
    runner, manifest, _, _, workspace = kernel(tmp_path)
    original = authorization()
    workspace.prepare_campaign(manifest, original)
    now = datetime.now(timezone.utc)
    replacement = AuthorizationEngine.issue(
        authorization_id="AUTH_REPLACEMENT",
        campaign_id=manifest.campaign_id,
        allowed_task_types=("SIMULATED",),
        generic_targets=("TARGET_001", "TARGET_002", "TARGET_003"),
        forbidden_operations=("DELETE",),
        stop_on_review=True,
        issued_by="different-authority",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )

    with pytest.raises(IntegrityError, match="immutable"):
        workspace.prepare_campaign(manifest, replacement)


def test_completed_tasks_are_not_duplicated_on_second_run(tmp_path: Path):
    runner, manifest, launcher, slurm, _ = kernel(tmp_path)
    envelope = authorization()
    first = runner.run(manifest, envelope, allocation_seconds=10_000)
    launches = list(launcher.launches)

    second = runner.run(manifest, envelope, allocation_seconds=10_000)

    assert second.attempt_counts == first.attempt_counts
    assert launcher.launches == launches
    assert slurm.submissions == 1
