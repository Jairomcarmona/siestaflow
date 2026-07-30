from siestaflow.models import DecisionStatus, TaskState

from tests.integration.test_simulated_campaign import authorization, kernel


def test_m1_end_to_end_smoke(tmp_path):
    runner, manifest, launcher, slurm, workspace = kernel(tmp_path)

    state = runner.run(manifest, authorization(), allocation_seconds=10_000)

    assert state.final_decision is DecisionStatus.PASS
    assert all(value is TaskState.COMPLETED for value in state.task_states.values())
    assert slurm.submissions == 1
    assert len(launcher.launches) == 3
    campaign = workspace.campaign_path(manifest.campaign_id)
    assert (campaign / "state.json").is_file()
    assert (campaign / "events.jsonl").is_file()
    assert (campaign / "artifacts.jsonl").is_file()

