from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from siestaflow.scientific_convergence import (
    MeshConvergenceEvaluator,
    MeshConvergenceRule,
    MeshObservation,
    mesh_adaptive_dag,
)


HASHES = {name: character * 64 for name, character in zip(("atoms", "structure", "pseudo", "input"), "abcd")}


def rule_data() -> dict:
    return {
        "schema_version": "1.0", "rule_id": "TEST_MESH_V1", "parameter": "Mesh.Cutoff",
        "initial_values": ["100", "200", "300", "400"], "extension_values": ["500", "600"],
        "cutoff_unit": "Ry", "energy_tolerance": {"value": "1", "unit": "meV/atom"},
        "force_tolerance": {"value": "0.01", "unit": "eV/Ang"}, "consecutive_levels": 2,
        "eggbox": {"required": True, "displacement_fraction": ["0.5", "0.5", "0.5"]},
        "require_magnetic_stability": True, "selection": "LOWEST_PASSING", "final_authority": "HUMAN_REVIEW",
    }


def observation(cutoff: int, energy: str, force: str, *, kind: str = "PRIMARY", baseline: str | None = None,
                mesh: tuple[int, int, int] | None = None, magnetic: str = "FM", scf: bool = True) -> MeshObservation:
    return MeshObservation.from_mapping({
        "schema_version": "1.0", "observation_id": f"{kind.lower()}-{cutoff}", "kind": kind,
        "requested_cutoff": {"value": str(cutoff), "unit": "Ry"},
        "actual_cutoff": {"value": str(cutoff + 1), "unit": "Ry"},
        "mesh_dimensions": list(mesh or (cutoff // 10, cutoff // 10 + 1, cutoff // 10 + 2)),
        "atom_count": 2, "atom_identity_sha256": HASHES["atoms"],
        "structure_sha256": HASHES["structure"] if kind == "PRIMARY" else "e" * 64,
        "pseudopotential_manifest_sha256": HASHES["pseudo"], "input_sha256": HASHES["input"],
        "energy": {"value": energy, "unit": "eV"},
        "forces": {"unit": "eV/Ang", "values": [[force, "0", "0"], ["0", force, "0"]]},
        "scf_converged": scf, "magnetic_signature": magnetic, "baseline_observation_id": baseline,
    })


def converged_primary() -> list[MeshObservation]:
    return [
        observation(100, "-19.990", "0.030"), observation(200, "-19.999", "0.005"),
        observation(300, "-19.9995", "0.004"), observation(400, "-20.000", "0.000"),
    ]


def test_rule_is_data_driven_and_dag_is_bounded() -> None:
    rule = MeshConvergenceRule.from_mapping(rule_data())
    dag = mesh_adaptive_dag(rule)
    assert len(dag["initial_tasks"]) == 5
    assert dag["initial_tasks"][-1]["depends_on"] == [item["task_id"] for item in dag["initial_tasks"][:-1]]
    assert dag["execution_authorized"] is False
    assert dag["final_authority"] == "HUMAN_REVIEW"


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda value: value.update(cutoff_unit="eV"), "cutoff_unit"),
        (lambda value: value["energy_tolerance"].update(unit="eV/cell"), "meV/atom"),
        (lambda value: value.update(selection="MINIMUM_ENERGY"), "LOWEST_PASSING"),
        (lambda value: value.update(initial_values=["200", "100", "300"]), "strictly increasing"),
    ],
)
def test_rule_rejects_unsafe_or_ambiguous_contracts(mutation, message: str) -> None:
    value = rule_data()
    mutation(value)
    with pytest.raises(ValueError, match=message):
        MeshConvergenceRule.from_mapping(value)


def test_missing_primary_wave_produces_dag_actions_without_selecting() -> None:
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), [])
    assert report.status == "NEEDS_PRIMARY_SERIES"
    assert [item["requested_cutoff_ry"] for item in report.next_actions] == ["100", "200", "300", "400"]
    assert report.selected_cutoff_ry is None


def test_lowest_consecutive_candidate_requires_eggbox() -> None:
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), converged_primary())
    assert report.status == "NEEDS_EGGBOX_CONFIRMATION"
    assert report.selected_cutoff_ry == "200"
    assert report.reference_cutoff_ry == "400"
    assert report.next_actions[0]["baseline_observation_id"] == "primary-200"


def test_passing_eggbox_emits_review_not_automatic_acceptance() -> None:
    records = converged_primary()
    records.append(observation(200, "-19.9994", "0.004", kind="EGGBOX", baseline="primary-200"))
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), records)
    assert report.status == "READY_FOR_HUMAN_REVIEW"
    assert report.final_authority == "HUMAN_REVIEW"
    assert report.selected_cutoff_ry == "200"


def test_energy_is_normalized_per_atom_and_force_vectors_are_compared() -> None:
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), converged_primary())
    level = next(item for item in report.levels if item["requested_cutoff_ry"] == "200")
    assert Decimal(level["energy_delta_mev_per_atom"]) == Decimal("0.5")
    assert Decimal(level["force_vector_delta_ev_per_ang"]) == Decimal("0.005")


def test_false_plateau_with_identical_meshes_is_not_consecutive() -> None:
    records = converged_primary()
    records[2] = observation(300, "-19.9995", "0.004", mesh=records[1].mesh_dimensions)
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), records)
    assert report.status == "NEEDS_EGGBOX_CONFIRMATION"
    assert report.selected_cutoff_ry == "300"


@pytest.mark.parametrize("field", ["scf", "magnetic"])
def test_failed_scf_or_magnetic_inversion_blocks_candidate(field: str) -> None:
    records = converged_primary()
    records[1] = observation(200, "-19.999", "0.005", scf=field != "scf", magnetic="AFM" if field == "magnetic" else "FM")
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), records)
    assert report.selected_cutoff_ry == "300"


def test_failed_eggbox_advances_to_next_eligible_candidate() -> None:
    records = converged_primary()
    records.append(observation(200, "-19.900", "0.2", kind="EGGBOX", baseline="primary-200"))
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), records)
    assert report.status == "NEEDS_EGGBOX_CONFIRMATION"
    assert report.selected_cutoff_ry == "300"


def test_nonconverged_initial_series_requests_declared_extension() -> None:
    records = [
        observation(100, "-19", "0.3"), observation(200, "-19.4", "0.2"),
        observation(300, "-19.7", "0.1"), observation(400, "-20", "0"),
    ]
    report = MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(rule_data()), records)
    assert report.status == "NEEDS_EXTENSION_SERIES"
    assert [item["requested_cutoff_ry"] for item in report.next_actions] == ["500", "600"]


def test_tampered_identity_duplicate_or_bad_units_fail_closed() -> None:
    records = converged_primary()
    data = rule_data()
    with pytest.raises(ValueError, match="unique"):
        MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(data), records + [records[0]])
    altered = deepcopy(records)
    object.__setattr__(altered[1], "pseudopotential_manifest_sha256", "f" * 64)
    with pytest.raises(ValueError, match="scientific identity"):
        MeshConvergenceEvaluator().evaluate(MeshConvergenceRule.from_mapping(data), altered)
    raw = {
        "schema_version": "1.0", "observation_id": "x", "kind": "PRIMARY",
        "requested_cutoff": {"value": "200", "unit": "eV"}, "actual_cutoff": {"value": "200", "unit": "Ry"},
        "mesh_dimensions": [1, 2, 3], "atom_count": 1, "atom_identity_sha256": "a" * 64,
        "structure_sha256": "b" * 64, "pseudopotential_manifest_sha256": "c" * 64, "input_sha256": "d" * 64,
        "energy": {"value": "-1", "unit": "eV"}, "forces": {"values": [[0, 0, 0]], "unit": "eV/Ang"},
        "scf_converged": True, "magnetic_signature": "state", "baseline_observation_id": None,
    }
    with pytest.raises(ValueError, match="requested_cutoff must use Ry"):
        MeshObservation.from_mapping(raw)


def test_orphan_or_duplicate_eggbox_evidence_fails_closed() -> None:
    rule = MeshConvergenceRule.from_mapping(rule_data())
    records = converged_primary()
    orphan = observation(200, "-20", "0", kind="EGGBOX", baseline="missing")
    with pytest.raises(ValueError, match="unknown or mismatched"):
        MeshConvergenceEvaluator().evaluate(rule, records + [orphan])
    first = observation(200, "-20", "0", kind="EGGBOX", baseline="primary-200")
    second = observation(200, "-20", "0", kind="EGGBOX", baseline="primary-200")
    object.__setattr__(second, "observation_id", "eggbox-200-copy")
    with pytest.raises(ValueError, match="one eggbox"):
        MeshConvergenceEvaluator().evaluate(rule, records + [first, second])


def test_report_is_deterministic() -> None:
    evaluator = MeshConvergenceEvaluator()
    rule = MeshConvergenceRule.from_mapping(rule_data())
    assert evaluator.evaluate(rule, converged_primary()).as_dict() == evaluator.evaluate(rule, list(reversed(converged_primary()))).as_dict()
