from __future__ import annotations

import json
from pathlib import Path

from tests.characterization.m9_mass_screening_harness import (
    MetricRecordingLauncher,
    candidate_identity,
    candidate_metric,
    candidate_summary,
    compile_campaign,
    eval_task_id,
    invoke,
    score_task_id,
    summary_digest,
)
from tests.execution.test_capability_runtime import OPAQUE_FAIL


def test_adversarial_candidate_identifiers_have_distinct_identity_paths_and_summary_order(tmp_path: Path) -> None:
    ids = ("candidate-1", "candidate-01", "candidate-10")
    compiled, task_candidates = compile_campaign(tmp_path / "source", ids, two_stage=False)
    identities = {candidate_id: candidate_identity(candidate_id).fingerprint for candidate_id in ids}
    assert len(set(identities.values())) == len(ids)
    root = tmp_path / "runtime"
    invocation = invoke(tmp_path / "source", root, compiled, task_candidates, MetricRecordingLauncher(task_candidates))
    result = invocation.result
    assert result.status == "COMPLETED"
    assert [task.task_id for task in compiled.tasks] == sorted(
        eval_task_id(candidate_id) for candidate_id in ids
    )
    for candidate_id in ids:
        result_path = root / "work" / eval_task_id(candidate_id) / "attempt-0001" / "result.dat"
        assert result_path.is_file()
        assert json.loads(result_path.read_text(encoding="utf-8")) == {
            "candidate_id": candidate_id,
            "scientific_metric": candidate_metric(candidate_id),
            "task_id": eval_task_id(candidate_id),
        }
        assert invocation.capability.consumed_candidate_ids[eval_task_id(candidate_id)] == candidate_id
    rows = candidate_summary(root, ids, two_stage=False)
    assert [row["candidate_id"] for row in rows] == sorted(ids)
    assert [row["rank"] for row in sorted(rows, key=lambda row: (row["scientific_metric"], row["candidate_id"]))] == [1, 2, 3]


def test_failure_isolation_recovery_reuses_siblings_and_matches_clean_summary(tmp_path: Path) -> None:
    ids = tuple(f"candidate-{index:02d}" for index in range(1, 21))
    compiled, task_candidates = compile_campaign(tmp_path / "source", ids, two_stage=True)
    root = tmp_path / "runtime"
    failed_candidate = "candidate-07"
    first = invoke(
        tmp_path / "source", root, compiled, task_candidates,
        MetricRecordingLauncher(task_candidates, {eval_task_id(failed_candidate): [(OPAQUE_FAIL, 0, False, True)]}),
    ).result
    assert first.status == "FAILED"
    rows = candidate_summary(root, ids, two_stage=True)
    failed_row = next(row for row in rows if row["candidate_id"] == failed_candidate)
    assert failed_row["status"] == "BLOCKED"
    assert failed_row["rank"] is None
    assert all(row["status"] == "COMPLETED" for row in rows if row["candidate_id"] != failed_candidate)
    retry_launcher = MetricRecordingLauncher(task_candidates)
    second = invoke(tmp_path / "source", root, compiled, task_candidates, retry_launcher).result
    assert second.status == "COMPLETED"
    assert len(second.reused_nodes) == (2 * len(ids)) - 2
    assert sorted(spec.task_id for spec in retry_launcher.launches) == sorted([eval_task_id(failed_candidate), score_task_id(failed_candidate)])
    assert (root / "work" / eval_task_id(failed_candidate) / "attempt-0001" / "attempt.json").is_file()
    assert (root / "work" / eval_task_id(failed_candidate) / "attempt-0002" / "attempt.json").is_file()
    recovered = candidate_summary(root, ids, two_stage=True)

    clean_compiled, clean_candidates = compile_campaign(tmp_path / "clean-source", ids, two_stage=True)
    clean_root = tmp_path / "clean-runtime"
    assert invoke(tmp_path / "clean-source", clean_root, clean_compiled, clean_candidates, MetricRecordingLauncher(clean_candidates)).result.status == "COMPLETED"
    assert summary_digest(recovered) == summary_digest(candidate_summary(clean_root, ids, two_stage=True))


def test_corrupt_attempt_rejects_reuse_for_only_the_affected_candidate(tmp_path: Path) -> None:
    ids = ("candidate-0001", "candidate-0002", "candidate-0003")
    compiled, task_candidates = compile_campaign(tmp_path / "source", ids, two_stage=False)
    root = tmp_path / "runtime"
    assert invoke(tmp_path / "source", root, compiled, task_candidates, MetricRecordingLauncher(task_candidates)).result.status == "COMPLETED"
    corrupted = "candidate-0002"
    artifact = root / "work" / eval_task_id(corrupted) / "attempt-0001" / "result.dat"
    artifact.write_text("corrupted\n", encoding="utf-8")

    retry_launcher = MetricRecordingLauncher(task_candidates)
    resumed = invoke(tmp_path / "source", root, compiled, task_candidates, retry_launcher).result
    assert resumed.status == "COMPLETED"
    assert resumed.reused_nodes == (eval_task_id("candidate-0001"), eval_task_id("candidate-0003"))
    assert [item.task_id for item in retry_launcher.launches] == [eval_task_id(corrupted)]
    assert (root / "work" / eval_task_id(corrupted) / "attempt-0002" / "attempt.json").is_file()
    for candidate_id in ("candidate-0001", "candidate-0003"):
        assert not (root / "work" / eval_task_id(candidate_id) / "attempt-0002").exists()
