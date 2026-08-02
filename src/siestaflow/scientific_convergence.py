"""Engine-neutral, fail-closed numerical-convergence decisions.

The module evaluates evidence; it neither launches an engine nor grants
scientific acceptance.  Numeric grids and tolerances live in project data so
the same contract can be reused for different systems and pseudopotentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        qualifier = "positive " if positive else ""
        raise ValueError(f"{field} must be a finite {qualifier}decimal")
    return result


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{field} schema mismatch")


def _sha256(value: object, field: str) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return text


@dataclass(frozen=True)
class MeshConvergenceRule:
    rule_id: str
    initial_cutoffs_ry: tuple[Decimal, ...]
    extension_cutoffs_ry: tuple[Decimal, ...]
    energy_tolerance_mev_per_atom: Decimal
    force_tolerance_ev_per_ang: Decimal
    consecutive_levels: int
    eggbox_displacement_fraction: tuple[Decimal, Decimal, Decimal]
    require_magnetic_stability: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MeshConvergenceRule":
        expected = {
            "schema_version", "rule_id", "parameter", "initial_values",
            "extension_values", "cutoff_unit", "energy_tolerance",
            "force_tolerance", "consecutive_levels", "eggbox",
            "require_magnetic_stability", "selection", "final_authority",
        }
        _exact_keys(value, expected, "mesh convergence rule")
        if value["schema_version"] != "1.0" or value["parameter"] != "Mesh.Cutoff":
            raise ValueError("unsupported mesh convergence rule identity")
        if value["cutoff_unit"] != "Ry":
            raise ValueError("cutoff_unit must be Ry")
        energy = value["energy_tolerance"]
        force = value["force_tolerance"]
        eggbox = value["eggbox"]
        if not isinstance(energy, Mapping) or set(energy) != {"value", "unit"} or energy["unit"] != "meV/atom":
            raise ValueError("energy_tolerance must use meV/atom")
        if not isinstance(force, Mapping) or set(force) != {"value", "unit"} or force["unit"] != "eV/Ang":
            raise ValueError("force_tolerance must use eV/Ang")
        if not isinstance(eggbox, Mapping) or set(eggbox) != {"required", "displacement_fraction"}:
            raise ValueError("eggbox schema mismatch")
        if eggbox["required"] is not True:
            raise ValueError("eggbox confirmation must be required")
        if value["selection"] != "LOWEST_PASSING" or value["final_authority"] != "HUMAN_REVIEW":
            raise ValueError("selection must remain LOWEST_PASSING under HUMAN_REVIEW")
        if not isinstance(value["initial_values"], list) or not isinstance(value["extension_values"], list):
            raise ValueError("cutoff series must be lists")
        if type(value["consecutive_levels"]) is not int:
            raise ValueError("consecutive_levels must be an integer")
        if type(value["require_magnetic_stability"]) is not bool:
            raise ValueError("require_magnetic_stability must be boolean")
        if not isinstance(eggbox["displacement_fraction"], list):
            raise ValueError("eggbox displacement must be a list")
        initial = tuple(_decimal(item, "initial_values", positive=True) for item in value["initial_values"])
        extension = tuple(_decimal(item, "extension_values", positive=True) for item in value["extension_values"])
        levels = value["consecutive_levels"]
        displacement = tuple(
            _decimal(item, "eggbox.displacement_fraction")
            for item in eggbox["displacement_fraction"]
        )
        if len(initial) < 3 or levels < 2 or levels > len(initial):
            raise ValueError("initial series and consecutive_levels are inconsistent")
        all_cutoffs = initial + extension
        if any(left >= right for left, right in zip(all_cutoffs, all_cutoffs[1:])):
            raise ValueError("cutoff values must be unique and strictly increasing")
        if len(displacement) != 3 or any(item < 0 or item >= 1 for item in displacement):
            raise ValueError("eggbox displacement must contain three fractions in [0,1)")
        rule_id = str(value["rule_id"])
        if not rule_id:
            raise ValueError("rule_id is required")
        return cls(
            rule_id=rule_id,
            initial_cutoffs_ry=initial,
            extension_cutoffs_ry=extension,
            energy_tolerance_mev_per_atom=_decimal(energy["value"], "energy_tolerance", positive=True),
            force_tolerance_ev_per_ang=_decimal(force["value"], "force_tolerance", positive=True),
            consecutive_levels=levels,
            eggbox_displacement_fraction=displacement,  # type: ignore[arg-type]
            require_magnetic_stability=value["require_magnetic_stability"],
        )


@dataclass(frozen=True)
class MeshObservation:
    observation_id: str
    kind: str
    requested_cutoff_ry: Decimal
    actual_cutoff_ry: Decimal
    mesh_dimensions: tuple[int, int, int]
    atom_count: int
    atom_identity_sha256: str
    structure_sha256: str
    pseudopotential_manifest_sha256: str
    input_sha256: str
    energy_ev: Decimal
    forces_ev_per_ang: tuple[tuple[Decimal, Decimal, Decimal], ...]
    scf_converged: bool
    magnetic_signature: str
    baseline_observation_id: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MeshObservation":
        expected = {
            "schema_version", "observation_id", "kind", "requested_cutoff",
            "actual_cutoff", "mesh_dimensions", "atom_count",
            "atom_identity_sha256", "structure_sha256",
            "pseudopotential_manifest_sha256", "input_sha256", "energy",
            "forces", "scf_converged", "magnetic_signature",
            "baseline_observation_id",
        }
        _exact_keys(value, expected, "mesh observation")
        if value["schema_version"] != "1.0" or value["kind"] not in {"PRIMARY", "EGGBOX"}:
            raise ValueError("unsupported mesh observation identity")
        requested = value["requested_cutoff"]
        actual = value["actual_cutoff"]
        energy = value["energy"]
        forces = value["forces"]
        for item, field, unit in (
            (requested, "requested_cutoff", "Ry"),
            (actual, "actual_cutoff", "Ry"),
            (energy, "energy", "eV"),
        ):
            if not isinstance(item, Mapping) or set(item) != {"value", "unit"} or item["unit"] != unit:
                raise ValueError(f"{field} must use {unit}")
        if not isinstance(forces, Mapping) or set(forces) != {"values", "unit"} or forces["unit"] != "eV/Ang":
            raise ValueError("forces must use eV/Ang")
        dimensions = tuple(int(item) for item in value["mesh_dimensions"])
        atom_count = int(value["atom_count"])
        vectors = tuple(
            tuple(_decimal(component, "forces.values") for component in vector)
            for vector in forces["values"]
        )
        if len(dimensions) != 3 or any(item <= 0 for item in dimensions):
            raise ValueError("mesh_dimensions must contain three positive integers")
        if atom_count <= 0 or len(vectors) != atom_count or any(len(vector) != 3 for vector in vectors):
            raise ValueError("force vectors must match atom_count and have three components")
        observation_id = str(value["observation_id"])
        magnetic_signature = str(value["magnetic_signature"])
        if not observation_id or not magnetic_signature or type(value["scf_converged"]) is not bool:
            raise ValueError("observation identity, SCF state and magnetic signature are required")
        baseline = value["baseline_observation_id"]
        if value["kind"] == "PRIMARY" and baseline is not None:
            raise ValueError("primary observation cannot declare an eggbox baseline")
        if value["kind"] == "EGGBOX" and (not isinstance(baseline, str) or not baseline):
            raise ValueError("eggbox observation requires a baseline_observation_id")
        return cls(
            observation_id=observation_id,
            kind=str(value["kind"]),
            requested_cutoff_ry=_decimal(requested["value"], "requested_cutoff", positive=True),
            actual_cutoff_ry=_decimal(actual["value"], "actual_cutoff", positive=True),
            mesh_dimensions=dimensions,  # type: ignore[arg-type]
            atom_count=atom_count,
            atom_identity_sha256=_sha256(value["atom_identity_sha256"], "atom_identity_sha256"),
            structure_sha256=_sha256(value["structure_sha256"], "structure_sha256"),
            pseudopotential_manifest_sha256=_sha256(value["pseudopotential_manifest_sha256"], "pseudopotential_manifest_sha256"),
            input_sha256=_sha256(value["input_sha256"], "input_sha256"),
            energy_ev=_decimal(energy["value"], "energy"),
            forces_ev_per_ang=vectors,  # type: ignore[arg-type]
            scf_converged=value["scf_converged"],
            magnetic_signature=magnetic_signature,
            baseline_observation_id=baseline,
        )


def _force_delta(left: MeshObservation, right: MeshObservation) -> Decimal:
    return max(
        sum((a - b) ** 2 for a, b in zip(left_vector, right_vector)).sqrt()
        for left_vector, right_vector in zip(left.forces_ev_per_ang, right.forces_ev_per_ang)
    )


def _same_scientific_identity(left: MeshObservation, right: MeshObservation) -> bool:
    return (
        left.atom_count == right.atom_count
        and left.atom_identity_sha256 == right.atom_identity_sha256
        and left.pseudopotential_manifest_sha256 == right.pseudopotential_manifest_sha256
    )


@dataclass(frozen=True)
class MeshConvergenceReport:
    status: str
    selected_cutoff_ry: str | None
    reference_cutoff_ry: str | None
    next_actions: tuple[dict[str, Any], ...]
    levels: tuple[dict[str, Any], ...]
    reasons: tuple[str, ...]
    final_authority: str = "HUMAN_REVIEW"

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_authority": self.final_authority,
            "levels": list(self.levels),
            "next_actions": list(self.next_actions),
            "reasons": list(self.reasons),
            "reference_cutoff_ry": self.reference_cutoff_ry,
            "selected_cutoff_ry": self.selected_cutoff_ry,
            "status": self.status,
        }


class MeshConvergenceEvaluator:
    """Evaluate one completed wave and describe the next DAG expansion."""

    def evaluate(
        self, rule: MeshConvergenceRule, observations: Sequence[MeshObservation]
    ) -> MeshConvergenceReport:
        ids = [item.observation_id for item in observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation_id values must be unique")
        primary = {item.requested_cutoff_ry: item for item in observations if item.kind == "PRIMARY"}
        eggbox = [item for item in observations if item.kind == "EGGBOX"]
        if len(primary) != sum(item.kind == "PRIMARY" for item in observations):
            raise ValueError("one primary observation is allowed per requested cutoff")
        allowed = rule.initial_cutoffs_ry + rule.extension_cutoffs_ry
        if any(item.requested_cutoff_ry not in allowed for item in observations):
            raise ValueError("observation cutoff is outside the rule")
        primary_by_id = {item.observation_id: item for item in primary.values()}
        eggbox_baselines: set[str] = set()
        for item in eggbox:
            baseline = primary_by_id.get(item.baseline_observation_id or "")
            if baseline is None or baseline.requested_cutoff_ry != item.requested_cutoff_ry:
                raise ValueError("eggbox observation has an unknown or mismatched baseline")
            if item.baseline_observation_id in eggbox_baselines:
                raise ValueError("one eggbox observation is allowed per baseline")
            eggbox_baselines.add(item.baseline_observation_id or "")
        missing_initial = [cutoff for cutoff in rule.initial_cutoffs_ry if cutoff not in primary]
        if missing_initial:
            return self._needs("NEEDS_PRIMARY_SERIES", missing_initial, "PRIMARY", "initial series is incomplete")
        using_extension = any(cutoff in primary for cutoff in rule.extension_cutoffs_ry)
        if using_extension:
            missing_extension = [cutoff for cutoff in rule.extension_cutoffs_ry if cutoff not in primary]
            if missing_extension:
                return self._needs("NEEDS_EXTENSION_SERIES", missing_extension, "PRIMARY", "extension series is incomplete")
            active = allowed
        else:
            active = rule.initial_cutoffs_ry
        ordered = [primary[cutoff] for cutoff in active]
        baseline = ordered[0]
        for item in ordered[1:]:
            if not _same_scientific_identity(baseline, item) or item.structure_sha256 != baseline.structure_sha256:
                raise ValueError("primary observations do not share scientific identity")
        reference = ordered[-1]
        levels: list[dict[str, Any]] = []
        passing: list[bool] = []
        for item in ordered:
            energy_delta = abs(item.energy_ev - reference.energy_ev) * Decimal(1000) / item.atom_count
            force_delta = _force_delta(item, reference)
            magnetic_ok = not rule.require_magnetic_stability or item.magnetic_signature == reference.magnetic_signature
            passed = (
                item.scf_converged
                and reference.scf_converged
                and energy_delta <= rule.energy_tolerance_mev_per_atom
                and force_delta <= rule.force_tolerance_ev_per_ang
                and magnetic_ok
            )
            passing.append(passed)
            levels.append({
                "actual_cutoff_ry": format(item.actual_cutoff_ry, "f"),
                "energy_delta_mev_per_atom": format(energy_delta, "f"),
                "force_vector_delta_ev_per_ang": format(force_delta, "f"),
                "magnetic_stability": magnetic_ok,
                "mesh_dimensions": list(item.mesh_dimensions),
                "passed": passed,
                "requested_cutoff_ry": format(item.requested_cutoff_ry, "f"),
                "scf_converged": item.scf_converged,
            })
        candidate_indexes = []
        for start in range(0, len(ordered) - rule.consecutive_levels + 1):
            window = ordered[start : start + rule.consecutive_levels]
            if all(passing[start : start + rule.consecutive_levels]) and len({item.mesh_dimensions for item in window}) == len(window):
                candidate_indexes.append(start)
        for index in candidate_indexes:
            candidate = ordered[index]
            confirmation = [item for item in eggbox if item.baseline_observation_id == candidate.observation_id]
            if not confirmation:
                return MeshConvergenceReport(
                    "NEEDS_EGGBOX_CONFIRMATION", format(candidate.requested_cutoff_ry, "f"),
                    format(reference.requested_cutoff_ry, "f"),
                    ({"kind": "EGGBOX", "requested_cutoff_ry": format(candidate.requested_cutoff_ry, "f"),
                      "baseline_observation_id": candidate.observation_id,
                      "displacement_fraction": [format(item, "f") for item in rule.eggbox_displacement_fraction]},),
                    tuple(levels), ("lowest consecutive passing level requires eggbox confirmation",),
                )
            shifted = confirmation[0]
            if not _same_scientific_identity(candidate, shifted):
                raise ValueError("eggbox observation does not share scientific identity")
            energy_delta = abs(candidate.energy_ev - shifted.energy_ev) * Decimal(1000) / candidate.atom_count
            force_delta = _force_delta(candidate, shifted)
            magnetic_ok = not rule.require_magnetic_stability or candidate.magnetic_signature == shifted.magnetic_signature
            if (
                shifted.scf_converged and energy_delta <= rule.energy_tolerance_mev_per_atom
                and force_delta <= rule.force_tolerance_ev_per_ang and magnetic_ok
            ):
                return MeshConvergenceReport(
                    "READY_FOR_HUMAN_REVIEW", format(candidate.requested_cutoff_ry, "f"),
                    format(reference.requested_cutoff_ry, "f"), (), tuple(levels),
                    ("lowest passing cutoff has consecutive and eggbox evidence",),
                )
        if not using_extension and rule.extension_cutoffs_ry:
            return self._needs(
                "NEEDS_EXTENSION_SERIES", rule.extension_cutoffs_ry, "PRIMARY",
                "initial series has no fully confirmed candidate",
                levels=tuple(levels), reference=reference.requested_cutoff_ry,
            )
        return MeshConvergenceReport(
            "REVIEW_REQUIRED", None, format(reference.requested_cutoff_ry, "f"), (),
            tuple(levels), ("no cutoff satisfies every convergence and eggbox criterion",),
        )

    @staticmethod
    def _needs(
        status: str, cutoffs: Sequence[Decimal], kind: str, reason: str, *,
        levels: tuple[dict[str, Any], ...] = (), reference: Decimal | None = None,
    ) -> MeshConvergenceReport:
        actions = tuple({"kind": kind, "requested_cutoff_ry": format(item, "f")} for item in cutoffs)
        return MeshConvergenceReport(
            status, None, format(reference, "f") if reference is not None else None,
            actions, levels, (reason,),
        )


def mesh_adaptive_dag(rule: MeshConvergenceRule) -> dict[str, Any]:
    """Return the deterministic initial DAG and bounded conditional expansions."""
    primary = [
        {"task_id": f"mesh_primary_{format(cutoff, 'f').replace('.', '_')}_ry", "kind": "PRIMARY", "depends_on": []}
        for cutoff in rule.initial_cutoffs_ry
    ]
    task_ids = [item["task_id"] for item in primary]
    return {
        "schema_version": "1.0",
        "rule_id": rule.rule_id,
        "initial_tasks": primary + [{"task_id": "mesh_evaluate", "kind": "EVALUATE", "depends_on": task_ids}],
        "conditional_expansions": {
            "NEEDS_EGGBOX_CONFIRMATION": "one EGGBOX task for the reported candidate, then EVALUATE",
            "NEEDS_EXTENSION_SERIES": "declared extension PRIMARY tasks, then EVALUATE",
            "READY_FOR_HUMAN_REVIEW": "stop; no scientific propagation before human approval",
            "REVIEW_REQUIRED": "stop for human scientific review",
        },
        "execution_authorized": False,
        "final_authority": "HUMAN_REVIEW",
    }
