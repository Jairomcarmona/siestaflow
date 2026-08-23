"""Pure FDF rendering and validation for the M6 fixed-geometry SCF stage."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .fdf_parser import FDFParser
from .effective_fdf import resolve_effective_fdf
from .models import FDFBlock, FDFDocument, normalize_label


def _logical(value: str) -> bool:
    token = value.strip().casefold()
    if token in {"", "t", "true", ".true.", "yes"}:
        return True
    if token in {"f", "false", ".false.", "no"}:
        return False
    raise ValueError(f"invalid FDF logical value: {value}")


def _scalar(document: FDFDocument, name: str):
    return next((item for item in document.scalars() if normalize_label(item.label) == normalize_label(name)), None)


def _replace_scalar(text: str, name: str, rendered: str) -> str:
    document = FDFParser().parse(text)
    matches = document.scalars(name)
    if len(matches) > 1:
        raise ValueError(f"duplicate FDF scalar: {name}")
    if not matches:
        return text.rstrip("\r\n") + "\n" + rendered + "\n"
    target = matches[0]
    replacement = rendered + ("\n" if target.raw.endswith(("\n", "\r\n")) else "")
    return "".join(replacement if node is target else node.raw for node in document.nodes)


def _replace_block(text: str, name: str, rendered: str) -> str:
    document = FDFParser().parse(text)
    matches = document.blocks(name)
    if len(matches) > 1:
        raise ValueError(f"duplicate FDF block: {name}")
    if not matches:
        return text.rstrip("\r\n") + "\n" + rendered
    target = matches[0]
    return "".join(rendered if node is target else node.raw for node in document.nodes)


def _number(value: object) -> str:
    return format(float(value), ".16g")


def render_geometry(text: str, geometry: Mapping[str, Any]) -> str:
    """Embed verified cartesian-Ang geometry deterministically in an FDF."""

    cell = geometry.get("cell")
    atoms = geometry.get("atoms")
    if not isinstance(cell, list) or len(cell) != 3 or not isinstance(atoms, list) or not atoms:
        raise ValueError("invalid qraft.geometry payload")
    if any(not isinstance(row, list) or len(row) != 3 for row in cell):
        raise ValueError("invalid qraft.geometry cell")
    updates = geometry_updates(geometry)
    lattice = "%block LatticeVectors\n" + str(updates["blocks"]["LatticeVectors"]) + "\n%endblock LatticeVectors\n"
    coordinates_block = "%block AtomicCoordinatesAndAtomicSpecies\n" + str(updates["blocks"]["AtomicCoordinatesAndAtomicSpecies"]) + "\n%endblock AtomicCoordinatesAndAtomicSpecies\n"
    rendered = _replace_scalar(text, "LatticeConstant", "LatticeConstant 1 Ang")
    rendered = _replace_block(rendered, "LatticeVectors", lattice)
    rendered = _replace_scalar(rendered, "AtomicCoordinatesFormat", "AtomicCoordinatesFormat Ang")
    rendered = _replace_block(rendered, "AtomicCoordinatesAndAtomicSpecies", coordinates_block)
    rendered = _replace_scalar(rendered, "NumberOfAtoms", f"NumberOfAtoms {len(atoms)}")
    return rendered.rstrip("\r\n") + "\n"


def geometry_updates(geometry: Mapping[str, Any]) -> dict[str, Mapping[str, object]]:
    """Canonical FDF values for a verified cartesian-Ang geometry."""

    cell = geometry.get("cell")
    atoms = geometry.get("atoms")
    if not isinstance(cell, list) or len(cell) != 3 or not isinstance(atoms, list) or not atoms:
        raise ValueError("invalid qraft.geometry payload")
    if any(not isinstance(row, list) or len(row) != 3 for row in cell):
        raise ValueError("invalid qraft.geometry cell")
    lattice = "".join(" ".join(_number(item) for item in row) + "\n" for row in cell).rstrip("\n")
    rows = []
    for atom in atoms:
        coordinates = atom.get("coordinates") if isinstance(atom, Mapping) else None
        if not isinstance(coordinates, list) or len(coordinates) != 3:
            raise ValueError("invalid qraft.geometry atom coordinates")
        rows.append(" ".join(_number(item) for item in coordinates) + f" {int(atom['species_index'])}")
    return {
        "scalars": {
            "LatticeConstant": (1, "Ang"), "AtomicCoordinatesFormat": ("Ang", None), "NumberOfAtoms": (len(atoms), None),
        },
        "blocks": {"LatticeVectors": lattice, "AtomicCoordinatesAndAtomicSpecies": "\n".join(rows)},
    }


def validate_final_scf(path: Path) -> None:
    effective = resolve_effective_fdf(path)
    steps = effective.scalar("MD.Steps")
    if steps is not None:
        try:
            if int(steps.value) != 0:
                raise ValueError("M6 final SCF requires MD.Steps absent or 0")
        except ValueError as exc:
            if "M6 final" in str(exc):
                raise
            raise ValueError("invalid MD.Steps") from exc
    for name in ("MD.VariableCell", "Harris.Functional", "UseStructFile"):
        scalar = effective.scalar(name)
        if scalar is not None and _logical(scalar.value):
            raise ValueError(f"M6 final SCF rejects {name}=true")


def system_label(path: Path) -> str:
    scalar = resolve_effective_fdf(path).scalar("SystemLabel")
    return scalar.value.strip() if scalar is not None and scalar.value.strip() else "siesta"
