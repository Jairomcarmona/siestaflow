"""Versioned, manual-backed SIESTA validation rule catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from ...contracts import (
    ContractVersion,
    EvidenceClass,
    FindingScope,
    RuleDescriptor,
    contract_sha256,
)


@dataclass(frozen=True)
class SiestaRuleEntry:
    descriptor: RuleDescriptor
    reference: str

    def __post_init__(self) -> None:
        if not self.reference.strip():
            raise ValueError("validation rule reference must be non-empty")


@dataclass(frozen=True)
class SiestaValidationCatalog:
    schema_version: str
    engine: str
    engine_version: str
    source_url: str
    source_accessed: str
    rules: tuple[SiestaRuleEntry, ...]
    sha256: str

    @classmethod
    def load_default(cls) -> "SiestaValidationCatalog":
        resource = files("siestaflow.engines.siesta.data").joinpath(
            "validation_rules_5.4.2.json"
        )
        with resource.open("r", encoding="utf-8") as handle:
            return cls.from_data(json.load(handle))

    @classmethod
    def load(cls, path: Path) -> "SiestaValidationCatalog":
        return cls.from_data(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_data(
        cls,
        payload: Mapping[str, Any],
    ) -> "SiestaValidationCatalog":
        allowed = {
            "schema_version",
            "engine",
            "engine_version",
            "source_url",
            "source_accessed",
            "rules",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(
                f"unknown validation catalog fields: {sorted(unknown)}"
            )
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported validation catalog schema")
        if payload.get("engine") != "siesta":
            raise ValueError("validation catalog engine must be siesta")
        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ValueError("validation catalog requires non-empty rules")
        entries: list[SiestaRuleEntry] = []
        for raw in raw_rules:
            if not isinstance(raw, Mapping):
                raise ValueError("validation catalog rules must be mappings")
            required = {
                "rule_id",
                "version",
                "summary",
                "evidence_class",
                "scopes",
                "supported_subjects",
                "deterministic",
                "reference",
            }
            if set(raw) != required:
                raise ValueError(
                    "validation catalog rule fields mismatch for "
                    f"{raw.get('rule_id', '<unknown>')}"
                )
            descriptor = RuleDescriptor(
                rule_id=str(raw["rule_id"]),
                version=ContractVersion.parse(str(raw["version"])),
                summary=str(raw["summary"]),
                evidence_class=EvidenceClass(str(raw["evidence_class"])),
                scopes=tuple(
                    FindingScope(str(item)) for item in raw["scopes"]
                ),
                supported_subjects=tuple(
                    str(item) for item in raw["supported_subjects"]
                ),
                deterministic=bool(raw["deterministic"]),
            )
            entries.append(
                SiestaRuleEntry(descriptor, str(raw["reference"]))
            )
        identifiers = [item.descriptor.rule_id for item in entries]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("validation catalog rule ids must be unique")
        canonical_payload = {
            key: payload[key]
            for key in (
                "schema_version",
                "engine",
                "engine_version",
                "source_url",
                "source_accessed",
                "rules",
            )
        }
        return cls(
            schema_version="1.0",
            engine="siesta",
            engine_version=str(payload["engine_version"]),
            source_url=str(payload["source_url"]),
            source_accessed=str(payload["source_accessed"]),
            rules=tuple(entries),
            sha256=contract_sha256(canonical_payload),
        )

    def require(self, rule_id: str) -> SiestaRuleEntry:
        for entry in self.rules:
            if entry.descriptor.rule_id == rule_id:
                return entry
        raise KeyError(f"validation rule is not registered: {rule_id}")

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "source_url": self.source_url,
            "source_accessed": self.source_accessed,
            "ruleset_sha256": self.sha256,
            "rules": [
                {
                    "rule_id": item.descriptor.rule_id,
                    "version": str(item.descriptor.version),
                    "summary": item.descriptor.summary,
                    "evidence_class": item.descriptor.evidence_class.value,
                    "scopes": [
                        scope.value for scope in item.descriptor.scopes
                    ],
                    "deterministic": item.descriptor.deterministic,
                    "reference": item.reference,
                }
                for item in self.rules
            ],
        }
