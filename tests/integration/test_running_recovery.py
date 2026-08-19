from qraft.models import CampaignState, EventRecord, TaskState, utc_now
from qraft.storage import EventStore, StateStore

from .test_simulated_campaign import authorization, kernel


def test_running_state_becomes_interrupted_before_new_attempt(tmp_path):
    runner, manifest, launcher, slurm, workspace = kernel(tmp_path)
    envelope = authorization()
    campaign = workspace.prepare_campaign(manifest, envelope)
    allocation = slurm.submit_allocation(manifest.campaign_id, 10_000)
    workspace.next_attempt(manifest.campaign_id, "TASK_001")
    state = CampaignState(
        manifest.campaign_id,
        allocation_id=allocation.allocation_id,
        task_states={"TASK_001": TaskState.RUNNING},
        attempt_counts={"TASK_001": 1},
    )
    events = EventStore(campaign / "events.jsonl", runner.fs)
    events.append(
        EventRecord(
            utc_now(), manifest.campaign_id, "TASK_001", "attempt_001",
            "TASK_STATE_CHANGED", None, "RUNNING", "simulated process crash"
        )
    )
    StateStore(campaign / "state.json", runner.fs).save(state)

    resumed = runner.run(manifest, envelope, allocation_seconds=10_000)

    assert resumed.task_states["TASK_001"] is TaskState.COMPLETED
    assert resumed.attempt_counts["TASK_001"] == 2
    messages = [event.message for event in events.read_all()]
    assert "running task recovered after process restart" in messages

