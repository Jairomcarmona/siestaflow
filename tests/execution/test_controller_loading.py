"""Conditional 2.1 loading and translation; no child processes or science."""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from qraft.execution import controller_campaign
from qraft.execution.allocation_controller_compat import load_controller_config
from qraft.execution.legacy_translation import translate_controller_config
from qraft.execution.resource_coordinator import RuntimeAllocation


def write_campaign(root, changes=None):
    source = root / "plan.json"
    source.write_bytes(b'{"scientific_policy":"synthetic-only"}\n')
    task = {
        "task_id": "hf1", "kind": "controller", "capability_id": "consumer.controller.hf1",
        "input": "plan.json", "input_hashes": {"plan.json": hashlib.sha256(source.read_bytes()).hexdigest()},
        "input_destinations": {"plan.json": "plan/campaign.json"},
        "required_artifacts": [], "optional_artifacts": [],
        "mpi_processes": 1, "cpus_per_process": 1, "nodes": 0,
        "estimated_runtime_seconds": 30, "max_attempts": 3,
        "reservation": {"nodes": 1, "inner_launcher": "openmpi", "inner_processes_per_node": 4,
                        "inner_cpus_per_process": 1, "max_concurrent_inner_launches": 1},
    }
    data = {
        "schema_version": "2.1", "campaign_id": "synthetic-controller", "system_id": "fixture",
        "slurm": {"partition": "fixture", "account": None, "qos": None},
        "resources": {"nodes": 1, "total_cpus": 8, "ntasks": 8, "cpus_per_task": 1,
                      "memory": "1G", "walltime": "00:05:00", "max_parallel_steps": 1,
                      "shutdown_margin_seconds": 10, "termination_grace_seconds": 1},
        "runtime": {"siesta_executable": "/never-executed/siesta", "environment": {},
                    "launcher": {"kind": "openmpi", "command": ["/never-executed/mpirun"],
                                 "arguments": [], "processes_per_node": 8}},
        "tasks": [task],
    }
    if changes:
        changes(data, task)
    path = root / "campaign.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


@pytest.fixture
def posix_declaration(monkeypatch):
    # Only declaration tests use this seam; no containment/launch is claimed.
    monkeypatch.setattr(controller_campaign, "os", SimpleNamespace(name="posix"))


def test_native_loader_translates_controller_without_relabeling_or_outer_mpi(tmp_path, posix_declaration):
    path, data = write_campaign(tmp_path)
    original = path.read_bytes()
    config = load_controller_config(path)
    plan = translate_controller_config(config, root=tmp_path)
    task = plan.workflow.tasks[0]
    execution = plan.execution_specs["hf1"]
    reservation = plan.controller_reservations["hf1"]
    assert task.capability_id == data["tasks"][0]["capability_id"]
    assert task.settings["legacy_task_kind"] == "controller"
    assert "command" not in task.settings and "require_scf_converged" not in task.settings
    assert (execution.launcher, execution.mpi_ranks, execution.cpus_per_rank) == ("controller", 1, 1)
    assert execution.executable == task.capability_id  # Declared identity, never PATH resolution.
    assert execution.launcher_command == ("/never-executed/mpirun",)
    assert reservation.min_cpus == 4
    assert reservation.resource_request("hf1", RuntimeAllocation(8, 1, hosts=("localhost",))).cpus == 8
    assert path.read_bytes() == original


@pytest.mark.parametrize("field", ["command", "require_scf_converged", "executable", "siesta_executable", "executable_arguments"])
def test_native_loader_vetoes_even_empty_controller_overrides(tmp_path, posix_declaration, field):
    path, _ = write_campaign(tmp_path, lambda data, task: task.update({field: None}))
    with pytest.raises(ValueError, match="forbidden"):
        load_controller_config(path)


@pytest.mark.parametrize("field", ["reservation", "capability_id", "mpi_processes", "cpus_per_process", "nodes"])
def test_native_loader_does_not_default_required_controller_fields(tmp_path, posix_declaration, field):
    path, _ = write_campaign(tmp_path, lambda data, task: task.pop(field))
    with pytest.raises(ValueError):
        load_controller_config(path)


@pytest.mark.parametrize("version", ["1.0", "2.0", 2.1, None])
def test_native_loader_never_accepts_controller_as_legacy(tmp_path, posix_declaration, version):
    path, _ = write_campaign(tmp_path, lambda data, task: data.update(schema_version=version))
    with pytest.raises(ValueError):
        load_controller_config(path)


@pytest.mark.parametrize("kind", ["Controller", " controller", "controller "])
def test_normalization_cannot_bypass_new_declaration_validation(tmp_path, posix_declaration, kind):
    path, _ = write_campaign(tmp_path, lambda data, task: task.update(kind=kind))
    with pytest.raises(ValueError):
        load_controller_config(path)


def test_changed_reservation_changes_workflow_definition_not_scientific_identity(tmp_path, posix_declaration):
    path, data = write_campaign(tmp_path)
    one = translate_controller_config(load_controller_config(path), root=tmp_path)
    data["tasks"][0]["reservation"]["inner_processes_per_node"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")
    two = translate_controller_config(load_controller_config(path), root=tmp_path)
    assert one.workflow.definition_sha256 != two.workflow.definition_sha256
    assert one.scientific_identities["hf1"].fingerprint == two.scientific_identities["hf1"].fingerprint
    assert one.execution_specs["hf1"].fingerprint == two.execution_specs["hf1"].fingerprint


def test_21_is_not_emitted_for_gate_or_siesta(tmp_path, posix_declaration):
    path, data = write_campaign(tmp_path)
    task = data["tasks"][0]
    task.update(kind="gate", command=["/never-executed/gate"])
    del task["reservation"]
    del task["capability_id"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly when"):
        load_controller_config(path)
    data["schema_version"] = "2.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    plan = translate_controller_config(load_controller_config(path), root=tmp_path)
    assert plan.controller_reservations == {}
    assert plan.workflow.tasks[0].capability_id == "qraft.runtime.command"


@pytest.mark.skipif(os.name != "nt", reason="native Windows rejection")
def test_windows_rejects_before_translating_or_creating_runtime(tmp_path):
    path, _ = write_campaign(tmp_path)
    with pytest.raises(ValueError, match="CONTROLLER_REQUIRES_POSIX"):
        load_controller_config(path)
