import pytest

from qraft.execution.controller_files import atomic_controller_json, read_controller_json
from qraft.execution.controller_state import (
    ControllerStateError, controller_state_manifest, previous_controller_owner,
)

OLD_BOOT = "00000000-0000-0000-0000-000000000001"
NEW_BOOT = "00000000-0000-0000-0000-000000000002"


def owned_state(tmp_path):
    state = tmp_path / "controller-state" / "hf1"
    state.mkdir(parents=True)
    closure = tmp_path / "work" / "hf1" / "attempt-0001" / ".qraft" / "controller-closure.json"
    atomic_controller_json(state / "owner.json", {
        "attempt_id": "attempt-0001", "authority_generation": None,
        "host": "localhost", "boot_id": OLD_BOOT, "supervisor_pid": 999999999,
        "supervisor_start_time_ticks": "1", "closure_ref": closure.relative_to(tmp_path).as_posix(),
    })
    atomic_controller_json(state / "checkpoint.json", {"native_id": "opaque", "state": "VALIDATED"})
    atomic_controller_json(closure.with_name("controller-state-manifest.json"), controller_state_manifest(state).to_mapping())
    return state, closure


def test_absent_pid_and_absent_closure_are_not_owner_death(tmp_path):
    state, _ = owned_state(tmp_path)
    with pytest.raises(ControllerStateError, match="PREVIOUS_OWNER_ALIVE"):
        previous_controller_owner(tmp_path, state, current_boot_id=OLD_BOOT, current_host="localhost")


@pytest.mark.parametrize("proof", ["CLOSED", "OWNER_DEAD_BY_BOOT_CHANGE"])
def test_positive_owner_death_and_sealed_state(tmp_path, proof):
    state, closure = owned_state(tmp_path)
    if proof == "CLOSED":
        atomic_controller_json(closure, {"state": "CLOSED", "method": "SUBREAPER_PIDFD", "remaining": []})
    previous = previous_controller_owner(tmp_path, state, current_boot_id=NEW_BOOT if proof != "CLOSED" else OLD_BOOT, current_host="localhost")
    assert previous["closure"] == proof
    assert previous["state_manifest_sha256"] == controller_state_manifest(state).sha256


def test_closed_owner_does_not_authorize_changed_native_state(tmp_path):
    state, closure = owned_state(tmp_path)
    atomic_controller_json(closure, {"state": "CLOSED", "method": "SUBREAPER_PIDFD", "remaining": []})
    (state / "checkpoint.json").write_text("{}")
    with pytest.raises(ControllerStateError, match="STATE_TAMPERED"):
        previous_controller_owner(tmp_path, state, current_boot_id=OLD_BOOT, current_host="localhost")


def test_state_without_an_owner_is_not_a_silent_fresh_start(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "checkpoint.json").write_text("{}")
    with pytest.raises(ControllerStateError, match="STATE_TAMPERED"):
        previous_controller_owner(tmp_path, state, current_boot_id="boot", current_host="localhost")


@pytest.mark.parametrize("field,value", [
    ("boot_id", "missing"), ("boot_id", None), ("supervisor_pid", True),
    ("supervisor_pid", -1), ("supervisor_start_time_ticks", "NaN"),
    ("supervisor_start_time_ticks", "01"), ("attempt_id", None),
    ("authority_generation", 2),
    ("boot_id", "-" * 36), ("boot_id", "0" * 36),
])
def test_corrupt_owner_identity_never_proves_death_even_if_state_is_sealed(tmp_path, field, value):
    state, closure = owned_state(tmp_path)
    owner = read_controller_json(state / "owner.json")
    owner[field] = value
    atomic_controller_json(state / "owner.json", owner)
    atomic_controller_json(closure.with_name("controller-state-manifest.json"),
                           controller_state_manifest(state).to_mapping())
    with pytest.raises(ControllerStateError, match="STATE_TAMPERED"):
        previous_controller_owner(tmp_path, state, current_boot_id=NEW_BOOT, current_host="localhost")
