"""Native conformance vectors and malformed durable evidence, without SIESTA."""

import copy
import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest

from qraft.execution.controller_contracts import (
    ControllerContractError, controller_descriptor_digest, parse_controller_json,
    read_controller_ledger, validate_controller_descriptor,
)
from qraft.execution.controller_ledger import evaluate_controller_ledger


_FIXTURES = Path(__file__).parents[1] / "fixtures" / "controller-ledger"
_VECTORS = json.loads((_FIXTURES / "cases.json").read_bytes())
_RESERVATION = json.loads((_FIXTURES / "reservation.json").read_bytes())


@pytest.mark.parametrize("case", _VECTORS["cases"], ids=lambda c: c["name"])
def test_normative_ledger_vectors(case):
    verdict = evaluate_controller_ledger(_VECTORS["reservation"], case["attempts"])
    assert verdict.code == case["expect"]
    assert verdict.accepted == (case["expect"] == "ACCEPT")
    assert (verdict.reason is None) == verdict.accepted


def test_previous_attempt_uses_its_own_deadline_and_allocated_host():
    attempts = copy.deepcopy(_VECTORS["cases"][0]["attempts"])
    attempt_id = attempts[0]["attempt_id"]
    original = _VECTORS["reservation"]
    later = dict(original, stop_launching_at="2020-01-01T00:00:00Z", hosts=["different-host"])
    assert evaluate_controller_ledger(later, attempts).code == "INTENT_AFTER_DEADLINE"
    verdict = evaluate_controller_ledger(later, attempts, attempt_reservations={attempt_id: original})
    assert verdict.accepted


def test_later_deadline_cannot_launder_old_attempt_violation():
    attempts = copy.deepcopy(_VECTORS["cases"][0]["attempts"])
    attempt_id = attempts[0]["attempt_id"]
    original = dict(_VECTORS["reservation"], stop_launching_at="2020-01-01T00:00:00Z")
    verdict = evaluate_controller_ledger(_VECTORS["reservation"], attempts,
                                        attempt_reservations={attempt_id: original})
    assert verdict.code == "INTENT_AFTER_DEADLINE"


def test_history_requires_exact_coverage_and_unique_attempts():
    attempts = copy.deepcopy(_VECTORS["cases"][0]["attempts"])
    assert evaluate_controller_ledger(_VECTORS["reservation"], attempts,
                                     attempt_reservations={}).code == "LEDGER_MALFORMED"
    assert evaluate_controller_ledger(_VECTORS["reservation"], attempts * 2).code == "LEDGER_MALFORMED"


def test_schema_bytes_identical_to_normative_contracts():
    expected = {
        "defs.schema.json": "2c4245ded2988c8ffeb5f9bed55fcac0d0aa57cf2805277a67b0408edebfb5f4",
        "qraft-controller-reservation.schema.json": "0c1694dd725d1d0eb8ce7e8a23bd537547629ab3dc463e158567c9cb50c3df56",
        "qraft-controller-ledger-entry.schema.json": "e93daa8ca193153563eec4c563da3360e2870d1228c8ceb8a62b6efb90dad2b3",
        "qraft-controller-resume-verdict.schema.json": "054993007e3bb579007a91262d9ea30a577b68b5273d9e2f675cc5c2fd8a1b54",
    }
    for name, digest in expected.items():
        assert hashlib.sha256(files("qraft.execution.controller_schemas").joinpath(name).read_bytes()).hexdigest() == digest


def test_descriptor_and_digest_reject_tampering():
    validate_controller_descriptor(_RESERVATION)
    assert len(controller_descriptor_digest(_RESERVATION)) == 64
    changed = copy.deepcopy(_RESERVATION)
    changed["reserved"]["scheduler_cpus_on_host"]["value"] = 3
    with pytest.raises(ControllerContractError, match="ALLOCATION_MISMATCH"):
        controller_descriptor_digest(changed)
    changed = copy.deepcopy(_RESERVATION)
    changed["paths"]["state_dir"] = "../outside"
    with pytest.raises(ControllerContractError):
        validate_controller_descriptor(changed)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'\xff'])
def test_ambiguous_json_rejected(raw):
    with pytest.raises(ControllerContractError):
        parse_controller_json(raw)


def test_torn_line_never_silently_discarded(tmp_path):
    entry = _VECTORS["cases"][0]["attempts"][0]["lines"][0]
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(json.dumps(entry).encode() + b"\n")
    assert read_controller_ledger(path) == (entry,)
    path.write_bytes(json.dumps(entry).encode())
    with pytest.raises(ControllerContractError, match="incomplete"):
        read_controller_ledger(path)


def test_nanosecond_deadline_has_no_float_or_millisecond_rounding():
    entry = copy.deepcopy(_VECTORS["cases"][0]["attempts"][0]["lines"][0])
    entry["at"] = "2026-10-11T19:30:00.000000002Z"
    reservation = dict(_VECTORS["reservation"], stop_launching_at="2026-10-11T19:30:00.000000001Z")
    verdict = evaluate_controller_ledger(reservation, [{"attempt_id": entry["attempt_id"], "end": "INTERRUPTED", "lines": [entry]}])
    assert verdict.code == "INTENT_AFTER_DEADLINE"
    assert verdict.reason == "CONTROLLER_RESERVATION_VIOLATED"


def test_invalid_calendar_rejected_without_optional_format_dependencies():
    changed = copy.deepcopy(_RESERVATION)
    changed["deadline"]["stop_launching_at"] = "2026-02-31T19:30:00Z"
    with pytest.raises(ControllerContractError):
        validate_controller_descriptor(changed)
