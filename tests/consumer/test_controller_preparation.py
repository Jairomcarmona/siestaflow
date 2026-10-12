"""Public task adapters emit 2.1 only for a validated controller declaration."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qraft.api import RunPreparer, RunPreparationRequest, WorkflowCompiler, write_workflow_lock
from qraft.execution import controller_campaign


def prepare_controller(tmp_path, monkeypatch, change=None):
    monkeypatch.setattr(controller_campaign, "os", SimpleNamespace(name="posix"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "plan.json").write_bytes(b'{"purpose":"synthetic-only"}\n')
    definition = source / "workflow.json"
    definition.write_text(json.dumps({
        "schema_version": "1.0", "workflow_id": "consumer-controller", "project_id": "fixture",
        "tasks": [{"task_id": "hf1", "kind": "calculation", "capability": "consumer.controller.hf1",
                   "inputs": [{"name": "plan", "source": "plan.json", "destination": "plan/campaign.json",
                               "media_type": "application/json"}], "outputs": [],
                   "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1,
                                 "cpus_per_process": 1, "walltime_seconds": 30}}],
    }), encoding="utf-8")
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid, compilation.diagnostics
    lock = source / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    profile = source / "profile.json"
    profile.write_text(json.dumps({
        "schema_version": "1.0", "profile_id": "fixture", "target": "slurm",
        "slurm": {"partition": "fixture", "account": None, "qos": None},
        "allocation": {"nodes": 1, "total_cpus": 8, "cpus_per_task": 1,
                       "memory": "1G", "walltime": "00:05:00", "max_parallel_steps": 1,
                       "shutdown_margin_seconds": 10, "termination_grace_seconds": 1},
        "runtime": {"module_commands": [], "siesta_executable": "never-executed-siesta",
                    "executable_arguments": [], "exclusive": True, "environment": {},
                    "launcher": {"kind": "openmpi", "command": ["/never-executed/mpirun"],
                                 "arguments": [], "bootstrap": "", "processes_per_node": 8}},
        "task_policy": {"max_attempts": 3, "require_scf_converged": True},
    }), encoding="utf-8")

    def adapter(task, *, artifacts, resolved_sources, protected, **context):
        binding = task.inputs[0]
        artifact = artifacts[binding.external_artifact_id]
        relative = "protected/hf1/plan/campaign.json"
        protected[relative] = resolved_sources[artifact.artifact_id]
        record = {
            "task_id": task.task_id, "kind": "controller", "capability_id": task.capability_id,
            "input": relative, "input_hashes": {relative: artifact.sha256},
            "input_destinations": {relative: binding.destination},
            "required_artifacts": [], "optional_artifacts": [], "depends_on": [], "transfers": [],
            "mpi_processes": 1, "cpus_per_process": 1, "nodes": 0,
            "estimated_runtime_seconds": 30, "max_attempts": 3,
            "reservation": {"nodes": 1, "inner_launcher": "openmpi", "inner_processes_per_node": 4,
                            "inner_cpus_per_process": 1, "max_concurrent_inner_launches": 1},
        }
        if change:
            change(record)
        return record

    return RunPreparer(task_adapters={"consumer.controller.hf1": adapter}).prepare(RunPreparationRequest(
        workflow_lock=lock, source_root=source, execution_profile=profile,
        output_root=tmp_path / "output", run_id="synthetic-controller",
    ))


def test_public_preparer_binds_reservation_to_campaign_and_run_lock(tmp_path, monkeypatch):
    result = prepare_controller(tmp_path, monkeypatch)
    root = Path(result.package_path)
    campaign = json.loads((root / "campaign.yaml").read_bytes())
    lock = json.loads((root / "run.lock.json").read_bytes())
    assert campaign["schema_version"] == "2.1"
    assert campaign["tasks"][0]["reservation"]["inner_processes_per_node"] == 4
    assert lock["payload"]["controller_campaign_sha256"] == result.controller_campaign_sha256
    assert result.execution_authorized is False and result.submission_performed is False
    assert (root / "protected/hf1/plan/campaign.json").read_bytes() == b'{"purpose":"synthetic-only"}\n'


@pytest.mark.parametrize("change", [
    lambda task: task.update(capability_id="consumer.different"),
    lambda task: task.update(command=[]),
    lambda task: task.update(require_scf_converged=False),
    lambda task: task["reservation"].update(nodes=2),
    lambda task: task["reservation"].update(inner_cpus_per_process=2),
    lambda task: task.pop("reservation"),
])
def test_public_preparer_rejects_invalid_adapter_before_package_write(tmp_path, monkeypatch, change):
    with pytest.raises(ValueError):
        prepare_controller(tmp_path, monkeypatch, change)
    assert not (tmp_path / "output").exists()
