"""Basic planner and sequential campaign runner for one fake allocation."""

from __future__ import annotations

from pathlib import Path

from .authorization import AuthorizationEngine
from .errors import AuthorizationError, IntegrityError
from .filesystem import FileSystem, validate_identifier
from .gates import GateEngine
from .hpc import BudgetStatus, FakeSlurmClient, ProcessLauncher, SlurmJobState, TimeBudget
from .models import (
    AuthorizationEnvelope,
    CampaignManifest,
    CampaignState,
    DecisionStatus,
    EventRecord,
    RuntimeEstimate,
    TaskAttempt,
    TaskSpec,
    TaskState,
    primitive,
    utc_now,
)
from .storage import ArtifactStore, EventStore, StateStore
from .workspace import WorkspaceManager


class BasicCampaignPlanner:
    def create(
        self,
        *,
        campaign_id: str,
        project_id: str,
        tasks: list[TaskSpec] | tuple[TaskSpec, ...],
    ) -> CampaignManifest:
        validate_identifier(campaign_id, field_name="campaign_id")
        validate_identifier(project_id, field_name="project_id")
        ids: set[str] = set()
        for task in tasks:
            validate_identifier(task.task_id, field_name="task_id")
            validate_identifier(task.task_type, field_name="task_type")
            validate_identifier(task.target_id, field_name="target_id")
            if task.task_id in ids:
                raise ValueError(f"duplicate task id: {task.task_id}")
            if not task.command:
                raise ValueError(f"task command is empty: {task.task_id}")
            if task.estimated_runtime_seconds is not None and task.estimated_runtime_seconds <= 0:
                raise ValueError(f"task runtime estimate must be positive: {task.task_id}")
            ids.add(task.task_id)
        if not tasks:
            raise ValueError("campaign requires at least one task")
        return CampaignManifest(campaign_id, project_id, tuple(tasks))


class CampaignRunner:
    """Execute authorized fake tasks sequentially without releasing allocation."""

    def __init__(
        self,
        *,
        workspace: WorkspaceManager,
        filesystem: FileSystem,
        authorization: AuthorizationEngine,
        gates: GateEngine,
        launcher: ProcessLauncher,
        slurm: FakeSlurmClient,
        time_budget: TimeBudget,
    ) -> None:
        self.workspace = workspace
        self.fs = filesystem
        self.authorization = authorization
        self.gates = gates
        self.launcher = launcher
        self.slurm = slurm
        self.time_budget = time_budget

    def run(
        self,
        manifest: CampaignManifest,
        envelope: AuthorizationEnvelope,
        *,
        allocation_seconds: float,
    ) -> CampaignState:
        # Envelope integrity/staleness is checked before any workspace side effect.
        self.authorization.verify(envelope)
        if envelope.campaign_id != manifest.campaign_id:
            raise AuthorizationError("authorization belongs to another campaign")

        campaign_path = self.workspace.prepare_campaign(manifest, envelope)
        state_store = StateStore(campaign_path / "state.json", self.fs)
        events = EventStore(campaign_path / "events.jsonl", self.fs)
        artifacts = ArtifactStore(campaign_path / "artifacts.jsonl", self.fs)

        if self.fs.exists(state_store.path):
            state = state_store.load()
            if state.campaign_id != manifest.campaign_id:
                raise IntegrityError("state belongs to another campaign")
            events.assert_matches(state)
        else:
            state = CampaignState(campaign_id=manifest.campaign_id)
            for task in manifest.tasks:
                self._transition(state, events, state_store, task.task_id, "", TaskState.PLANNED, "task planned")

        if state.allocation_id is None:
            allocation = self.slurm.submit_allocation(manifest.campaign_id, allocation_seconds)
            state.allocation_id = allocation.allocation_id
            state_store.save(state)
        else:
            allocation = self.slurm.get_allocation(state.allocation_id)

        # A process that died while RUNNING is never silently treated as complete.
        for task in manifest.tasks:
            if state.task_states.get(task.task_id) is TaskState.RUNNING:
                self._transition(
                    state,
                    events,
                    state_store,
                    task.task_id,
                    self._last_attempt_id(state, task.task_id),
                    TaskState.INTERRUPTED,
                    "running task recovered after process restart",
                )

        for task in manifest.tasks:
            current = state.task_states.get(task.task_id, TaskState.PLANNED)
            if current is TaskState.COMPLETED:
                continue
            if current in {TaskState.REVIEW, TaskState.FAILED, TaskState.BLOCKED}:
                break

            authorization = self.authorization.authorize(envelope, task)
            if authorization.status is not DecisionStatus.PASS:
                self._transition(
                    state,
                    events,
                    state_store,
                    task.task_id,
                    "",
                    TaskState.BLOCKED,
                    authorization.reason,
                    {"gate": primitive(authorization)},
                )
                state.final_decision = DecisionStatus.BLOCKED
                state_store.save(state)
                break

            estimate = RuntimeEstimate(
                estimated_seconds=task.estimated_runtime_seconds,
                source="authorized_task_spec",
                authorized=task.estimated_runtime_seconds is not None,
            )
            budget = self.time_budget.can_start(
                estimate,
                self.slurm.remaining_time(allocation.allocation_id),
            )
            if budget.status is not BudgetStatus.ALLOW:
                self._transition(
                    state,
                    events,
                    state_store,
                    task.task_id,
                    "",
                    TaskState.BLOCKED,
                    budget.reason,
                    {"time_budget": primitive(budget)},
                )
                state.final_decision = DecisionStatus.BLOCKED
                state_store.save(state)
                break

            record = self.workspace.next_attempt(manifest.campaign_id, task.task_id)
            state.attempt_counts[task.task_id] = state.attempt_counts.get(task.task_id, 0) + 1
            attempt = TaskAttempt(
                campaign_id=manifest.campaign_id,
                task_id=task.task_id,
                attempt_id=record.attempt_id,
                allocation_id=allocation.allocation_id,
                workspace=record.path,
            )
            self._transition(state, events, state_store, task.task_id, record.attempt_id, TaskState.PREPARED, "attempt prepared")
            self._transition(state, events, state_store, task.task_id, record.attempt_id, TaskState.RUNNING, "fake launcher started")

            result = self.launcher.launch(task, attempt, self.slurm.get_allocation(allocation.allocation_id))
            attempt_path = Path(record.path)
            self.fs.write_text(attempt_path / "stdout.txt", result.stdout)
            self.fs.write_text(attempt_path / "stderr.txt", result.stderr)
            artifacts.register_text(
                campaign_id=manifest.campaign_id,
                task_id=task.task_id,
                attempt_id=record.attempt_id,
                relative_path=f"tasks/{task.task_id}/{record.attempt_id}/stdout.txt",
                content=result.stdout,
            )
            artifacts.register_text(
                campaign_id=manifest.campaign_id,
                task_id=task.task_id,
                attempt_id=record.attempt_id,
                relative_path=f"tasks/{task.task_id}/{record.attempt_id}/stderr.txt",
                content=result.stderr,
            )
            state.results[task.task_id] = primitive(result)
            self.slurm.consume(allocation.allocation_id, result.runtime_seconds)

            gate = self.gates.evaluate(result)
            if gate.status is DecisionStatus.PASS:
                next_state = TaskState.COMPLETED
            elif gate.status is DecisionStatus.REVIEW:
                next_state = TaskState.REVIEW
            elif gate.status is DecisionStatus.FAIL:
                next_state = TaskState.FAILED
            elif result.failure.value == "INTERRUPTED":
                next_state = TaskState.INTERRUPTED
            else:
                next_state = TaskState.BLOCKED
            self._transition(
                state,
                events,
                state_store,
                task.task_id,
                record.attempt_id,
                next_state,
                gate.reason,
                {"gate": primitive(gate)},
            )
            state.final_decision = gate.status
            state_store.save(state)
            if gate.status is not DecisionStatus.PASS:
                break

        if all(state.task_states.get(task.task_id) is TaskState.COMPLETED for task in manifest.tasks):
            state.final_decision = DecisionStatus.PASS
            state_store.save(state)
            self.slurm.end_allocation(allocation.allocation_id, SlurmJobState.COMPLETED)
        return state

    @staticmethod
    def _last_attempt_id(state: CampaignState, task_id: str) -> str:
        count = state.attempt_counts.get(task_id, 0)
        return f"attempt_{count:03d}" if count else ""

    @staticmethod
    def _transition(
        state: CampaignState,
        events: EventStore,
        state_store: StateStore,
        task_id: str,
        attempt_id: str,
        new_state: TaskState,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        previous = state.task_states.get(task_id)
        event = EventRecord(
            timestamp=utc_now(),
            campaign_id=state.campaign_id,
            task_id=task_id,
            attempt_id=attempt_id,
            event_type="TASK_STATE_CHANGED",
            previous_state=previous.value if previous else None,
            new_state=new_state.value,
            message=message,
            metadata=metadata or {},
        )
        events.append(event)
        state.task_states[task_id] = new_state
        state_store.save(state)
