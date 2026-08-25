from __future__ import annotations

import json
from pathlib import Path

import pytest

from qraft.execution.capability_runtime import load_runtime_state_payload

from tests.execution.test_capability_runtime import (
    RecordingLauncher,
    SyntheticCapability,
    node,
    registry_for,
    runtime,
    workflow,
)


def test_legacy_snapshot_without_journal_loads_unchanged(tmp_path: Path) -> None:
    compiled = workflow(tmp_path, (node("A"),))
    first = runtime(tmp_path, compiled, registry_for(SyntheticCapability()), RecordingLauncher())
    assert first.run().status == "COMPLETED"
    assert not first.journal_path.exists()

    restored = runtime(tmp_path, compiled, registry_for(SyntheticCapability()), RecordingLauncher())
    restored._load_or_initialize_state()
    assert restored._state["tasks"]["A"]["status"] == "COMPLETED"


def test_journal_recovers_multiple_local_mutations_after_restart(tmp_path: Path) -> None:
    compiled = workflow(tmp_path, (node("A"), node("B")))
    active = runtime(tmp_path, compiled, registry_for(SyntheticCapability()), RecordingLauncher())
    active._load_or_initialize_state()
    active._set_task("A", "RUNNING", "attempt reserved", attempts=1, last_attempt="attempt-0001")
    active._set_task("B", "BLOCKED", "failed dependency: A")
    assert active.journal_path.is_file()

    restored = runtime(tmp_path, compiled, registry_for(SyntheticCapability()), RecordingLauncher())
    restored._load_or_initialize_state()
    assert restored._state["tasks"]["A"]["status"] == "RUNNING"
    assert restored._state["tasks"]["A"]["last_attempt"] == "attempt-0001"
    assert restored._state["tasks"]["B"]["status"] == "BLOCKED"
    assert restored._state["revision"] == 2


def test_clean_completion_compacts_journal_after_final_snapshot(tmp_path: Path) -> None:
    compiled = workflow(tmp_path, (node("A"),))
    current = runtime(tmp_path, compiled, registry_for(SyntheticCapability()), RecordingLauncher())
    assert current.run().status == "COMPLETED"
    assert not current.journal_path.exists()
    wrapper = json.loads(current.state_path.read_text(encoding="utf-8"))
    assert wrapper["schema_version"] == current.STATE_SCHEMA
    assert wrapper["payload"]["status"] == "COMPLETED"
    assert wrapper["payload"]["revision"] > 0


def test_corrupt_journal_is_rejected_without_silent_recovery(tmp_path: Path) -> None:
    compiled = workflow(tmp_path, (node("A"),))
    active = runtime(tmp_path, compiled, registry_for(SyntheticCapability()), RecordingLauncher())
    active._load_or_initialize_state()
    active._set_task("A", "RUNNING", "attempt reserved", attempts=1)
    active.journal_path.write_text(
        active.journal_path.read_text(encoding="utf-8") + '{"truncated":',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="journal JSON"):
        load_runtime_state_payload(active.state_path)
