"""New declaration/binding rules; no campaign loader or execution is enabled."""

import copy
from types import SimpleNamespace

import pytest

from qraft.execution import controller_campaign as module
from qraft.execution.controller_campaign import controller_task_declarations, validate_controller_bindings


@pytest.fixture
def campaign(monkeypatch):
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix"))
    return {"schema_version": "2.1", "tasks": [{
        "task_id": "hf1", "kind": "controller", "capability_id": "consumer.controller.hf1",
        "mpi_processes": 1, "cpus_per_process": 1, "nodes": 0,
        "reservation": {"nodes": 1, "inner_launcher": "openmpi", "inner_processes_per_node": 4,
                        "inner_cpus_per_process": 1, "max_concurrent_inner_launches": 1},
    }]}


def test_declaration_does_not_mutate_native_campaign(campaign):
    original = copy.deepcopy(campaign)
    declarations = controller_task_declarations(campaign)
    assert campaign == original
    assert len(declarations) == 1
    assert declarations[0].reservation.min_cpus == 4
    campaign["tasks"][0]["reservation"]["nodes"] = 2
    assert declarations[0].reservation.nodes == 1


@pytest.mark.parametrize("version", ["1.0", "2.0", 2.1, None])
def test_controller_requires_exact_campaign_21(campaign, version):
    campaign["schema_version"] = version
    with pytest.raises(ValueError, match="schema 2.1"):
        controller_task_declarations(campaign)


def test_legacy_campaign_is_not_promoted_without_a_controller(campaign):
    campaign["tasks"][0]["kind"] = "gate"
    with pytest.raises(ValueError, match="schema 2.1"):
        controller_task_declarations(campaign)
    campaign["schema_version"] = "2.0"
    assert controller_task_declarations(campaign) == ()


@pytest.mark.parametrize("field", ["command", "require_scf_converged", "executable", "siesta_executable", "executable_arguments"])
def test_even_empty_overrides_are_forbidden(campaign, field):
    campaign["tasks"][0][field] = None
    with pytest.raises(ValueError, match="forbidden"):
        controller_task_declarations(campaign)


@pytest.mark.parametrize("field,value", [
    ("mpi_processes", True), ("mpi_processes", 4), ("cpus_per_process", "1"),
    ("cpus_per_process", 2), ("nodes", False), ("nodes", 1),
])
def test_outer_process_shape_never_substitutes_inner_allocation(campaign, field, value):
    campaign["tasks"][0][field] = value
    with pytest.raises(ValueError, match="outer placement"):
        controller_task_declarations(campaign)


@pytest.mark.parametrize("field", ["capability_id", "reservation", "mpi_processes", "cpus_per_process", "nodes"])
def test_required_controller_fields_are_not_defaulted(campaign, field):
    del campaign["tasks"][0][field]
    with pytest.raises(ValueError):
        controller_task_declarations(campaign)


def test_windows_rejects_native_controller_declaration(campaign, monkeypatch):
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    with pytest.raises(ValueError, match="CONTROLLER_REQUIRES_POSIX"):
        controller_task_declarations(campaign)


@pytest.mark.parametrize("bindings", [None, {}, {"hf1": "consumer.wrong"}])
def test_controller_binding_is_mandatory(campaign, bindings):
    declarations = controller_task_declarations(campaign)
    with pytest.raises(ValueError, match="mandatory"):
        validate_controller_bindings(declarations, bindings, {"hf1": "consumer.controller.hf1"})


def test_binding_and_declaration_do_not_replace_verified_lock_identity(campaign):
    declarations = controller_task_declarations(campaign)
    bindings = {"hf1": "consumer.controller.hf1"}
    with pytest.raises(ValueError, match="verified workflow lock"):
        validate_controller_bindings(declarations, bindings, {"hf1": "consumer.wrong"})
    validate_controller_bindings(declarations, bindings, bindings)


def test_duplicate_task_ids_cannot_overwrite_reservation_map(campaign):
    campaign["tasks"].append(dict(campaign["tasks"][0], kind="gate"))
    with pytest.raises(ValueError, match="duplicate"):
        controller_task_declarations(campaign)
