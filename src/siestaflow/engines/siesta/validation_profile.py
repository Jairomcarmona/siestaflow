"""Researcher-declared context for non-universal SIESTA review rules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ...contracts import contract_sha256


_PERIODICITIES = {"unknown", "molecule", "chain", "slab", "bulk"}
_OUTPUTS = {"bader"}
_LIMITS = {"max_kpoints", "max_atoms_times_kpoints"}


@dataclass(frozen=True)
class SiestaValidationProfile:
    profile_id: str
    periodicity: str = "unknown"
    required_outputs: tuple[str, ...] = ()
    review_limits: Mapping[str, int] = field(default_factory=dict)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("validation profile requires profile_id")
        if self.schema_version != "1.0":
            raise ValueError("unsupported validation profile schema")
        if self.periodicity not in _PERIODICITIES:
            raise ValueError(
                f"unsupported periodicity: {self.periodicity}"
            )
        unknown_outputs = set(self.required_outputs) - _OUTPUTS
        if unknown_outputs:
            raise ValueError(
                f"unsupported required outputs: {sorted(unknown_outputs)}"
            )
        unknown_limits = set(self.review_limits) - _LIMITS
        if unknown_limits:
            raise ValueError(
                f"unsupported review limits: {sorted(unknown_limits)}"
            )
        for name, value in self.review_limits.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"review limit {name} must be a positive integer"
                )

    @classmethod
    def load(cls, path: Path) -> "SiestaValidationProfile":
        data = _load_mapping(path)
        allowed = {
            "schema_version",
            "profile_id",
            "periodicity",
            "required_outputs",
            "review_limits",
        }
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(
                f"unknown validation profile fields: {sorted(unknown)}"
            )
        return cls(
            schema_version=str(data.get("schema_version", "1.0")),
            profile_id=str(data.get("profile_id", "")).strip(),
            periodicity=str(data.get("periodicity", "unknown")).strip(),
            required_outputs=tuple(
                str(item).strip()
                for item in data.get("required_outputs", ())
            ),
            review_limits=dict(data.get("review_limits", {})),
        )

    @property
    def sha256(self) -> str:
        return contract_sha256(
            {
                "schema_version": self.schema_version,
                "profile_id": self.profile_id,
                "periodicity": self.periodicity,
                "required_outputs": self.required_outputs,
                "review_limits": dict(self.review_limits),
            }
        )


def _load_mapping(path: Path) -> Mapping[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"validation profile does not exist: {resolved}"
        )
    text = resolved.read_text(encoding="utf-8")
    if resolved.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError(
                "YAML validation profiles require PyYAML; use JSON instead"
            ) from exc
        value = yaml.safe_load(text)
    if not isinstance(value, Mapping):
        raise ValueError("validation profile root must be a mapping")
    return value
