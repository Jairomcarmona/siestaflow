from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from siestaflow.execution.allocation_controller import AllocationController, ExecutionStatus, load_controller_config
from siestaflow.run_inspection import RunInspector
from siestaflow.run_preparation import RunPreparer, RunPreparationRequest
from siestaflow.workflows import WorkflowCompiler, write_workflow_lock


REPO = Path(__file__).resolve().parents[2]
RESOURCES = {
    "nodes": 1,
    "mpi_processes": 1,
    "processes_per_node": 1,
    "cpus_per_process": 1,
    "walltime_seconds": 30,
}


def adaptive_definition(root: Path) -> Path:
    tasks: list[dict] = []
    for variant_id, value in (("alpha", 2.0), ("beta", 1.0), ("gamma", 1.0)):
        tasks.append({
            "task_id": f"sweep_{variant_id}",
            "kind": "sweep",
            "capability": "siestaflow.gate.deterministic-metric",
            "inputs": [],
            "outputs": [{
                "name": "metric", "path": "metric.json",
                "artifact_type": "siestaflow.adaptive-metric",
                "media_type": "application/json",
            }],
            "resources": RESOURCES,
            "settings": {
                "variant_id": variant_id,
                "metric_name": "score",
                "metric_value": value,
            },
        })
    tasks.append({
        "task_id": "select_best",
        "kind": "selection",
        "capability": "siestaflow.gate.minimum-selector",
        "inputs": [{
            "name": f"metric_{variant}",
            "from": {"task": f"sweep_{variant}", "output": "metric"},
            "destination": f"metrics/{variant}.json",
            "media_type": "application/json",
        } for variant in ("alpha", "beta", "gamma")],
        "outputs": [{
            "name": "decision", "path": "selection.json",
            "artifact_type": "siestaflow.adaptive-decision",
            "media_type": "application/json",
        }],
        "resources": RESOURCES,
        "settings": {"metric_name": "score"},
    })
    tasks.append({
        "task_id": "consume_best",
        "kind": "transformation",
        "capability": "siestaflow.gate.selection-consumer",
        "inputs": [{
            "name": "decision",
            "from": {"task": "select_best", "output": "decision"},
            "destination": "selection.json",
            "media_type": "application/json",
        }],
        "outputs": [{
            "name": "result", "path": "final.json",
            "artifact_type": "siestaflow.adaptive-result",
            "media_type": "application/json",
        }],
        "resources": RESOURCES,
        "settings": {},
    })
    path = root / "adaptive-workflow.json"
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "workflow_id": "adaptive-fixture",
        "project_id": "phase4-local",
        "description": "Static three-variant adaptive gate fixture",
        "metadata": {"scientific_policy": "not-a-scientific-calculation"},
        "tasks": tasks,
    }, indent=2) + "\n", encoding="utf-8")
    return path


def profile(root: Path) -> Path:
    path = root / "profile.json"
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "profile_id": "local-adaptive-gate",
        "target": "slurm",
        "slurm": {"partition": "local", "account": "test", "qos": "normal"},
        "allocation": {
            "nodes": 1, "total_cpus": 3, "memory": "1G", "walltime": "00:05:00",
            "max_parallel_steps": 3, "shutdown_margin_seconds": 30,
            "termination_grace_seconds": 10,
        },
        "runtime": {
            "module_commands": [], "siesta_executable": "siesta",
            "executable_arguments": [],
            "launcher": {
                "kind": "srun", "command": ["srun"], "arguments": [],
                "bootstrap": "ssh", "processes_per_node": 1,
            },
            "exclusive": True, "environment": {},
        },
        "task_policy": {"max_attempts": 1, "require_scf_converged": True},
    }, indent=2) + "\n", encoding="utf-8")
    return path


def prepared(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    compilation = WorkflowCompiler().compile(adaptive_definition(source))
    assert compilation.valid
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    result = RunPreparer(REPO).prepare(RunPreparationRequest(
        workflow_lock=lock,
        source_root=source,
        execution_profile=profile(tmp_path),
        output_root=tmp_path / "packages",
        run_id="phase4-adaptive-local-001",
    ))
    return compilation, result, Path(result.package_path)


def environment(root: Path) -> dict[str, str]:
    return {
        "SLURM_JOB_ID": "phase4-local-job",
        "SLURM_SUBMIT_DIR": str(root),
        "SLURM_JOB_END_TIME": str(time.time() + 300),
        "SLURM_NNODES": "1",
        "SLURM_NTASKS": "3",
        "SLURM_CPUS_PER_TASK": "1",
    }


def test_adaptive_workflow_compiles_deterministically_with_explicit_fan_in(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    definition = adaptive_definition(source)
    first = WorkflowCompiler().compile(definition)
    second = WorkflowCompiler().compile(definition)
    assert first.valid and first.lock_dict() == second.lock_dict()
    compiled = first.compiled
    assert compiled is not None
    assert [task.task_id for task in compiled.tasks] == [
        "sweep_alpha", "sweep_beta", "sweep_gamma", "select_best", "consume_best",
    ]
    assert compiled.tasks[3].dependencies == ("sweep_alpha", "sweep_beta", "sweep_gamma")
    assert compiled.tasks[4].dependencies == ("select_best",)


def test_run_prepare_builds_hash_bound_gate_campaign_and_verified_package(tmp_path: Path) -> None:
    _, result, package = prepared(tmp_path)
    assert result.task_count == 5 and Path(result.zip_path).is_file()
    config = load_controller_config(package / "campaign.yaml")
    assert [task.task_kind for task in config.tasks] == ["gate"] * 5
    selector = next(task for task in config.tasks if task.task_id == "select_best")
    assert len(selector.transfers) == 3
    assert selector.depends_on == ("sweep_alpha", "sweep_beta", "sweep_gamma")
    assert all("adaptive_gate.py" in task.input_path for task in config.tasks)
    assert "\\" not in (package / "campaign.yaml").read_text(encoding="utf-8")
    assert RunInspector().inspect(package).status == "PREPARED_RUN_VERIFIED"
    verified = subprocess.run([sys.executable, "verify_package.py"], cwd=package, capture_output=True, text=True)
    assert verified.returncode == 0, verified.stderr


def test_local_controller_executes_fan_out_selector_and_consumer(tmp_path: Path) -> None:
    _, _, package = prepared(tmp_path)
    controller = AllocationController.from_file(
        package / "campaign.yaml", environment=environment(package), poll_interval_seconds=0.01,
    )
    assert controller.run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    final = package / "work" / "consume_best" / "attempt-0001" / "final.json"
    assert json.loads(final.read_text())["selected_variant_id"] == "beta"
    decision = package / "work" / "select_best" / "attempt-0001" / "selection.json"
    assert json.loads(decision.read_text())["selection_reason"] == "minimum metric; ties resolved by variant_id"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["tasks"].__setitem__(3, {**data["tasks"][3], "inputs": data["tasks"][3]["inputs"][:1]}), "selector requires two or three"),
        (lambda data: data["tasks"][0].__setitem__("capability", "siestaflow.engine.siesta"), "unsupported sweep capability"),
        (lambda data: data["tasks"][4].__setitem__("settings", {"unexpected": True}), "invalid selection consumer"),
        (lambda data: data["tasks"][0]["settings"].__setitem__("metric_name", "invalid metric"), "metric_name is not a valid local identifier"),
        (lambda data: data["tasks"][3].__setitem__("settings", {"unexpected": True}), "invalid selector settings"),
        (lambda data: data["tasks"][4]["outputs"][0].__setitem__("name", "wrong"), "requires one required 'result' output"),
        (lambda data: data["tasks"][0]["settings"].__setitem__("metric_value", "not-numeric"), "metric_value must be finite numeric"),
    ],
)
def test_run_prepare_rejects_invalid_adaptive_contracts(tmp_path: Path, mutate, message: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    definition = adaptive_definition(source)
    data = json.loads(definition.read_text())
    mutate(data)
    definition.write_text(json.dumps(data), encoding="utf-8")
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    with pytest.raises(ValueError, match=message):
        RunPreparer(REPO).prepare(RunPreparationRequest(
            workflow_lock=lock, source_root=source, execution_profile=profile(tmp_path),
            output_root=tmp_path / "packages", run_id="invalid-adaptive",
        ))
