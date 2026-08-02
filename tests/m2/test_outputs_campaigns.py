import json
from pathlib import Path

import pytest

from siestaflow.engines.siesta.adapter import SyntheticSiestaLauncher
from siestaflow.engines.siesta.output_parser import SiestaOutputParser
from siestaflow.project_packages import ProjectPackageLoader
from siestaflow.project_packages import load_structured
from siestaflow.scientific_convergence import MeshConvergenceRule, mesh_adaptive_dag
from siestaflow.siesta_campaigns import SiestaCampaignFactory, simulate_definition


def _definition(reference_package: Path, campaign: str):
    package = ProjectPackageLoader().load(reference_package)
    return SiestaCampaignFactory().from_package(package, campaign)


@pytest.mark.parametrize("name", [
    "normal_completion.out", "scf_not_converged.out", "input_error.out",
    "missing_pseudopotential.out", "truncated_output.out", "unknown_warning.out",
    "environment_error.out", "timeout.out", "spin_polarized_completion.out",
])
def test_all_synthetic_output_fixtures(name: str, synthetic_fixtures: Path):
    expected = json.loads((synthetic_fixtures / f"{name}.expected.json").read_text(encoding="utf-8"))
    parsed = SiestaOutputParser().parse((synthetic_fixtures / name).read_text(encoding="utf-8").splitlines(keepends=True), synthetic=True)
    gate = SiestaOutputParser().gate(parsed)
    assert parsed.classification.value == expected["expected_classification"]
    assert gate.status.value == expected["expected_gate"]
    assert parsed.synthetic is True
    assert parsed.provisional_status == "PROVISIONAL_UNTIL_REAL_OUTPUT_IMPORTED"
    for field, value in expected["expected_fields"].items():
        assert getattr(parsed, field) == value


def test_energy_does_not_imply_success(synthetic_fixtures: Path):
    parsed = SiestaOutputParser().parse((synthetic_fixtures / "truncated_output.out").read_text().splitlines(True), synthetic=True)
    assert parsed.energies
    assert parsed.classification.value == "TRUNCATED_OUTPUT"


def test_sanity_definition_and_single_task_simulation(reference_package: Path, tmp_path: Path):
    definition, variants = _definition(reference_package, "m1_sanity")
    assert definition.status == "EXECUTION_READY_PENDING_PREFLIGHT"
    assert variants == ()
    state, launcher, slurm = simulate_definition(definition, tmp_path)
    assert state.final_decision.value == "PASS"
    assert len(launcher.launches) == 1
    assert slurm.submissions == 1
    assert definition.metadata["stop_after_task"] is True


def test_mesh_real_gate_and_five_task_one_allocation_resume(reference_package: Path, tmp_path: Path):
    definition, variants = _definition(reference_package, "m1_mesh_convergence")
    assert definition.metadata["preview"] == "MESH_CAMPAIGN_PREVIEW_ONLY"
    assert len(definition.metadata["missing_dependencies"]) == 3
    assert len(variants) == 5
    state, launcher, slurm = simulate_definition(definition, tmp_path)
    assert state.final_decision.value == "PASS"
    assert slurm.submissions == 1
    assert len({allocation for allocation, _, _ in launcher.launches}) == 1
    assert len(launcher.launches) == 5
    attempts = list((tmp_path / "campaigns" / definition.manifest.campaign_id / "tasks").glob("*/attempt_001"))
    assert len(attempts) == 5
    revisions_before = state.revision
    resumed, second_launcher, second_slurm = simulate_definition(definition, tmp_path)
    assert resumed.revision >= revisions_before
    assert second_launcher.launches == []
    assert second_slurm.submissions == 0
    assert not list((tmp_path / "campaigns" / definition.manifest.campaign_id / "tasks").glob("*/attempt_002"))


def test_mesh_campaign_references_a_valid_human_review_rule(reference_package: Path):
    package = ProjectPackageLoader().load(reference_package)
    campaign = package.campaign("m1_mesh_convergence")
    rule_path = reference_package / str(campaign.metadata["convergence_rule"])
    rule = MeshConvergenceRule.from_mapping(load_structured(rule_path))
    assert tuple(f"{value} Ry" for value in map(str, rule.initial_cutoffs_ry)) == campaign.values
    assert mesh_adaptive_dag(rule)["execution_authorized"] is False


@pytest.mark.parametrize("fixture_name,expected_tasks", [("unknown_warning.out", 1), ("input_error.out", 1), ("truncated_output.out", 1)])
def test_review_or_failure_stops_persistent_worker(reference_package: Path, synthetic_fixtures: Path, tmp_path: Path, fixture_name: str, expected_tasks: int):
    definition, _ = _definition(reference_package, "m1_mesh_convergence")
    first = definition.manifest.tasks[0].task_id
    fixture = (synthetic_fixtures / fixture_name).read_text(encoding="utf-8")
    state, launcher, _ = simulate_definition(definition, tmp_path, fixtures={first: fixture})
    assert len(launcher.launches) == expected_tasks
    assert state.final_decision.value in {"REVIEW", "FAIL"}


def test_insufficient_time_stops_before_launch(reference_package: Path, tmp_path: Path):
    definition, _ = _definition(reference_package, "m1_mesh_convergence")
    state, launcher, slurm = simulate_definition(definition, tmp_path, allocation_seconds=1.0)
    assert launcher.launches == []
    assert state.final_decision.value == "BLOCKED"
    assert slurm.submissions == 1
