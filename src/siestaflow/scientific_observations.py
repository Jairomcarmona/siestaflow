"""Produce strict convergence observations from completed SIESTA artifacts.

This module is deliberately a postprocessor: it reads immutable calculation
artifacts and never alters an FDF, pseudo, or scientific decision.  The
resulting JSON is the only interchange format consumed by the convergence
evaluators.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_fdf(
    text: str, *, omit_mesh: bool, omit_kgrid: bool, omit_coordinates: bool = False,
) -> str:
    """Normalize identity, optionally excluding the swept axis or displacement."""
    output: list[str] = []
    in_kgrid = False
    in_coordinates = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        lowered = line.casefold()
        if omit_kgrid and lowered.startswith("%block kgrid.monkhorstpack"):
            in_kgrid = True
            continue
        if in_kgrid:
            if lowered.startswith("%endblock kgrid.monkhorstpack"):
                in_kgrid = False
            continue
        if omit_coordinates and lowered.startswith("%block atomiccoordinatesandatomicspecies"):
            in_coordinates = True
            continue
        if in_coordinates:
            if lowered.startswith("%endblock atomiccoordinatesandatomicspecies"):
                in_coordinates = False
            continue
        if omit_mesh and lowered.startswith("mesh.cutoff"):
            continue
        if line:
            output.append(" ".join(line.split()))
    return "\n".join(output) + "\n"


def _fdf_value(text: str, label: str) -> str:
    match = re.search(rf"^\s*{re.escape(label)}\s+(.+?)\s*$", text, re.I | re.M)
    if not match:
        raise ValueError(f"FDF does not declare {label}")
    return match.group(1).split("#", 1)[0].strip()


def _kgrid(text: str) -> dict[str, list[Any]]:
    match = re.search(
        r"%block\s+kgrid\.MonkhorstPack\s*\n(.*?)%endblock\s+kgrid\.MonkhorstPack",
        text, re.I | re.S,
    )
    if not match:
        raise ValueError("FDF does not declare %block kgrid.MonkhorstPack")
    rows = [line.split() for line in match.group(1).splitlines() if line.split()]
    if len(rows) != 3 or any(len(row) != 4 for row in rows):
        raise ValueError("kgrid.MonkhorstPack must contain three four-column rows")
    dimensions: list[int] = []
    shifts: list[str] = []
    for axis, row in enumerate(rows):
        if any(row[index] != ("1" if index == axis else "0") for index in range(3)):
            raise ValueError("only diagonal Monkhorst-Pack grids are supported")
        dimensions.append(int(row[axis]))
        shifts.append(str(float(row[3])))
    return {"dimensions": dimensions, "shifts": shifts}


def _stdout_data(text: str) -> tuple[str, list[str], bool]:
    energy = re.findall(rf"siesta:\s*E_KS\(eV\)\s*=\s*({_FLOAT})", text, re.I)
    mesh = re.findall(r"InitMesh:\s*MESH\s*=\s*(\d+)\s*x\s*(\d+)\s*x\s*(\d+)", text, re.I)
    if not energy:
        raise ValueError("SIESTA output has no final E_KS(eV) evidence")
    if not mesh:
        raise ValueError("SIESTA output has no InitMesh MESH evidence")
    if "Job completed" not in text or not re.search(r"SCF cycle converged", text, re.I):
        raise ValueError("SIESTA output does not prove normal SCF completion")
    return energy[-1], list(mesh[-1]), True


def _forces(path: Path, atom_count: int) -> list[list[str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for index, line in enumerate(lines):
        if line.strip() != str(atom_count):
            continue
        rows = lines[index + 1:index + 1 + atom_count]
        if len(rows) != atom_count:
            continue
        values: list[list[str]] = []
        for row in rows:
            fields = row.split()
            if len(fields) < 5:
                break
            try:
                values.append([str(float(fields[2])), str(float(fields[3])), str(float(fields[4]))])
            except ValueError:
                break
        if len(values) == atom_count:
            return values
    raise ValueError("FORCE_STRESS has no complete atomic-force block")


def produce_observation(
    *, axis: str, observation_id: str, fdf: Path, stdout: Path,
    force_stress: Path, pseudopotential_manifest: Path, kind: str = "PRIMARY",
    baseline_observation_id: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic Mesh or k-grid observation from real artifacts."""
    if axis not in {"mesh", "kgrid"}:
        raise ValueError("axis must be mesh or kgrid")
    if kind not in {"PRIMARY", "EGGBOX"}:
        raise ValueError("kind must be PRIMARY or EGGBOX")
    fdf_text = fdf.read_text(encoding="utf-8")
    stdout_text = stdout.read_text(encoding="utf-8", errors="replace")
    atom_count = int(_fdf_value(fdf_text, "NumberOfAtoms").split()[0])
    energy, mesh_dimensions, scf_converged = _stdout_data(stdout_text)
    try:
        magnetic_signature = _fdf_value(fdf_text, "Spin").casefold()
    except ValueError:
        # SIESTA's documented default is non-polarized; accept it only when the
        # completed output independently records one spin component.
        if not re.search(r"Number of spin components\s*=\s*1", stdout_text, re.I):
            raise ValueError("FDF omits Spin and output cannot establish its default")
        magnetic_signature = "non-polarized"
    common = {
        "schema_version": "1.0",
        "observation_id": observation_id,
        "atom_count": atom_count,
        "atom_identity_sha256": hashlib.sha256(
            _canonical_fdf(
                fdf_text, omit_mesh=True, omit_kgrid=True, omit_coordinates=True,
            ).encode("utf-8")
        ).hexdigest(),
        "structure_sha256": hashlib.sha256(
            _canonical_fdf(fdf_text, omit_mesh=True, omit_kgrid=True).encode("utf-8")
        ).hexdigest(),
        "pseudopotential_manifest_sha256": _sha256(pseudopotential_manifest),
        "input_sha256": hashlib.sha256(
            _canonical_fdf(fdf_text, omit_mesh=True, omit_kgrid=True).encode("utf-8")
        ).hexdigest(),
        "energy": {"value": energy, "unit": "eV"},
        "forces": {"unit": "eV/Ang", "values": _forces(force_stress, atom_count)},
        "scf_converged": scf_converged,
        "magnetic_signature": magnetic_signature,
    }
    if axis == "mesh":
        requested = _fdf_value(fdf_text, "Mesh.Cutoff").split()
        if len(requested) != 2 or requested[1].casefold() != "ry":
            raise ValueError("Mesh.Cutoff must use Ry")
        return {
            **common, "kind": kind,
            "requested_cutoff": {"value": str(float(requested[0])), "unit": "Ry"},
            "actual_cutoff": {"value": str(float(requested[0])), "unit": "Ry"},
            "mesh_dimensions": mesh_dimensions,
            "baseline_observation_id": baseline_observation_id,
        }
    grid = _kgrid(fdf_text)
    common["invariant_input_sha256"] = common.pop("input_sha256")
    return {**common, "requested_grid": grid, "used_grid": grid}


def main() -> int:
    parser = argparse.ArgumentParser(description="Produce canonical SIESTA convergence observation")
    parser.add_argument("--axis", required=True, choices=("mesh", "kgrid"))
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--fdf", required=True, type=Path)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--force-stress", required=True, type=Path)
    parser.add_argument("--pseudopotential-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--kind", choices=("PRIMARY", "EGGBOX"), default="PRIMARY")
    parser.add_argument("--baseline-observation-id")
    args = parser.parse_args()
    value = produce_observation(
        axis=args.axis, observation_id=args.observation_id, fdf=args.fdf,
        stdout=args.stdout, force_stress=args.force_stress,
        pseudopotential_manifest=args.pseudopotential_manifest, kind=args.kind,
        baseline_observation_id=args.baseline_observation_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
