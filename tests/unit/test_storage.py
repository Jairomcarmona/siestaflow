from __future__ import annotations

import json
from pathlib import Path

import pytest

from siestaflow.errors import IntegrityError, StateConflictError
from siestaflow.filesystem import RealFileSystem
from siestaflow.models import CampaignState, EventRecord, TaskState, utc_now
from siestaflow.storage import EventStore, StateStore


def test_atomic_state_write_round_trip_and_no_temp_residue(tmp_path: Path):
    store = StateStore(tmp_path / "state.json", RealFileSystem())
    state = CampaignState("CAMPAIGN_001", task_states={"TASK_001": TaskState.RUNNING})

    store.save(state)
    loaded = store.load()

    assert loaded.task_states == {"TASK_001": TaskState.RUNNING}
    assert loaded.revision == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_or_tampered_state_is_rejected(tmp_path: Path):
    path = tmp_path / "state.json"
    store = StateStore(path, RealFileSystem())
    store.save(CampaignState("CAMPAIGN_001"))
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    wrapper["payload"]["campaign_id"] = "TAMPERED"
    path.write_text(json.dumps(wrapper), encoding="utf-8")

    with pytest.raises(IntegrityError, match="checksum"):
        store.load()


def test_event_store_appends_and_reconstructs_state(tmp_path: Path):
    store = EventStore(tmp_path / "events.jsonl", RealFileSystem())
    store.append(EventRecord(utc_now(), "C", "T", "", "STATE", None, "PLANNED", "planned"))
    first_size = (tmp_path / "events.jsonl").stat().st_size
    store.append(EventRecord(utc_now(), "C", "T", "attempt_001", "STATE", "PLANNED", "RUNNING", "running"))

    assert (tmp_path / "events.jsonl").stat().st_size > first_size
    assert store.reconstructed_states() == {"T": TaskState.RUNNING}


def test_state_event_disagreement_fails_closed(tmp_path: Path):
    store = EventStore(tmp_path / "events.jsonl", RealFileSystem())
    store.append(EventRecord(utc_now(), "C", "T", "", "STATE", None, "PLANNED", "planned"))

    with pytest.raises(StateConflictError):
        store.assert_matches(CampaignState("C", task_states={"T": TaskState.COMPLETED}))

