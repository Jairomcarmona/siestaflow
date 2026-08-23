"""SIESTA-specific binding of generic campaign parameters to FDF text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ...campaign_spec import EngineOption, ScientificValue
from .fdf_parser import FDFParser
from .fdf_registry import FDFRegistry
from .models import normalize_label


@dataclass(frozen=True)
class MaterializedFDF:
    parameter: str
    value: ScientificValue
    text: str
    sha256: str
    filename: str


class SiestaCampaignAdapter:
    """The only campaign layer that knows concrete SIESTA keywords."""

    _SCALARS = {
        "mesh_cutoff": ("Mesh.Cutoff", {"ry"}),
        "basis_size": ("PAO.BasisSize", {None}),
        "basis_energy_shift": ("PAO.EnergyShift", {"mev", "ev", "ry"}),
    }

    def __init__(self, registry: FDFRegistry | None = None) -> None:
        self.registry = registry or FDFRegistry.load_default()

    def validate_parameter(self, name: str, unit: str | None) -> None:
        if name == "kpoints":
            if unit is not None:
                raise ValueError("kpoints does not accept a unit")
            return
        if name not in self._SCALARS:
            raise ValueError(f"convergence parameter is not supported by SIESTA v1: {name}")
        allowed = self._SCALARS[name][1]
        normalized = unit.casefold() if unit else None
        if normalized not in allowed:
            rendered = ", ".join(sorted(value or "none" for value in allowed))
            raise ValueError(f"{name} unit must be one of: {rendered}")

    def materialize(
        self,
        base: Path,
        *,
        scanned_name: str,
        scanned_value: ScientificValue,
        resolved: Mapping[str, tuple[ScientificValue, str | None]],
        engine_options: tuple[EngineOption, ...] = (),
    ) -> MaterializedFDF:
        text = self.render_resolved(base, resolved=resolved, engine_options=engine_options)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return MaterializedFDF(
            scanned_name,
            scanned_value,
            text,
            digest,
            f"point-{self._slug(scanned_value)}.fdf",
        )

    def render_resolved(
        self,
        base: Path,
        *,
        resolved: Mapping[str, tuple[ScientificValue, str | None]],
        engine_options: tuple[EngineOption, ...] = (),
    ) -> str:
        """Purely apply already-selected campaign values to an FDF template."""

        text = base.read_text(encoding="utf-8")
        for name, (value, unit) in sorted(resolved.items()):
            self.validate_parameter(name, unit)
            text = self._apply(text, name, value, unit)
        for option in engine_options:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", option.name):
                raise ValueError(f"invalid SIESTA engine option: {option.name}")
            reserved = {normalize_label(item[0]) for item in self._SCALARS.values()}
            reserved.add(normalize_label("kgrid.MonkhorstPack"))
            if normalize_label(option.name) in reserved:
                raise ValueError(f"engine option conflicts with governed campaign parameter: {option.name}")
            entry = self.registry.get(option.name)
            if entry is None or entry.kind != "scalar":
                raise ValueError(f"SIESTA engine option is not a registered scalar: {option.name}")
            if entry.value_type == "real" and (
                not isinstance(option.value, (int, float)) or isinstance(option.value, bool)
            ):
                raise ValueError(f"SIESTA engine option requires a real value: {option.name}")
            if entry.value_type == "integer" and (
                not isinstance(option.value, int) or isinstance(option.value, bool)
            ):
                raise ValueError(f"SIESTA engine option requires an integer value: {option.name}")
            if entry.unit_policy == "dimensionless" and option.unit is not None:
                raise ValueError(f"SIESTA engine option is dimensionless: {option.name}")
            text = self._replace_scalar(text, option.name, option.value, option.unit)
        text = text.rstrip("\r\n") + "\n"
        return text

    def _apply(
        self, text: str, name: str, value: ScientificValue, unit: str | None
    ) -> str:
        if name == "kpoints":
            if not (
                isinstance(value, tuple) and len(value) == 3
                and all(isinstance(item, int) and item > 0 for item in value)
            ):
                raise ValueError("kpoints values must be positive [kx, ky, kz] grids")
            return self._replace_kgrid(text, value)
        if name in {"mesh_cutoff", "basis_energy_shift"} and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
        ):
            raise ValueError(f"{name} must be a positive number")
        keyword = self._SCALARS[name][0]
        return self._replace_scalar(text, keyword, value, unit)

    @staticmethod
    def _replace_scalar(
        text: str, keyword: str, value: ScientificValue, unit: str | None
    ) -> str:
        rendered = f"{keyword} {value}{f' {unit}' if unit else ''}"
        document = FDFParser().parse(text)
        matches = document.scalars(keyword)
        if len(matches) > 1:
            raise ValueError(f"duplicate FDF scalar cannot be materialized: {keyword}")
        if matches:
            target = matches[0]
            replacement = rendered + ("\n" if target.raw.endswith(("\n", "\r\n")) else "")
            return "".join(replacement if node is target else node.raw for node in document.nodes)
        return text.rstrip("\r\n") + "\n" + rendered + "\n"

    @staticmethod
    def _replace_kgrid(text: str, grid: tuple[int, ...]) -> str:
        replacement = (
            "%block kgrid.MonkhorstPack\n"
            f"  {grid[0]} 0 0 0.0\n"
            f"  0 {grid[1]} 0 0.0\n"
            f"  0 0 {grid[2]} 0.0\n"
            "%endblock kgrid.MonkhorstPack\n"
        )
        document = FDFParser().parse(text)
        matches = document.blocks("kgrid.MonkhorstPack")
        if len(matches) > 1:
            raise ValueError("duplicate kgrid.MonkhorstPack block")
        if matches:
            target = matches[0]
            return "".join(replacement if node is target else node.raw for node in document.nodes)
        return text.rstrip("\r\n") + "\n" + replacement

    @staticmethod
    def _slug(value: ScientificValue) -> str:
        raw = "x".join(map(str, value)) if isinstance(value, tuple) else str(value)
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-")
