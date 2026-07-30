"""Small, manual-backed operational FDF registry."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .models import FDFRegistryEntry, MutableStatus, normalize_label


class FDFRegistry:
    def __init__(self, entries: tuple[FDFRegistryEntry, ...]) -> None:
        self.entries = entries
        self._by_name = {normalize_label(entry.canonical_name): entry for entry in entries}

    @classmethod
    def load_default(cls) -> "FDFRegistry":
        resource = files("siestaflow.engines.siesta.data").joinpath("supported_fdf_registry_5.4.2.json")
        with resource.open("r", encoding="utf-8") as handle:
            return cls.from_data(json.load(handle))

    @classmethod
    def load(cls, path: Path) -> "FDFRegistry":
        return cls.from_data(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_data(cls, data: list[dict[str, str]]) -> "FDFRegistry":
        entries = tuple(FDFRegistryEntry(
            canonical_name=item["canonical_name"], kind=item["kind"], value_type=item["value_type"],
            unit_policy=item["unit_policy"], repeat_policy=item["repeat_policy"],
            mutable_status=MutableStatus(item["mutable_status"]), scientific_scope=item["scientific_scope"],
            evidence_class=item["evidence_class"], manual_reference=item["manual_reference"], notes=item["notes"],
        ) for item in data)
        return cls(entries)

    def get(self, name: str) -> FDFRegistryEntry | None:
        return self._by_name.get(normalize_label(name))

    def require_mutable(self, name: str) -> FDFRegistryEntry:
        entry = self.get(name)
        if entry is None or entry.mutable_status is not MutableStatus.MUTABLE_TECHNICAL:
            raise PermissionError(f"FDF parameter is not technically mutable: {name}")
        return entry
