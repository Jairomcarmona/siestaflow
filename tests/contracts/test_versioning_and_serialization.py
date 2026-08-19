from __future__ import annotations

import json

import pytest

from qraft.contracts import (
    ContractCompatibilityError,
    ContractEnvelope,
    ContractIntegrityError,
    ContractRef,
    ContractVersion,
    canonical_json,
)


def test_contract_version_has_explicit_minor_compatibility() -> None:
    provided = ContractVersion.parse("1.3")
    assert provided.supports("1.0")
    assert provided.supports("1.3")
    assert not provided.supports("1.4")
    assert not provided.supports("2.0")
    with pytest.raises(ContractCompatibilityError):
        provided.require_supports("2.0")


def test_contract_reference_requires_namespaced_identifier() -> None:
    reference = ContractRef.parse("siestaflow.validation-report@1.0")
    assert str(reference) == "siestaflow.validation-report@1.0"
    with pytest.raises(ValueError):
        ContractRef.parse("validation@1.0")


def test_envelope_is_canonical_immutable_and_hash_bound() -> None:
    reference = ContractRef.parse("siestaflow.validation-report@1.0")
    first = ContractEnvelope.create(
        reference,
        producer="tests",
        payload={"b": [2, 1], "a": "value"},
        extensions={"org.example.note": {"enabled": True}},
    )
    second = ContractEnvelope.create(
        reference,
        producer="tests",
        payload={"a": "value", "b": [2, 1]},
        extensions={"org.example.note": {"enabled": True}},
    )
    assert first.content_sha256 == second.content_sha256
    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    with pytest.raises(TypeError):
        first.payload["a"] = "changed"  # type: ignore[index]

    tampered = json.loads(json.dumps(first.to_dict()))
    tampered["payload"]["a"] = "changed"
    with pytest.raises(ContractIntegrityError):
        ContractEnvelope.from_dict(tampered)


def test_envelope_rejects_top_level_and_unnamespaced_extensions() -> None:
    reference = ContractRef.parse("siestaflow.workflow-event@1.0")
    with pytest.raises(ValueError):
        ContractEnvelope.create(
            reference,
            producer="tests",
            payload={},
            extensions={"custom": True},
        )
    envelope = ContractEnvelope.create(reference, producer="tests", payload={})
    data = envelope.to_dict()
    data["new_field"] = True
    with pytest.raises(ContractIntegrityError):
        ContractEnvelope.from_dict(data)


def test_nonfinite_float_is_never_serialized() -> None:
    with pytest.raises(ValueError):
        canonical_json({"energy": float("nan")})

