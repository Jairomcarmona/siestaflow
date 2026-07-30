#!/usr/bin/env python3
"""Validated transfer of accepted SIESTA geometries into adsorption FDF seeds.

Scientific contract
-------------------
* STRUCT_OUT is the primary geometry because it is the last structure for which
  forces and stresses were evaluated.
* XV is a mandatory independent consistency check and a restart artifact.
* siesta.out and FA are acceptance evidence, never the coordinate source.
* Source species indices are never copied into a target FDF.  They are mapped
  through (atomic number, chemical label) into the target ChemicalSpeciesLabel.
* Master FDF files are read-only.  Generated FDFs and JSON audit records live
  under generated/geometry_transfers/.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


BOHR_TO_ANG = 0.529177210903
STRUCT_XV_TOL_ANG = 1.0e-6
CELL_TOL_ANG = 1.0e-6
SEED_RIGID_FIT_TOL_ANG = 1.0e-5
RIGID_DISTANCE_TOL_ANG = 1.0e-8
CROSS_FRAGMENT_HARD_MIN_ANG = 1.30


ADSORPTION_DEPENDENCIES = {
    "ADSORB_Gr_Ca8w_OS_v01": ("SURF_Gr5x5_clean_v01", "ADS_Ca8w_v01", 50),
    "ADSORB_Gr_Mg6w_OS_v01": ("SURF_Gr5x5_clean_v01", "ADS_Mg6w_v01", 50),
    "ADSORB_COO2_Ca8w_OS_v01": ("SURF_Gr5x5_2COO_v01", "ADS_Ca8w_v01", 50),
    "ADSORB_COO2_Mg6w_OS_v01": ("SURF_Gr5x5_2COO_v01", "ADS_Mg6w_v01", 50),
    "ADSORB_M1_Ca8w_OS_v01": (
        "M1_delta_MnO2_neutral_surface_control_v01",
        "ADS_Ca8w_v01",
        54,
    ),
    "ADSORB_M1_Mg6w_OS_v01": (
        "M1_delta_MnO2_neutral_surface_control_v01",
        "ADS_Mg6w_v01",
        54,
    ),
}


class GeometryTransferError(RuntimeError):
    """Fail-closed geometry validation error."""


@dataclass(frozen=True)
class Species:
    index: int
    atomic_number: int
    label: str


@dataclass(frozen=True)
class Structure:
    cell: tuple[tuple[float, float, float], ...]
    species_indices: tuple[int, ...]
    positions_ang: tuple[tuple[float, float, float], ...]

    @property
    def natoms(self) -> int:
        return len(self.positions_ang)


@dataclass(frozen=True)
class FdfGeometry:
    path: Path
    text: str
    number_of_atoms: int
    species: dict[int, Species]
    structure: Structure
    max_force_tol_ev_ang: float

    @property
    def atom_species(self) -> tuple[Species, ...]:
        return tuple(self.species[index] for index in self.structure.species_indices)


@dataclass(frozen=True)
class AcceptedRun:
    system_id: str
    run_dir: Path
    fdf: FdfGeometry
    structure_out: Structure
    xv: Structure
    max_force_ev_ang: float
    struct_xv_max_delta_ang: float
    output_path: Path
    structure_out_path: Path
    xv_path: Path
    force_path: Path

    def summary(self) -> dict[str, object]:
        return {
            "system_id": self.system_id,
            "run_id": self.run_dir.name,
            "run_dir": str(self.run_dir),
            "normal_termination": True,
            "geometry_accepted": True,
            "max_force_ev_ang": self.max_force_ev_ang,
            "max_force_tolerance_ev_ang": self.fdf.max_force_tol_ev_ang,
            "struct_xv_max_delta_ang": self.struct_xv_max_delta_ang,
            "coordinate_authority": "STRUCT_OUT",
            "coordinate_crosscheck": "XV",
            "structure_out_sha256": sha256(self.structure_out_path),
            "xv_sha256": sha256(self.xv_path),
            "fa_sha256": sha256(self.force_path),
            "siesta_out_sha256": sha256(self.output_path),
            "run_fdf_sha256": sha256(self.fdf.path),
        }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _block(text: str, name: str) -> str:
    match = re.search(
        rf"%block\s+{re.escape(name)}\s*(.*?)%endblock\s+{re.escape(name)}",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise GeometryTransferError(f"missing FDF block: {name}")
    return match.group(1)


def _data_lines(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in block.splitlines():
        tokens = raw.split("#", 1)[0].split()
        if tokens:
            rows.append(tokens)
    return rows


def parse_fdf(path: str | Path) -> FdfGeometry:
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    atom_match = re.search(r"^\s*NumberOfAtoms\s+(\d+)", text, re.IGNORECASE | re.MULTILINE)
    if not atom_match:
        raise GeometryTransferError(f"{path}: missing NumberOfAtoms")
    number_of_atoms = int(atom_match.group(1))

    format_match = re.search(
        r"^\s*AtomicCoordinatesFormat\s+(\S+)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not format_match or format_match.group(1).lower() not in {"ang", "angstrom"}:
        raise GeometryTransferError(f"{path}: only Cartesian Ang coordinates are accepted")

    lattice_match = re.search(
        r"^\s*LatticeConstant\s+([0-9.eEdD+-]+)\s+(\S+)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not lattice_match:
        raise GeometryTransferError(f"{path}: missing LatticeConstant")
    lattice_value = float(lattice_match.group(1).replace("D", "E").replace("d", "e"))
    lattice_unit = lattice_match.group(2).lower()
    if lattice_unit not in {"ang", "angstrom"} or abs(lattice_value - 1.0) > 1.0e-12:
        raise GeometryTransferError(f"{path}: expected LatticeConstant 1.0 Ang")

    lattice_rows = _data_lines(_block(text, "LatticeVectors"))
    if len(lattice_rows) != 3 or any(len(row) < 3 for row in lattice_rows):
        raise GeometryTransferError(f"{path}: LatticeVectors must contain exactly 3 vectors")
    cell = tuple(tuple(float(value) for value in row[:3]) for row in lattice_rows)

    species: dict[int, Species] = {}
    for row in _data_lines(_block(text, "ChemicalSpeciesLabel")):
        if len(row) < 3:
            raise GeometryTransferError(f"{path}: malformed ChemicalSpeciesLabel row {row!r}")
        item = Species(int(row[0]), int(row[1]), row[2])
        if item.index in species:
            raise GeometryTransferError(f"{path}: duplicate species index {item.index}")
        species[item.index] = item

    coord_rows = _data_lines(_block(text, "AtomicCoordinatesAndAtomicSpecies"))
    if len(coord_rows) != number_of_atoms:
        raise GeometryTransferError(
            f"{path}: NumberOfAtoms={number_of_atoms}, coordinate rows={len(coord_rows)}"
        )
    positions: list[tuple[float, float, float]] = []
    species_indices: list[int] = []
    for atom_index, row in enumerate(coord_rows, 1):
        if len(row) < 4:
            raise GeometryTransferError(f"{path}: malformed coordinate row {atom_index}")
        position = tuple(float(value) for value in row[:3])
        species_index = int(row[3])
        if species_index not in species:
            raise GeometryTransferError(
                f"{path}: atom {atom_index} uses undefined species {species_index}"
            )
        if not all(math.isfinite(value) for value in position):
            raise GeometryTransferError(f"{path}: non-finite coordinate at atom {atom_index}")
        positions.append(position)
        species_indices.append(species_index)

    force_match = re.search(
        r"^\s*MD\.MaxForceTol\s+([0-9.eEdD+-]+)\s+eV/Ang",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not force_match:
        raise GeometryTransferError(f"{path}: missing MD.MaxForceTol in eV/Ang")
    force_tolerance = float(force_match.group(1).replace("D", "E").replace("d", "e"))

    return FdfGeometry(
        path=path,
        text=text,
        number_of_atoms=number_of_atoms,
        species=species,
        structure=Structure(cell, tuple(species_indices), tuple(positions)),
        max_force_tol_ev_ang=force_tolerance,
    )


def parse_struct_out(path: str | Path) -> Structure:
    path = Path(path)
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 4:
        raise GeometryTransferError(f"{path}: truncated STRUCT_OUT")
    if any(len(lines[index]) < 3 for index in range(3)):
        raise GeometryTransferError(f"{path}: malformed STRUCT_OUT cell")
    cell = tuple(tuple(float(value) for value in lines[index][:3]) for index in range(3))
    natoms = int(lines[3][0])
    if len(lines) != 4 + natoms:
        raise GeometryTransferError(
            f"{path}: STRUCT_OUT declares {natoms} atoms but has {len(lines) - 4} rows"
        )

    species_indices: list[int] = []
    positions: list[tuple[float, float, float]] = []
    for atom_index, row in enumerate(lines[4:], 1):
        if len(row) < 5:
            raise GeometryTransferError(f"{path}: malformed atom row {atom_index}")
        species_indices.append(int(row[0]))
        fractional = tuple(float(value) for value in row[2:5])
        positions.append(frac_to_cart(fractional, cell))
    return Structure(cell, tuple(species_indices), tuple(positions))


def parse_xv(path: str | Path, source_species: dict[int, Species]) -> Structure:
    path = Path(path)
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 4:
        raise GeometryTransferError(f"{path}: truncated XV")
    if any(len(lines[index]) < 3 for index in range(3)):
        raise GeometryTransferError(f"{path}: malformed XV cell")
    cell = tuple(
        tuple(float(value) * BOHR_TO_ANG for value in lines[index][:3])
        for index in range(3)
    )
    natoms = int(lines[3][0])
    if len(lines) != 4 + natoms:
        raise GeometryTransferError(f"{path}: XV declares {natoms} atoms but has {len(lines) - 4}")

    species_indices: list[int] = []
    positions: list[tuple[float, float, float]] = []
    for atom_index, row in enumerate(lines[4:], 1):
        if len(row) < 8:
            raise GeometryTransferError(f"{path}: malformed XV atom row {atom_index}")
        species_index = int(row[0])
        atomic_number = int(row[1])
        if species_index not in source_species:
            raise GeometryTransferError(
                f"{path}: atom {atom_index} uses undefined source species {species_index}"
            )
        expected_z = source_species[species_index].atomic_number
        if atomic_number != expected_z:
            raise GeometryTransferError(
                f"{path}: atom {atom_index} XV Z={atomic_number}, FDF Z={expected_z}"
            )
        position = tuple(float(value) * BOHR_TO_ANG for value in row[2:5])
        species_indices.append(species_index)
        positions.append(position)
    return Structure(cell, tuple(species_indices), tuple(positions))


def parse_fa_max_component(path: str | Path, expected_atoms: int) -> float:
    path = Path(path)
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise GeometryTransferError(f"{path}: empty FA")
    natoms = int(lines[0][0])
    if natoms != expected_atoms or len(lines) != natoms + 1:
        raise GeometryTransferError(
            f"{path}: FA atom count mismatch ({natoms}, rows={len(lines) - 1}, expected={expected_atoms})"
        )
    maximum = 0.0
    for expected_index, row in enumerate(lines[1:], 1):
        if len(row) < 4 or int(row[0]) != expected_index:
            raise GeometryTransferError(f"{path}: malformed or reordered FA atom {expected_index}")
        maximum = max(maximum, *(abs(float(value)) for value in row[1:4]))
    return maximum


def frac_to_cart(
    fractional: Sequence[float],
    cell: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    return tuple(sum(fractional[k] * cell[k][j] for k in range(3)) for j in range(3))


def cart_to_frac(
    cartesian: Sequence[float],
    cell: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    inverse = inverse3(cell)
    return tuple(sum(cartesian[k] * inverse[k][j] for k in range(3)) for j in range(3))


def inverse3(matrix: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], ...]:
    a, b, c = matrix
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant) < 1.0e-14:
        raise GeometryTransferError("singular cell matrix")
    return (
        (
            (b[1] * c[2] - b[2] * c[1]) / determinant,
            (a[2] * c[1] - a[1] * c[2]) / determinant,
            (a[1] * b[2] - a[2] * b[1]) / determinant,
        ),
        (
            (b[2] * c[0] - b[0] * c[2]) / determinant,
            (a[0] * c[2] - a[2] * c[0]) / determinant,
            (a[2] * b[0] - a[0] * b[2]) / determinant,
        ),
        (
            (b[0] * c[1] - b[1] * c[0]) / determinant,
            (a[1] * c[0] - a[0] * c[1]) / determinant,
            (a[0] * b[1] - a[1] * b[0]) / determinant,
        ),
    )


def subtract(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def minimum_image_vector(
    delta_cart: Sequence[float],
    cell: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    fractional = cart_to_frac(delta_cart, cell)
    wrapped = tuple(value - round(value) for value in fractional)
    return frac_to_cart(wrapped, cell)


def nearest_image_to_reference(
    position: Sequence[float],
    reference: Sequence[float],
    cell: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    return add(reference, minimum_image_vector(subtract(position, reference), cell))


def max_periodic_delta(
    first: Structure,
    second: Structure,
) -> float:
    if first.natoms != second.natoms:
        raise GeometryTransferError("cannot compare structures with different atom counts")
    assert_cells_close(first.cell, second.cell)
    return max(
        norm(minimum_image_vector(subtract(a, b), first.cell))
        for a, b in zip(first.positions_ang, second.positions_ang)
    )


def assert_cells_close(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
    tolerance: float = CELL_TOL_ANG,
) -> None:
    maximum = max(abs(first[i][j] - second[i][j]) for i in range(3) for j in range(3))
    if maximum > tolerance:
        raise GeometryTransferError(f"cell mismatch: max delta {maximum:.6e} Ang")


def validate_run_directory(system_id: str, run_dir: str | Path) -> AcceptedRun:
    run_dir = Path(run_dir)
    work = run_dir / "work"
    results = run_dir / "results"
    fdf = parse_fdf(work / "run.fdf")

    output_path = results / "siesta.out"
    output_text = output_path.read_text(encoding="utf-8", errors="replace")
    if "Job completed" not in output_text or ">> End of run:" not in output_text:
        raise GeometryTransferError(f"{run_dir}: no normal SIESTA termination")

    structure_files = list(work.glob("*.STRUCT_OUT"))
    xv_files = list(work.glob("*.XV"))
    force_files = list(work.glob("*.FA"))
    if len(structure_files) != 1 or len(xv_files) != 1 or len(force_files) != 1:
        raise GeometryTransferError(
            f"{run_dir}: expected one STRUCT_OUT, XV and FA; got "
            f"{len(structure_files)}, {len(xv_files)}, {len(force_files)}"
        )

    structure_out = parse_struct_out(structure_files[0])
    xv = parse_xv(xv_files[0], fdf.species)
    for name, structure in (("STRUCT_OUT", structure_out), ("XV", xv)):
        if structure.natoms != fdf.number_of_atoms:
            raise GeometryTransferError(f"{run_dir}: {name} atom count mismatch")
        if structure.species_indices != fdf.structure.species_indices:
            raise GeometryTransferError(f"{run_dir}: {name} species/order mismatch against run.fdf")

    assert_cells_close(structure_out.cell, fdf.structure.cell)
    assert_cells_close(xv.cell, fdf.structure.cell)
    struct_xv_delta = max_periodic_delta(structure_out, xv)
    if struct_xv_delta > STRUCT_XV_TOL_ANG:
        raise GeometryTransferError(
            f"{run_dir}: STRUCT_OUT/XV max delta {struct_xv_delta:.6e} Ang "
            f"exceeds {STRUCT_XV_TOL_ANG:.1e}"
        )

    maximum_force = parse_fa_max_component(force_files[0], fdf.number_of_atoms)
    if maximum_force > fdf.max_force_tol_ev_ang + 1.0e-10:
        raise GeometryTransferError(
            f"{run_dir}: max force {maximum_force:.8f} exceeds "
            f"{fdf.max_force_tol_ev_ang:.8f} eV/Ang"
        )

    return AcceptedRun(
        system_id=system_id,
        run_dir=run_dir,
        fdf=fdf,
        structure_out=structure_out,
        xv=xv,
        max_force_ev_ang=maximum_force,
        struct_xv_max_delta_ang=struct_xv_delta,
        output_path=output_path,
        structure_out_path=structure_files[0],
        xv_path=xv_files[0],
        force_path=force_files[0],
    )


def find_latest_accepted_run(root: str | Path, system_id: str) -> AcceptedRun | None:
    runs_root = Path(root) / "systems" / system_id / "runs"
    if not runs_root.exists():
        return None
    candidates = sorted(
        (path for path in runs_root.iterdir() if path.is_dir()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for run_dir in candidates:
        try:
            return validate_run_directory(system_id, run_dir)
        except (GeometryTransferError, OSError, ValueError):
            continue
    return None


def validate_restart_xv(
    xv_path: str | Path,
    fdf_path: str | Path,
) -> Structure:
    """Validate a same-system restart checkpoint without treating it as accepted."""
    xv_path = Path(xv_path)
    fdf = parse_fdf(fdf_path)
    label_match = re.search(
        r"^\s*SystemLabel\s+(\S+)",
        fdf.text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not label_match:
        raise GeometryTransferError(f"{fdf.path}: missing SystemLabel")
    expected_name = f"{label_match.group(1)}.XV"
    if xv_path.name != expected_name:
        raise GeometryTransferError(
            f"{xv_path}: checkpoint filename {xv_path.name!r} != {expected_name!r}"
        )
    xv = parse_xv(xv_path, fdf.species)
    if xv.natoms != fdf.number_of_atoms:
        raise GeometryTransferError(f"{xv_path}: restart atom count mismatch")
    if xv.species_indices != fdf.structure.species_indices:
        raise GeometryTransferError(f"{xv_path}: restart species/order mismatch")
    assert_cells_close(xv.cell, fdf.structure.cell)
    return xv


def centroid(points: Iterable[Sequence[float]]) -> tuple[float, float, float]:
    rows = list(points)
    if not rows:
        raise GeometryTransferError("cannot calculate centroid of empty point set")
    return tuple(sum(row[j] for row in rows) / len(rows) for j in range(3))


def matrix_vector(
    matrix: Sequence[Sequence[float]],
    vector: Sequence[float],
) -> tuple[float, float, float]:
    return tuple(sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3))


def determinant3(matrix: Sequence[Sequence[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _jacobi_largest_eigenvector(matrix: Sequence[Sequence[float]]) -> tuple[float, ...]:
    size = len(matrix)
    values = [list(row) for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for _ in range(100):
        p, q = max(
            ((i, j) for i in range(size) for j in range(i + 1, size)),
            key=lambda pair: abs(values[pair[0]][pair[1]]),
        )
        if abs(values[p][q]) < 1.0e-15:
            break
        angle = 0.5 * math.atan2(2.0 * values[p][q], values[q][q] - values[p][p])
        cosine = math.cos(angle)
        sine = math.sin(angle)

        app = values[p][p]
        aqq = values[q][q]
        apq = values[p][q]
        values[p][p] = cosine * cosine * app - 2.0 * sine * cosine * apq + sine * sine * aqq
        values[q][q] = sine * sine * app + 2.0 * sine * cosine * apq + cosine * cosine * aqq
        values[p][q] = values[q][p] = 0.0
        for k in range(size):
            if k in (p, q):
                continue
            akp = values[k][p]
            akq = values[k][q]
            values[k][p] = values[p][k] = cosine * akp - sine * akq
            values[k][q] = values[q][k] = sine * akp + cosine * akq
        for k in range(size):
            vkp = vectors[k][p]
            vkq = vectors[k][q]
            vectors[k][p] = cosine * vkp - sine * vkq
            vectors[k][q] = sine * vkp + cosine * vkq

    index = max(range(size), key=lambda item: values[item][item])
    vector = tuple(vectors[row][index] for row in range(size))
    magnitude = math.sqrt(sum(value * value for value in vector))
    return tuple(value / magnitude for value in vector)


def optimal_rotation(
    source_vectors: Sequence[Sequence[float]],
    target_vectors: Sequence[Sequence[float]],
) -> tuple[tuple[float, float, float], ...]:
    if len(source_vectors) != len(target_vectors) or len(source_vectors) < 2:
        raise GeometryTransferError("rotation fit needs at least two paired vectors")
    covariance = [[0.0] * 3 for _ in range(3)]
    for source, target in zip(source_vectors, target_vectors):
        for i in range(3):
            for j in range(3):
                covariance[i][j] += source[i] * target[j]
    s = covariance
    quaternion_matrix = (
        (s[0][0] + s[1][1] + s[2][2], s[1][2] - s[2][1], s[2][0] - s[0][2], s[0][1] - s[1][0]),
        (s[1][2] - s[2][1], s[0][0] - s[1][1] - s[2][2], s[0][1] + s[1][0], s[0][2] + s[2][0]),
        (s[2][0] - s[0][2], s[0][1] + s[1][0], -s[0][0] + s[1][1] - s[2][2], s[1][2] + s[2][1]),
        (s[0][1] - s[1][0], s[0][2] + s[2][0], s[1][2] + s[2][1], -s[0][0] - s[1][1] + s[2][2]),
    )
    w, x, y, z = _jacobi_largest_eigenvector(quaternion_matrix)
    rotation = (
        (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)),
        (2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)),
        (2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)),
    )
    if abs(determinant3(rotation) - 1.0) > 1.0e-10:
        raise GeometryTransferError("rotation fit produced a reflection or non-rigid matrix")
    return rotation


def fit_rmsd(
    rotation: Sequence[Sequence[float]],
    source_vectors: Sequence[Sequence[float]],
    target_vectors: Sequence[Sequence[float]],
) -> tuple[float, float]:
    deltas = [
        norm(subtract(matrix_vector(rotation, source), target))
        for source, target in zip(source_vectors, target_vectors)
    ]
    return math.sqrt(sum(value * value for value in deltas) / len(deltas)), max(deltas)


def unwrap_around_anchor(
    positions: Sequence[Sequence[float]],
    anchor_index: int,
    cell: Sequence[Sequence[float]],
) -> tuple[tuple[float, float, float], ...]:
    anchor = positions[anchor_index]
    return tuple(nearest_image_to_reference(position, anchor, cell) for position in positions)


def periodic_pair_distance(
    first: Sequence[float],
    second: Sequence[float],
    cell: Sequence[Sequence[float]],
) -> float:
    return norm(minimum_image_vector(subtract(first, second), cell))


def max_pair_distance_change(
    before: Sequence[Sequence[float]],
    after: Sequence[Sequence[float]],
) -> float:
    if len(before) != len(after):
        raise GeometryTransferError("pair-distance comparison size mismatch")
    maximum = 0.0
    for i in range(len(before)):
        for j in range(i + 1, len(before)):
            maximum = max(
                maximum,
                abs(norm(subtract(before[i], before[j])) - norm(subtract(after[i], after[j]))),
            )
    return maximum


def _target_species_map(fdf: FdfGeometry) -> dict[tuple[int, str], int]:
    result: dict[tuple[int, str], int] = {}
    for item in fdf.species.values():
        key = (item.atomic_number, item.label)
        if key in result:
            raise GeometryTransferError(f"{fdf.path}: duplicate target species identity {key}")
        result[key] = item.index
    return result


def _mapped_target_species(
    source_fdf: FdfGeometry,
    target_fdf: FdfGeometry,
) -> tuple[int, ...]:
    target = _target_species_map(target_fdf)
    mapped: list[int] = []
    for atom_index, source_item in enumerate(source_fdf.atom_species, 1):
        key = (source_item.atomic_number, source_item.label)
        if key not in target:
            raise GeometryTransferError(
                f"{target_fdf.path}: no target species for source atom {atom_index} {key}"
            )
        mapped.append(target[key])
    return tuple(mapped)


def _surface_in_seed_frame(
    relaxed: Structure,
    target_positions: Sequence[Sequence[float]],
    target_cell: Sequence[Sequence[float]],
    anchor_count: int,
) -> tuple[tuple[tuple[float, float, float], ...], tuple[float, float, float]]:
    assert_cells_close(relaxed.cell, target_cell)
    if relaxed.natoms != len(target_positions):
        raise GeometryTransferError("surface atom count does not match target seed fragment")
    image_matched = tuple(
        nearest_image_to_reference(position, target, target_cell)
        for position, target in zip(relaxed.positions_ang, target_positions)
    )
    source_center = centroid(image_matched[:anchor_count])
    target_center = centroid(target_positions[:anchor_count])
    translation = subtract(target_center, source_center)
    shifted = tuple(add(position, translation) for position in image_matched)
    return shifted, translation


def _adsorbate_in_seed_frame(
    relaxed: Structure,
    parent_seed: Structure,
    target_positions: Sequence[Sequence[float]],
    target_cell: Sequence[Sequence[float]],
    labels: Sequence[str],
) -> tuple[
    tuple[tuple[float, float, float], ...],
    dict[str, object],
]:
    if relaxed.natoms != len(parent_seed.positions_ang) or relaxed.natoms != len(target_positions):
        raise GeometryTransferError("adsorbate atom count mismatch")
    metal_indices = [index for index, label in enumerate(labels) if label in {"Ca", "Mg"}]
    oxygen_indices = [index for index, label in enumerate(labels) if label == "O"]
    if len(metal_indices) != 1 or len(oxygen_indices) not in {6, 8}:
        raise GeometryTransferError(
            f"expected one Ca/Mg and 6 or 8 oxygen anchors; got {metal_indices}, {oxygen_indices}"
        )
    metal = metal_indices[0]
    relaxed_unwrapped = unwrap_around_anchor(relaxed.positions_ang, metal, relaxed.cell)
    parent_unwrapped = unwrap_around_anchor(parent_seed.positions_ang, metal, parent_seed.cell)
    target_unwrapped = unwrap_around_anchor(target_positions, metal, target_cell)

    relaxed_vectors = [
        subtract(relaxed_unwrapped[index], relaxed_unwrapped[metal]) for index in oxygen_indices
    ]
    parent_vectors = [
        subtract(parent_unwrapped[index], parent_unwrapped[metal]) for index in oxygen_indices
    ]
    target_vectors = [
        subtract(target_unwrapped[index], target_unwrapped[metal]) for index in oxygen_indices
    ]

    normalize_rotation = optimal_rotation(relaxed_vectors, parent_vectors)
    normalized = tuple(
        add(
            matrix_vector(
                normalize_rotation,
                subtract(position, relaxed_unwrapped[metal]),
            ),
            parent_unwrapped[metal],
        )
        for position in relaxed_unwrapped
    )

    seed_rotation = optimal_rotation(parent_vectors, target_vectors)
    seed_rmsd, seed_max = fit_rmsd(seed_rotation, parent_vectors, target_vectors)
    seed_all = tuple(
        add(
            matrix_vector(seed_rotation, subtract(position, parent_unwrapped[metal])),
            target_unwrapped[metal],
        )
        for position in parent_unwrapped
    )
    seed_all_rmsd = math.sqrt(
        sum(norm(subtract(a, b)) ** 2 for a, b in zip(seed_all, target_unwrapped))
        / len(seed_all)
    )
    seed_all_max = max(norm(subtract(a, b)) for a, b in zip(seed_all, target_unwrapped))
    if seed_all_max > SEED_RIGID_FIT_TOL_ANG:
        raise GeometryTransferError(
            f"adsorbate seed is not a rigid embedding of its parent: max={seed_all_max:.6e} Ang"
        )

    injected = tuple(
        add(
            matrix_vector(seed_rotation, subtract(position, parent_unwrapped[metal])),
            target_unwrapped[metal],
        )
        for position in normalized
    )
    pair_delta = max_pair_distance_change(relaxed_unwrapped, injected)
    if pair_delta > RIGID_DISTANCE_TOL_ANG:
        raise GeometryTransferError(
            f"adsorbate rigid transfer changed an internal distance by {pair_delta:.6e} Ang"
        )

    normalize_rmsd, normalize_max = fit_rmsd(
        normalize_rotation,
        relaxed_vectors,
        parent_vectors,
    )
    return injected, {
        "metal_anchor_index_1based": metal + 1,
        "oxygen_anchor_indices_1based": [index + 1 for index in oxygen_indices],
        "relaxed_to_parent_oxygen_rmsd_ang": normalize_rmsd,
        "relaxed_to_parent_oxygen_max_ang": normalize_max,
        "parent_to_target_oxygen_rmsd_ang": seed_rmsd,
        "parent_to_target_oxygen_max_ang": seed_max,
        "parent_to_target_all_atom_rmsd_ang": seed_all_rmsd,
        "parent_to_target_all_atom_max_ang": seed_all_max,
        "max_internal_distance_change_ang": pair_delta,
        "normalize_rotation": [list(row) for row in normalize_rotation],
        "seed_rotation": [list(row) for row in seed_rotation],
    }


def _cross_fragment_minimum(
    surface: Sequence[Sequence[float]],
    adsorbate: Sequence[Sequence[float]],
    cell: Sequence[Sequence[float]],
) -> tuple[float, tuple[int, int]]:
    minimum = math.inf
    pair = (-1, -1)
    for surface_index, first in enumerate(surface, 1):
        for adsorbate_index, second in enumerate(adsorbate, 1):
            distance = periodic_pair_distance(first, second, cell)
            if distance < minimum:
                minimum = distance
                pair = (surface_index, adsorbate_index)
    return minimum, pair


def _replace_coordinate_block(
    target: FdfGeometry,
    positions: Sequence[Sequence[float]],
    target_species_indices: Sequence[int],
    provenance: Sequence[str],
) -> str:
    if len(positions) != target.number_of_atoms:
        raise GeometryTransferError("generated coordinate count does not match NumberOfAtoms")
    if len(target_species_indices) != len(positions) or len(provenance) != len(positions):
        raise GeometryTransferError("generated coordinate metadata size mismatch")
    rows = ["%block AtomicCoordinatesAndAtomicSpecies"]
    for position, species_index, source_id in zip(positions, target_species_indices, provenance):
        item = target.species[species_index]
        rows.append(
            f"  {position[0]:16.10f}  {position[1]:16.10f}  "
            f"{position[2]:16.10f}  {species_index:2d} "
            f"# {item.label} source={source_id}"
        )
    rows.append("%endblock AtomicCoordinatesAndAtomicSpecies")
    replacement = "\n".join(rows)
    pattern = re.compile(
        r"%block\s+AtomicCoordinatesAndAtomicSpecies.*?"
        r"%endblock\s+AtomicCoordinatesAndAtomicSpecies",
        flags=re.IGNORECASE | re.DOTALL,
    )
    updated, count = pattern.subn(replacement, target.text, count=1)
    if count != 1:
        raise GeometryTransferError("failed to replace exactly one target coordinate block")
    return updated


def build_adsorption_fdf(
    root: str | Path,
    system_id: str,
    target_fdf_path: str | Path,
) -> tuple[Path, Path, dict[str, object]]:
    root = Path(root)
    if system_id not in ADSORPTION_DEPENDENCIES:
        raise GeometryTransferError(f"{system_id}: no adsorption dependency contract")
    surface_id, adsorbate_id, surface_anchor_count = ADSORPTION_DEPENDENCIES[system_id]

    surface_run = find_latest_accepted_run(root, surface_id)
    adsorbate_run = find_latest_accepted_run(root, adsorbate_id)
    if surface_run is None or adsorbate_run is None:
        missing = [
            name
            for name, run in ((surface_id, surface_run), (adsorbate_id, adsorbate_run))
            if run is None
        ]
        raise GeometryTransferError(
            f"{system_id}: missing accepted parent relaxation(s): {', '.join(missing)}"
        )

    target = parse_fdf(target_fdf_path)
    surface_count = surface_run.structure_out.natoms
    adsorbate_count = adsorbate_run.structure_out.natoms
    if target.number_of_atoms != surface_count + adsorbate_count:
        raise GeometryTransferError(
            f"{system_id}: target atoms {target.number_of_atoms} != "
            f"{surface_count}+{adsorbate_count}"
        )

    mapped_surface_species = _mapped_target_species(surface_run.fdf, target)
    mapped_adsorbate_species = _mapped_target_species(adsorbate_run.fdf, target)
    mapped_species = mapped_surface_species + mapped_adsorbate_species
    if mapped_species != target.structure.species_indices:
        mismatches = [
            index + 1
            for index, (expected, actual) in enumerate(
                zip(mapped_species, target.structure.species_indices)
            )
            if expected != actual
        ]
        raise GeometryTransferError(
            f"{system_id}: target seed parent lineage/species mismatch at atoms {mismatches[:10]}"
        )

    target_surface = target.structure.positions_ang[:surface_count]
    target_adsorbate = target.structure.positions_ang[surface_count:]
    injected_surface, surface_translation = _surface_in_seed_frame(
        surface_run.structure_out,
        target_surface,
        target.structure.cell,
        surface_anchor_count,
    )
    adsorbate_labels = [item.label for item in adsorbate_run.fdf.atom_species]
    injected_adsorbate, adsorbate_audit = _adsorbate_in_seed_frame(
        adsorbate_run.structure_out,
        adsorbate_run.fdf.structure,
        target_adsorbate,
        target.structure.cell,
        adsorbate_labels,
    )

    cross_minimum, cross_pair = _cross_fragment_minimum(
        injected_surface,
        injected_adsorbate,
        target.structure.cell,
    )
    seed_cross_minimum, seed_cross_pair = _cross_fragment_minimum(
        target_surface,
        target_adsorbate,
        target.structure.cell,
    )
    if cross_minimum < CROSS_FRAGMENT_HARD_MIN_ANG:
        raise GeometryTransferError(
            f"{system_id}: periodic cross-fragment collision {cross_minimum:.6f} Ang "
            f"at surface atom {cross_pair[0]}, adsorbate atom {cross_pair[1]}"
        )

    positions = injected_surface + injected_adsorbate
    provenance = tuple(
        f"{surface_id}:{index}" for index in range(1, surface_count + 1)
    ) + tuple(
        f"{adsorbate_id}:{index}" for index in range(1, adsorbate_count + 1)
    )
    updated_text = _replace_coordinate_block(target, positions, mapped_species, provenance)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = root / "generated" / "geometry_transfers" / system_id / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    output_fdf = output_dir / "run.fdf"
    output_fdf.write_text(updated_text, encoding="utf-8")

    reparsed = parse_fdf(output_fdf)
    if reparsed.structure.species_indices != mapped_species:
        raise GeometryTransferError(f"{system_id}: written FDF species round-trip mismatch")
    coordinate_roundtrip_max = max(
        norm(subtract(expected, actual))
        for expected, actual in zip(positions, reparsed.structure.positions_ang)
    )
    if coordinate_roundtrip_max > 1.0e-9:
        raise GeometryTransferError(
            f"{system_id}: written FDF coordinate round-trip delta "
            f"{coordinate_roundtrip_max:.6e} Ang"
        )

    inventory: dict[str, int] = {}
    mappings: list[dict[str, object]] = []
    for target_index, (species_index, source_id) in enumerate(
        zip(mapped_species, provenance),
        1,
    ):
        item = target.species[species_index]
        inventory[item.label] = inventory.get(item.label, 0) + 1
        mappings.append(
            {
                "target_atom_index_1based": target_index,
                "source_atom_id": source_id,
                "target_species_index": species_index,
                "atomic_number": item.atomic_number,
                "label": item.label,
            }
        )

    audit: dict[str, object] = {
        "schema": "siestaflow.geometry_transfer.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "system_id": system_id,
        "coordinate_authority": "STRUCT_OUT",
        "coordinate_crosscheck": "XV",
        "target_master_fdf": str(Path(target_fdf_path)),
        "target_master_fdf_sha256": sha256(Path(target_fdf_path)),
        "generated_fdf": str(output_fdf),
        "generated_fdf_sha256": sha256(output_fdf),
        "surface_parent": surface_run.summary(),
        "adsorbate_parent": adsorbate_run.summary(),
        "surface_anchor_count": surface_anchor_count,
        "surface_translation_ang": list(surface_translation),
        "adsorbate_alignment": adsorbate_audit,
        "inventory": inventory,
        "number_of_atoms": len(positions),
        "seed_periodic_cross_fragment_minimum_ang": seed_cross_minimum,
        "seed_cross_fragment_pair_local_1based": list(seed_cross_pair),
        "generated_periodic_cross_fragment_minimum_ang": cross_minimum,
        "generated_cross_fragment_pair_local_1based": list(cross_pair),
        "coordinate_roundtrip_max_delta_ang": coordinate_roundtrip_max,
        "species_mapping_policy": "(atomic_number,label)->target ChemicalSpeciesLabel index",
        "atom_mapping": mappings,
    }
    audit_path = output_dir / "geometry_transfer_audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_fdf, audit_path, audit


__all__ = [
    "ADSORPTION_DEPENDENCIES",
    "AcceptedRun",
    "GeometryTransferError",
    "build_adsorption_fdf",
    "find_latest_accepted_run",
    "parse_fdf",
    "validate_restart_xv",
    "validate_run_directory",
]
