"""Engine-neutral, fail-closed k-point convergence evidence decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{field} must be a finite {'positive ' if positive else ''}decimal")
    return result


def _sha256(value: object, field: str) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return text


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{field} schema mismatch")


@dataclass(frozen=True, order=True)
class KGrid:
    dimensions: tuple[int, int, int]
    shifts: tuple[Decimal, Decimal, Decimal]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, field: str) -> "KGrid":
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be a mapping")
        _exact_keys(value, {"dimensions", "shifts"}, field)
        if not isinstance(value["dimensions"], list) or not isinstance(value["shifts"], list):
            raise ValueError(f"{field} dimensions and shifts must be lists")
        dimensions = tuple(value["dimensions"])
        shifts = tuple(value["shifts"])
        if (
            len(dimensions) != 3 or len(shifts) != 3
            or any(type(item) is not int or item <= 0 for item in dimensions)
        ):
            raise ValueError(f"{field} requires three positive integer dimensions")
        parsed_shifts = tuple(_decimal(item, f"{field}.shifts") for item in shifts)
        if any(item < 0 or item >= 1 for item in parsed_shifts):
            raise ValueError(f"{field} shifts must be fractions in [0,1)")
        return cls(dimensions, parsed_shifts)  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimensions": list(self.dimensions),
            "shifts": [format(item, "f") for item in self.shifts],
        }


def _strictly_refines(left: KGrid, right: KGrid) -> bool:
    return (
        left.shifts == right.shifts
        and all(a <= b for a, b in zip(left.dimensions, right.dimensions))
        and any(a < b for a, b in zip(left.dimensions, right.dimensions))
    )


@dataclass(frozen=True)
class KGridConvergenceRule:
    rule_id: str
    initial_grids: tuple[KGrid, ...]
    extension_grids: tuple[KGrid, ...]
    energy_tolerance_mev_per_atom: Decimal
    force_tolerance_ev_per_ang: Decimal
    consecutive_levels: int
    require_magnetic_stability: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "KGridConvergenceRule":
        expected = {
            "schema_version", "rule_id", "parameter", "initial_values",
            "extension_values", "energy_tolerance", "force_tolerance",
            "consecutive_levels", "require_magnetic_stability", "selection",
            "final_authority",
        }
        _exact_keys(value, expected, "k-grid convergence rule")
        if value["schema_version"] != "1.0" or value["parameter"] != "kgrid.MonkhorstPack":
            raise ValueError("unsupported k-grid convergence rule identity")
        if value["selection"] != "LOWEST_PASSING" or value["final_authority"] != "HUMAN_REVIEW":
            raise ValueError("selection must remain LOWEST_PASSING under HUMAN_REVIEW")
        energy = value["energy_tolerance"]
        force = value["force_tolerance"]
        if not isinstance(energy, Mapping) or set(energy) != {"value", "unit"} or energy["unit"] != "meV/atom":
            raise ValueError("energy_tolerance must use meV/atom")
        if not isinstance(force, Mapping) or set(force) != {"value", "unit"} or force["unit"] != "eV/Ang":
            raise ValueError("force_tolerance must use eV/Ang")
        if not isinstance(value["initial_values"], list) or not isinstance(value["extension_values"], list):
            raise ValueError("k-grid series must be lists")
        if type(value["consecutive_levels"]) is not int or type(value["require_magnetic_stability"]) is not bool:
            raise ValueError("k-grid levels and magnetic requirement have invalid types")
        initial = tuple(KGrid.from_mapping(item, field="initial_values") for item in value["initial_values"] if isinstance(item, Mapping))
        extension = tuple(KGrid.from_mapping(item, field="extension_values") for item in value["extension_values"] if isinstance(item, Mapping))
        if len(initial) != len(value["initial_values"]) or len(extension) != len(value["extension_values"]):
            raise ValueError("k-grid values must be mappings")
        all_grids = initial + extension
        levels = value["consecutive_levels"]
        if len(initial) < 3 or levels < 2 or levels > len(initial):
            raise ValueError("initial k-grid series and consecutive_levels are inconsistent")
        if any(not _strictly_refines(left, right) for left, right in zip(all_grids, all_grids[1:])):
            raise ValueError("k-grid values must strictly refine with identical shifts")
        rule_id = str(value["rule_id"])
        if not rule_id:
            raise ValueError("rule_id is required")
        return cls(
            rule_id, initial, extension,
            _decimal(energy["value"], "energy_tolerance", positive=True),
            _decimal(force["value"], "force_tolerance", positive=True),
            levels, value["require_magnetic_stability"],
        )


@dataclass(frozen=True)
class KGridObservation:
    observation_id: str
    requested_grid: KGrid
    used_grid: KGrid
    atom_count: int
    atom_identity_sha256: str
    structure_sha256: str
    pseudopotential_manifest_sha256: str
    invariant_input_sha256: str
    energy_ev: Decimal
    forces_ev_per_ang: tuple[tuple[Decimal, Decimal, Decimal], ...]
    scf_converged: bool
    magnetic_signature: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "KGridObservation":
        expected = {
            "schema_version", "observation_id", "requested_grid", "used_grid",
            "atom_count", "atom_identity_sha256", "structure_sha256",
            "pseudopotential_manifest_sha256", "invariant_input_sha256", "energy",
            "forces", "scf_converged", "magnetic_signature",
        }
        _exact_keys(value, expected, "k-grid observation")
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported k-grid observation schema")
        energy = value["energy"]
        forces = value["forces"]
        if not isinstance(energy, Mapping) or set(energy) != {"value", "unit"} or energy["unit"] != "eV":
            raise ValueError("energy must use eV")
        if not isinstance(forces, Mapping) or set(forces) != {"values", "unit"} or forces["unit"] != "eV/Ang":
            raise ValueError("forces must use eV/Ang")
        atom_count = value["atom_count"]
        if type(atom_count) is not int or atom_count <= 0 or type(value["scf_converged"]) is not bool:
            raise ValueError("atom_count and SCF state are invalid")
        vectors = tuple(tuple(_decimal(component, "forces.values") for component in vector) for vector in forces["values"])
        if len(vectors) != atom_count or any(len(vector) != 3 for vector in vectors):
            raise ValueError("force vectors must match atom_count and have three components")
        observation_id = str(value["observation_id"])
        magnetic = str(value["magnetic_signature"])
        if not observation_id or not magnetic:
            raise ValueError("observation identity and magnetic signature are required")
        return cls(
            observation_id,
            KGrid.from_mapping(value["requested_grid"], field="requested_grid"),
            KGrid.from_mapping(value["used_grid"], field="used_grid"),
            atom_count,
            _sha256(value["atom_identity_sha256"], "atom_identity_sha256"),
            _sha256(value["structure_sha256"], "structure_sha256"),
            _sha256(value["pseudopotential_manifest_sha256"], "pseudopotential_manifest_sha256"),
            _sha256(value["invariant_input_sha256"], "invariant_input_sha256"),
            _decimal(energy["value"], "energy"), vectors, value["scf_converged"], magnetic,
        )


def _force_delta(left: KGridObservation, right: KGridObservation) -> Decimal:
    return max(sum((a - b) ** 2 for a, b in zip(left_vector, right_vector)).sqrt()
               for left_vector, right_vector in zip(left.forces_ev_per_ang, right.forces_ev_per_ang))


def _same_identity(left: KGridObservation, right: KGridObservation) -> bool:
    return (
        left.atom_count == right.atom_count
        and left.atom_identity_sha256 == right.atom_identity_sha256
        and left.structure_sha256 == right.structure_sha256
        and left.pseudopotential_manifest_sha256 == right.pseudopotential_manifest_sha256
        and left.invariant_input_sha256 == right.invariant_input_sha256
    )


@dataclass(frozen=True)
class KGridConvergenceReport:
    status: str
    selected_grid: KGrid | None
    reference_grid: KGrid | None
    next_actions: tuple[dict[str, Any], ...]
    levels: tuple[dict[str, Any], ...]
    reasons: tuple[str, ...]
    final_authority: str = "HUMAN_REVIEW"

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_authority": self.final_authority,
            "levels": list(self.levels), "next_actions": list(self.next_actions),
            "reasons": list(self.reasons),
            "reference_grid": self.reference_grid.as_dict() if self.reference_grid else None,
            "selected_grid": self.selected_grid.as_dict() if self.selected_grid else None,
            "status": self.status,
        }


class KGridConvergenceEvaluator:
    def evaluate(self, rule: KGridConvergenceRule, observations: Sequence[KGridObservation]) -> KGridConvergenceReport:
        if len({item.observation_id for item in observations}) != len(observations):
            raise ValueError("observation_id values must be unique")
        primary = {item.requested_grid: item for item in observations}
        if len(primary) != len(observations):
            raise ValueError("one observation is allowed per requested k-grid")
        allowed = rule.initial_grids + rule.extension_grids
        if any(item.requested_grid not in allowed or item.requested_grid != item.used_grid for item in observations):
            raise ValueError("observation k-grid is outside the rule or differs from its used grid")
        missing_initial = [item for item in rule.initial_grids if item not in primary]
        if missing_initial:
            return self._needs("NEEDS_PRIMARY_SERIES", missing_initial, "initial series is incomplete")
        using_extension = any(item in primary for item in rule.extension_grids)
        if using_extension:
            missing_extension = [item for item in rule.extension_grids if item not in primary]
            if missing_extension:
                return self._needs("NEEDS_EXTENSION_SERIES", missing_extension, "extension series is incomplete")
            active = allowed
        else:
            active = rule.initial_grids
        ordered = [primary[item] for item in active]
        if any(not _same_identity(ordered[0], item) for item in ordered[1:]):
            raise ValueError("k-grid observations do not share scientific identity")
        reference = ordered[-1]
        passing: list[bool] = []
        levels: list[dict[str, Any]] = []
        for item in ordered:
            energy_delta = abs(item.energy_ev - reference.energy_ev) * Decimal(1000) / item.atom_count
            force_delta = _force_delta(item, reference)
            magnetic_ok = not rule.require_magnetic_stability or item.magnetic_signature == reference.magnetic_signature
            passed = item.scf_converged and reference.scf_converged and energy_delta <= rule.energy_tolerance_mev_per_atom and force_delta <= rule.force_tolerance_ev_per_ang and magnetic_ok
            passing.append(passed)
            levels.append({
                "energy_delta_mev_per_atom": format(energy_delta, "f"),
                "force_vector_delta_ev_per_ang": format(force_delta, "f"),
                "grid": item.used_grid.as_dict(), "magnetic_stability": magnetic_ok,
                "passed": passed, "scf_converged": item.scf_converged,
            })
        for index in range(len(ordered) - rule.consecutive_levels + 1):
            window = ordered[index:index + rule.consecutive_levels]
            if all(passing[index:index + rule.consecutive_levels]) and all(
                _strictly_refines(left.used_grid, right.used_grid) for left, right in zip(window, window[1:])
            ):
                return KGridConvergenceReport(
                    "READY_FOR_HUMAN_REVIEW", window[0].requested_grid, reference.requested_grid,
                    (), tuple(levels), ("lowest consecutive passing k-grid selected for human review",),
                )
        if not using_extension and rule.extension_grids:
            return self._needs("NEEDS_EXTENSION_SERIES", rule.extension_grids, "initial series has no consecutive passing k-grid", levels=tuple(levels), reference=reference.requested_grid)
        return KGridConvergenceReport("REVIEW_REQUIRED", None, reference.requested_grid, (), tuple(levels), ("no k-grid satisfies every convergence criterion",))

    @staticmethod
    def _needs(status: str, grids: Sequence[KGrid], reason: str, *, levels: tuple[dict[str, Any], ...] = (), reference: KGrid | None = None) -> KGridConvergenceReport:
        return KGridConvergenceReport(
            status, None, reference,
            tuple({"kind": "PRIMARY", "grid": item.as_dict()} for item in grids), levels, (reason,),
        )


def evaluate_kgrid_files(rule_path: Path, observation_paths: Sequence[Path], output: Path) -> KGridConvergenceReport:
    try:
        rule_raw = json.loads(rule_path.read_text(encoding="utf-8"))
        observations_raw = [json.loads(path.read_text(encoding="utf-8")) for path in observation_paths]
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load k-grid convergence evidence: {exc}") from exc
    if not isinstance(rule_raw, Mapping) or any(not isinstance(item, Mapping) for item in observations_raw):
        raise ValueError("k-grid convergence evidence must contain JSON mappings")
    rule = KGridConvergenceRule.from_mapping(rule_raw)
    observations = tuple(KGridObservation.from_mapping(item) for item in observations_raw)
    report = KGridConvergenceEvaluator().evaluate(rule, observations)
    payload = {
        "schema_version": "1.0", "rule_id": rule.rule_id,
        "rule_sha256": hashlib.sha256(rule_path.read_bytes()).hexdigest(),
        "observations": [
            {"observation_id": item.observation_id, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for item, path in zip(observations, observation_paths)
        ],
        **report.as_dict(),
    }
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return report


def kgrid_adaptive_dag(rule: KGridConvergenceRule) -> dict[str, Any]:
    """Return the deterministic initial DAG and declared extension boundary."""
    primary = [
        {
            "task_id": "kgrid_primary_" + "x".join(map(str, grid.dimensions)),
            "kind": "PRIMARY",
            "depends_on": [],
        }
        for grid in rule.initial_grids
    ]
    task_ids = [item["task_id"] for item in primary]
    return {
        "schema_version": "1.0",
        "rule_id": rule.rule_id,
        "initial_tasks": primary + [{"task_id": "kgrid_evaluate", "kind": "EVALUATE", "depends_on": task_ids}],
        "conditional_expansions": {
            "NEEDS_EXTENSION_SERIES": "declared extension PRIMARY tasks, then EVALUATE",
            "READY_FOR_HUMAN_REVIEW": "stop; no scientific propagation before human approval",
            "REVIEW_REQUIRED": "stop for human scientific review",
        },
        "execution_authorized": False,
        "final_authority": "HUMAN_REVIEW",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--rule", required=True, type=Path)
    evaluate.add_argument("--observation", required=True, action="append", type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        evaluate_kgrid_files(args.rule, args.observation, args.output)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised in prepared package.
    raise SystemExit(main())
