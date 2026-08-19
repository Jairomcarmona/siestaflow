"""Canonical serialization and integrity envelopes for public contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .versioning import ContractRef, ContractVersion


_EXTENSION_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
_ENVELOPE_FIELDS = {
    "contract",
    "producer",
    "payload",
    "extensions",
    "content_sha256",
}


class ContractIntegrityError(ValueError):
    """Raised for malformed, unsupported, or hash-invalid contract data."""


def canonical_primitive(value: Any) -> Any:
    """Normalize supported values to a deterministic JSON representation."""

    if isinstance(value, Enum):
        return canonical_primitive(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: canonical_primitive(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("contract mapping keys must be strings")
            result[key] = canonical_primitive(item)
        return result
    if isinstance(value, (list, tuple)):
        return [canonical_primitive(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("contract floats must be finite")
        return value
    raise TypeError(f"unsupported contract value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_primitive(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def contract_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _freeze(value: Any) -> Any:
    normalized = canonical_primitive(value)
    if isinstance(normalized, dict):
        return MappingProxyType({key: _freeze(item) for key, item in normalized.items()})
    if isinstance(normalized, list):
        return tuple(_freeze(item) for item in normalized)
    return normalized


def validate_extensions(extensions: Mapping[str, Any]) -> None:
    for name in extensions:
        if not _EXTENSION_NAME.fullmatch(name):
            raise ValueError(
                f"extension keys must be lowercase namespaced identifiers: {name!r}"
            )


class ContractEnvelope:
    """Immutable, hash-bound transport envelope.

    Unknown top-level fields are rejected.  Optional evolution data must live
    under a namespaced key in ``extensions``.
    """

    __slots__ = (
        "contract",
        "producer",
        "payload",
        "extensions",
        "content_sha256",
        "_sealed",
    )

    def __init__(
        self,
        *,
        contract: ContractRef,
        producer: str,
        payload: Mapping[str, Any],
        extensions: Mapping[str, Any],
        content_sha256: str,
    ) -> None:
        if not str(producer).strip():
            raise ValueError("producer must be non-empty")
        validate_extensions(extensions)
        object.__setattr__(self, "contract", contract)
        object.__setattr__(self, "producer", str(producer).strip())
        object.__setattr__(self, "payload", _freeze(payload))
        object.__setattr__(self, "extensions", _freeze(extensions))
        object.__setattr__(self, "content_sha256", str(content_sha256).lower())
        object.__setattr__(self, "_sealed", True)
        self.verify()

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("contract envelopes are immutable")
        object.__setattr__(self, name, value)

    @classmethod
    def create(
        cls,
        contract: ContractRef,
        *,
        producer: str,
        payload: Mapping[str, Any],
        extensions: Mapping[str, Any] | None = None,
    ) -> "ContractEnvelope":
        extension_data = dict(extensions or {})
        body = {
            "contract": contract.to_dict(),
            "producer": str(producer).strip(),
            "payload": payload,
            "extensions": extension_data,
        }
        return cls(
            contract=contract,
            producer=producer,
            payload=payload,
            extensions=extension_data,
            content_sha256=contract_sha256(body),
        )

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        required_contract: ContractRef | None = None,
    ) -> "ContractEnvelope":
        if set(data) != _ENVELOPE_FIELDS:
            difference = sorted(set(data) ^ _ENVELOPE_FIELDS)
            raise ContractIntegrityError(
                f"invalid contract envelope fields: {difference}"
            )
        contract_data = data.get("contract")
        if not isinstance(contract_data, Mapping):
            raise ContractIntegrityError("contract must be a mapping")
        try:
            contract = ContractRef(
                str(contract_data["name"]),
                ContractVersion.parse(str(contract_data["version"])),
            )
            payload = data["payload"]
            extensions = data["extensions"]
            if not isinstance(payload, Mapping) or not isinstance(extensions, Mapping):
                raise TypeError("payload and extensions must be mappings")
            envelope = cls(
                contract=contract,
                producer=str(data["producer"]),
                payload=payload,
                extensions=extensions,
                content_sha256=str(data["content_sha256"]),
            )
            if required_contract is not None:
                envelope.contract.require_satisfies(required_contract)
            return envelope
        except ContractIntegrityError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractIntegrityError(f"invalid contract envelope: {exc}") from exc

    def _body(self) -> dict[str, Any]:
        return {
            "contract": self.contract.to_dict(),
            "producer": self.producer,
            "payload": self.payload,
            "extensions": self.extensions,
        }

    def verify(self) -> None:
        expected = contract_sha256(self._body())
        if self.content_sha256 != expected:
            raise ContractIntegrityError("contract envelope checksum mismatch")

    def to_dict(self) -> dict[str, Any]:
        body = canonical_primitive(self._body())
        body["content_sha256"] = self.content_sha256
        return body
