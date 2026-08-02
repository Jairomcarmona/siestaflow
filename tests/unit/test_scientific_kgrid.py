from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from siestaflow.scientific_kgrid import (
    KGridConvergenceEvaluator,
    KGridConvergenceRule,
    KGridObservation,
    kgrid_adaptive_dag,
)


HASHES = {name: character * 64 for name, character in zip(("atoms", "structure", "pseudo", "invariant"), "abcd")}


def grid(dimensions: tuple[int, int, int]) -> dict:
    return {"dimensions": list(dimensions), "shifts": ["0.0", "0.0", "0.0"]}


def rule_data() -> dict:
    return {
        "schema_version": "1.0", "rule_id": "TEST_KGRID_V1", "parameter": "kgrid.MonkhorstPack",
        "initial_values": [grid((2, 2, 1)), grid((3, 3, 1)), grid((4, 4, 1))],
        "extension_values": [grid((5, 5, 1))],
        "energy_tolerance": {"value": "1", "unit": "meV/atom"},
        "force_tolerance": {"value": "0.01", "unit": "eV/Ang"}, "consecutive_levels": 2,
        "require_magnetic_stability": True, "selection": "LOWEST_PASSING", "final_authority": "HUMAN_REVIEW",
    }


def observation(dimensions: tuple[int, int, int], energy: str, force: str, *, scf: bool = True, magnetic: str = "FM") -> KGridObservation:
    spec = grid(dimensions)
    return KGridObservation.from_mapping({
        "schema_version": "1.0", "observation_id": f"k{'x'.join(map(str, dimensions))}",
        "requested_grid": spec, "used_grid": spec, "atom_count": 2,
        "atom_identity_sha256": HASHES["atoms"], "structure_sha256": HASHES["structure"],
        "pseudopotential_manifest_sha256": HASHES["pseudo"], "invariant_input_sha256": HASHES["invariant"],
        "energy": {"value": energy, "unit": "eV"},
        "forces": {"values": [[force, "0", "0"], ["0", force, "0"]], "unit": "eV/Ang"},
        "scf_converged": scf, "magnetic_signature": magnetic,
    })


def converged() -> list[KGridObservation]:
    return [
        observation((2, 2, 1), "-19.990", "0.030"),
        observation((3, 3, 1), "-19.999", "0.005"),
        observation((4, 4, 1), "-20.000", "0.000"),
    ]


def test_rule_requires_refining_fixed_shift_grid_series() -> None:
    rule = KGridConvergenceRule.from_mapping(rule_data())
    assert rule.initial_grids[0].dimensions == (2, 2, 1)
    dag = kgrid_adaptive_dag(rule)
    assert dag["initial_tasks"][-1]["depends_on"] == [
        "kgrid_primary_2x2x1", "kgrid_primary_3x3x1", "kgrid_primary_4x4x1",
    ]
    assert dag["execution_authorized"] is False
    value = rule_data()
    value["initial_values"][1]["shifts"] = ["0.5", "0", "0"]
    with pytest.raises(ValueError, match="strictly refine"):
        KGridConvergenceRule.from_mapping(value)


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda value: value["energy_tolerance"].update(unit="eV/cell"), "meV/atom"),
        (lambda value: value.update(selection="MINIMUM_ENERGY"), "LOWEST_PASSING"),
        (lambda value: value["initial_values"].__setitem__(1, grid((2, 2, 1))), "strictly refine"),
    ],
)
def test_rule_fails_closed_on_ambiguous_or_unsafe_policy(mutation, message: str) -> None:
    value = rule_data()
    mutation(value)
    with pytest.raises(ValueError, match=message):
        KGridConvergenceRule.from_mapping(value)


def test_missing_primary_series_requests_only_declared_grids() -> None:
    report = KGridConvergenceEvaluator().evaluate(KGridConvergenceRule.from_mapping(rule_data()), [])
    assert report.status == "NEEDS_PRIMARY_SERIES"
    assert [item["grid"]["dimensions"] for item in report.next_actions] == [[2, 2, 1], [3, 3, 1], [4, 4, 1]]


def test_lowest_consecutive_passing_grid_requires_human_review() -> None:
    report = KGridConvergenceEvaluator().evaluate(KGridConvergenceRule.from_mapping(rule_data()), converged())
    assert report.status == "READY_FOR_HUMAN_REVIEW"
    assert report.selected_grid and report.selected_grid.dimensions == (3, 3, 1)
    assert report.final_authority == "HUMAN_REVIEW"


def test_energy_and_force_comparisons_are_normalized_and_vectorial() -> None:
    report = KGridConvergenceEvaluator().evaluate(KGridConvergenceRule.from_mapping(rule_data()), converged())
    level = next(item for item in report.levels if item["grid"]["dimensions"] == [3, 3, 1])
    assert Decimal(level["energy_delta_mev_per_atom"]) == Decimal("0.5")
    assert Decimal(level["force_vector_delta_ev_per_ang"]) == Decimal("0.005")


@pytest.mark.parametrize("field", ["scf", "magnetic"])
def test_scf_or_magnetic_change_blocks_candidate(field: str) -> None:
    records = converged()
    records[1] = observation((3, 3, 1), "-19.999", "0.005", scf=field != "scf", magnetic="AFM" if field == "magnetic" else "FM")
    report = KGridConvergenceEvaluator().evaluate(KGridConvergenceRule.from_mapping(rule_data()), records)
    assert report.status == "NEEDS_EXTENSION_SERIES"


def test_nonconverged_series_requests_declared_extension() -> None:
    records = [
        observation((2, 2, 1), "-19", "0.3"), observation((3, 3, 1), "-19.4", "0.2"),
        observation((4, 4, 1), "-20", "0"),
    ]
    report = KGridConvergenceEvaluator().evaluate(KGridConvergenceRule.from_mapping(rule_data()), records)
    assert report.status == "NEEDS_EXTENSION_SERIES"
    assert report.next_actions[0]["grid"]["dimensions"] == [5, 5, 1]


def test_tampered_identity_or_used_grid_fails_closed() -> None:
    records = converged()
    altered = deepcopy(records)
    object.__setattr__(altered[1], "invariant_input_sha256", "e" * 64)
    with pytest.raises(ValueError, match="scientific identity"):
        KGridConvergenceEvaluator().evaluate(KGridConvergenceRule.from_mapping(rule_data()), altered)
    raw = {
        "schema_version": "1.0", "observation_id": "bad", "requested_grid": grid((2, 2, 1)),
        "used_grid": grid((3, 3, 1)), "atom_count": 1, "atom_identity_sha256": "a" * 64,
        "structure_sha256": "b" * 64, "pseudopotential_manifest_sha256": "c" * 64,
        "invariant_input_sha256": "d" * 64, "energy": {"value": "-1", "unit": "eV"},
        "forces": {"values": [["0", "0", "0"]], "unit": "eV/Ang"}, "scf_converged": True,
        "magnetic_signature": "FM",
    }
    item = KGridObservation.from_mapping(raw)
    with pytest.raises(ValueError, match="differs from its used grid"):
        KGridConvergenceEvaluator().evaluate(KGridConvergenceRule.from_mapping(rule_data()), [item])
    with pytest.raises(ValueError, match="dimensions and shifts must be lists"):
        KGridObservation.from_mapping({**raw, "requested_grid": {"dimensions": "221", "shifts": ["0", "0", "0"]}})


def test_result_is_deterministic() -> None:
    rule = KGridConvergenceRule.from_mapping(rule_data())
    assert KGridConvergenceEvaluator().evaluate(rule, converged()).as_dict() == KGridConvergenceEvaluator().evaluate(rule, list(reversed(converged()))).as_dict()
