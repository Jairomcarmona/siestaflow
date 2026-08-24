"""SIESTA-only geometry and BandPathSpec adapters for M7.1."""

from __future__ import annotations

from pathlib import Path

from ...band_paths import (
    BandPathProposal,
    CrystalStructure,
)
from .electronic_properties import BandPathSpec, BandPathVertex
from .effective_fdf import resolve_effective_fdf
from .relaxation import geometry_from_fdf


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _cross(left: tuple[float, float, float], right: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _fractional(cell: tuple[tuple[float, float, float], ...], cartesian: tuple[float, float, float]) -> tuple[float, float, float]:
    first, second, third = cell
    determinant = _dot(first, _cross(second, third))
    if abs(determinant) <= 1.0e-12:
        raise ValueError("M6 final geometry cell has zero volume")
    return (
        _dot(cartesian, _cross(second, third)) / determinant,
        _dot(first, _cross(cartesian, third)) / determinant,
        _dot(first, _cross(second, cartesian)) / determinant,
    )


def structure_from_final_fdf(final_fdf: Path) -> CrystalStructure:
    """Read the verified M6 final geometry without transforming its cell or atoms."""

    geometry = geometry_from_fdf(final_fdf)
    effective = resolve_effective_fdf(final_fdf)
    species = effective.block("ChemicalSpeciesLabel")
    if species is None or not species.closed:
        raise ValueError("M6 final geometry lacks ChemicalSpeciesLabel")
    atomic_numbers: dict[int, int] = {}
    for raw in species.body_lines:
        fields = raw.split()
        if not fields:
            continue
        if len(fields) < 3:
            raise ValueError("M6 ChemicalSpeciesLabel row is invalid")
        try:
            atomic_numbers[int(fields[0])] = int(fields[1])
        except ValueError as exc:
            raise ValueError("M6 ChemicalSpeciesLabel row has invalid indices") from exc
    cell = tuple(tuple(float(value) for value in row) for row in geometry["cell"])
    positions = []
    numbers = []
    for atom in geometry["atoms"]:
        species_index = int(atom["species_index"])
        if species_index not in atomic_numbers:
            raise ValueError("M6 geometry references an undeclared species")
        cartesian = tuple(float(value) for value in atom["coordinates"])
        positions.append(_fractional(cell, cartesian))
        numbers.append(atomic_numbers[species_index])
    return CrystalStructure(cell, tuple(positions), tuple(numbers))  # type: ignore[arg-type]


def time_reversal_evidence_from_final_fdf(final_fdf: Path) -> bool | None:
    """Return only explicit non-magnetic M6 evidence; never infer by absence."""

    spin = resolve_effective_fdf(final_fdf).scalar("Spin")
    if spin is None:
        return None
    normalized = "".join(character.casefold() for character in spin.value if character.isalnum())
    if normalized in {"none", "nonpolarized", "unpolarized"}:
        return True
    # Polarized/non-collinear/SOC values are not enough for M7.1 V1 to make a
    # magnetism decision.  M8 must supply an explicit policy later.
    return None


def compile_band_path_proposal(proposal: BandPathProposal, *, scale: str = "ReciprocalLatticeVectors") -> BandPathSpec:
    """Compile only approved continuous segments into the established renderer.

    Each disconnected group begins again with SIESTA's required count ``1``.
    Therefore adjacent proposal segments are joined only when their shared end
    point is explicit; unrelated U and K endpoints are never bridged.
    """

    if proposal.status.value != "READY":
        raise ValueError(f"cannot compile a {proposal.status.value} band-path proposal")
    groups: list[list[BandPathVertex]] = []
    for segment in proposal.segments:
        start = BandPathVertex(segment.start_coordinates, 1, segment.start_label)
        end = BandPathVertex(segment.end_coordinates, segment.points, segment.end_label)
        if groups and groups[-1][-1].coordinates == start.coordinates and groups[-1][-1].label == start.label:
            groups[-1].append(end)
        else:
            groups.append([start, end])
    return BandPathSpec(scale, segments=tuple(tuple(group) for group in groups))
