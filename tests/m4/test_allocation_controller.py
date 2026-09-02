from __future__ import annotations

import hashlib
import json
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from qraft.execution.allocation_controller import (
    AllocationController,
    ExecutionStatus,
    load_controller_config,
)
from qraft.execution.canonical_controller import CanonicalController
from qraft.execution.legacy_translation import translate_controller_config
from qraft.execution.hydra_launcher import HydraLauncher
from qraft.execution.adapters import launcher_registry
from qraft.execution.runtime_composition import compose_runtime
from qraft.core import ExecutionSpec
from qraft.execution.slurm_environment import ShutdownRequest, SignalHandlers, SlurmEnvironment
from qraft.execution.srun_launcher import SrunLauncher, StepLaunchSpec, StepOutcome


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_runtime(root: Path) -> tuple[Path, Path]:
    srun = root / "fake_srun.py"
    srun.write_text(
        "import subprocess,sys\n"
        "args=sys.argv[1:]\n"
        "while args and args[0].startswith('--'): args.pop(0)\n"
        "raise SystemExit(subprocess.run(args).returncode)\n",
        encoding="utf-8",
    )
    siesta = root / "fake_siesta.py"
    siesta.write_text(
        "import pathlib,sys,time\n"
        "text=sys.stdin.read()\n"
        "if 'SLEEP' in text: time.sleep(0.20)\n"
        "if 'FAIL' in text:\n"
        " print('SIESTA started'); print('controlled failure',file=sys.stderr); raise SystemExit(7)\n"
        "if 'TRUNCATED' in text:\n"
        " print('SIESTA started'); print('SCF iteration 1'); raise SystemExit(0)\n"
        "print('Version: 5.4.2')\n"
        "print('Reading input FDF')\n"
        "if 'RESTART_MUTATES' in text:\n"
        " assert pathlib.Path('required.DM').read_text() == 'dm'\n"
        " print('Attempting to read DM from file... Succeeded...')\n"
        " pathlib.Path('required.DM').write_text('updated-dm')\n"
        "print('SCF iteration 1')\n"
        "print('SCF converged')\n"
        "if 'ARTIFACT' in text: pathlib.Path('required.DM').write_text('dm')\n"
        "print('Job completed')\n",
        encoding="utf-8",
    )
    return srun, siesta


def make_package(tmp_path: Path, behaviors: list[str], *, total_cpus: int = 2, max_parallel: int = 2,
                 mpi_processes: int = 1, max_attempts: int = 2, required_artifact: bool = False) -> tuple[Path, dict]:
    root = tmp_path.resolve()
    (root / "input").mkdir()
    (root / "pseudopotentials").mkdir()
    pseudo = root / "pseudopotentials" / "C.psml"
    pseudo.write_text("pseudo", encoding="utf-8")
    srun, siesta = write_runtime(root)
    tasks = []
    for index, behavior in enumerate(behaviors, 1):
        source = root / "input" / f"task{index}.fdf"
        source.write_text(behavior + "\n", encoding="utf-8")
        tasks.append({
            "task_id": f"task-{index}", "input": f"input/task{index}.fdf",
            "input_hashes": {f"input/task{index}.fdf": sha(source), "pseudopotentials/C.psml": sha(pseudo)},
            "required_artifacts": ["required.DM"] if required_artifact else [],
            "mpi_processes": mpi_processes, "cpus_per_process": 1,
            "estimated_runtime_seconds": 1, "max_attempts": max_attempts,
            "require_scf_converged": True,
        })
    config = {
        "schema_version": "1.0", "campaign_id": "m4-test", "system_id": "C50",
        "slurm": {"partition": "test", "account": "account", "qos": "normal"},
        "resources": {
            "nodes": 1, "total_cpus": total_cpus, "memory": "1G", "walltime": "00:05:00",
            "max_parallel_steps": max_parallel, "shutdown_margin_seconds": 1,
            "termination_grace_seconds": 0.01,
        },
        "runtime": {
            "module_commands": [], "siesta_executable": sys.executable,
            "executable_arguments": [str(siesta)], "srun_command": [sys.executable, str(srun)],
            "srun_arguments": [], "exclusive": True, "environment": {},
        },
        "tasks": tasks,
    }
    campaign = root / "campaign.yaml"
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return campaign, config


def environment(root: Path, job: str, *, seconds: float = 300, total_cpus: int = 2) -> dict[str, str]:
    return {
        "SLURM_JOB_ID": job, "SLURM_SUBMIT_DIR": str(root),
        "SLURM_JOB_END_TIME": str(time.time() + seconds), "SLURM_NNODES": "1",
        "SLURM_NTASKS": str(total_cpus), "SLURM_CPUS_PER_TASK": "1",
    }


def state(root: Path) -> dict:
    return json.loads((root / "state" / "campaign_state.json").read_text(encoding="utf-8"))["payload"]


def controller(campaign: Path, job: str, **kwargs) -> AllocationController:
    config = json.loads(campaign.read_text(encoding="utf-8"))
    total = config["resources"]["total_cpus"]
    return AllocationController.from_file(
        campaign, environment=environment(campaign.parent, job, total_cpus=total),
        poll_interval_seconds=0.01, **kwargs,
    )


def test_one_successful_srun_step_is_fully_validated(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS"])
    result = controller(campaign, "1001").run(install_signal_handlers=False)
    assert result is ExecutionStatus.COMPLETED
    attempt = tmp_path / "work" / "task-1" / "attempt-0001"
    command = json.loads((attempt / "command.json").read_text())["argv"]
    assert "--exclusive" in command
    assert "--ntasks=1" in command
    assert state(tmp_path)["tasks"]["task-1"]["status"] == "COMPLETED"


@pytest.mark.parametrize("qos", ["normal", None])
def test_schema2_controller_config_accepts_explicit_or_null_qos(
    tmp_path: Path, qos: str | None,
) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"])
    config["schema_version"] = "2.0"
    config["runtime"]["launcher"] = {
        "kind": "srun", "command": [sys.executable], "arguments": [],
        "bootstrap": "ssh",
    }
    config["slurm"]["qos"] = qos
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    assert load_controller_config(campaign).campaign_id == "m4-test"


def test_schema2_controller_config_accepts_missing_qos(tmp_path: Path) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"])
    config["schema_version"] = "2.0"
    config["runtime"]["launcher"] = {
        "kind": "srun", "command": [sys.executable], "arguments": [],
        "bootstrap": "ssh",
    }
    config["slurm"].pop("qos")
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    assert load_controller_config(campaign).campaign_id == "m4-test"


@pytest.mark.parametrize("include_account, account", [(True, "account"), (True, None), (False, None)])
def test_schema2_controller_config_accepts_explicit_null_or_missing_account(
    tmp_path: Path, include_account: bool, account: str | None,
) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"])
    config["schema_version"] = "2.0"
    config["runtime"]["launcher"] = {
        "kind": "srun", "command": [sys.executable], "arguments": [],
        "bootstrap": "ssh",
    }
    if include_account:
        config["slurm"]["account"] = account
    else:
        config["slurm"].pop("account")
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    assert load_controller_config(campaign).campaign_id == "m4-test"


@pytest.mark.parametrize("account", ["", "MISSING_ACCOUNT", 7])
def test_schema2_controller_config_rejects_invalid_explicit_account(
    tmp_path: Path, account: object,
) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"])
    config["schema_version"] = "2.0"
    config["runtime"]["launcher"] = {
        "kind": "srun", "command": [sys.executable], "arguments": [],
        "bootstrap": "ssh",
    }
    config["slurm"]["account"] = account
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="account"):
        load_controller_config(campaign)


@pytest.mark.parametrize("qos", ["", "MISSING_QOS", 7])
def test_schema2_controller_config_rejects_invalid_explicit_qos(
    tmp_path: Path, qos: object,
) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"])
    config["schema_version"] = "2.0"
    config["runtime"]["launcher"] = {
        "kind": "srun", "command": [sys.executable], "arguments": [],
        "bootstrap": "ssh",
    }
    config["slurm"]["qos"] = qos
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="qos"):
        load_controller_config(campaign)


def test_sequential_steps_use_one_slot(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS", "SUCCESS", "SUCCESS"], max_parallel=1)
    assert controller(campaign, "1002").run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    events = [json.loads(line) for line in (tmp_path / "evidence" / "events.jsonl").read_text().splitlines()]
    states = [(item.get("task_id"), item.get("status")) for item in events if item["event"] == "TASK_STATE"]
    assert states.index(("task-1", "COMPLETED")) < states.index(("task-2", "RUNNING"))
    assert states.index(("task-2", "COMPLETED")) < states.index(("task-3", "RUNNING"))


def test_two_steps_run_together_but_cpu_pool_limits_next_wave(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SLEEP", "SLEEP", "SLEEP"], total_cpus=2, max_parallel=3)
    assert controller(campaign, "1003").run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    events = [json.loads(line) for line in (tmp_path / "evidence" / "events.jsonl").read_text().splitlines()]
    states = [(item.get("task_id"), item.get("status")) for item in events if item["event"] == "TASK_STATE"]
    first_completion = min(index for index, item in enumerate(states) if item[1] == "COMPLETED")
    assert states.index(("task-1", "RUNNING")) < first_completion
    assert states.index(("task-2", "RUNNING")) < first_completion
    assert states.index(("task-3", "RUNNING")) > first_completion


def test_failure_does_not_stop_independent_task(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["FAIL", "SUCCESS"], max_parallel=1)
    assert controller(campaign, "1004").run(install_signal_handlers=False) is ExecutionStatus.FAILED
    tasks = state(tmp_path)["tasks"]
    assert tasks["task-1"]["status"] == "FAILED"
    assert tasks["task-2"]["status"] == "COMPLETED"


def test_new_job_id_resumes_incomplete_campaign_without_fake_allocation(tmp_path: Path):
    campaign, config = make_package(tmp_path, ["SUCCESS"])
    first = AllocationController.from_file(
        campaign, environment=environment(tmp_path, "old-job", seconds=0.1, total_cpus=2),
        poll_interval_seconds=0.01,
    )
    assert first.run(install_signal_handlers=False) is ExecutionStatus.INTERRUPTED
    assert state(tmp_path)["tasks"]["task-1"]["attempts"] == 0
    second = controller(campaign, "new-job")
    assert second.run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    saved = state(tmp_path)
    assert [item["job_id"] for item in saved["allocation_history"]] == ["old-job", "new-job"]
    assert saved["tasks"]["task-1"]["attempts"] == 1


@pytest.mark.parametrize("reason", ["SIGUSR1", "SIGTERM"])
def test_shutdown_signals_stop_new_launches_and_close_active_step(tmp_path: Path, reason: str):
    campaign, config_data = make_package(tmp_path, ["SUCCESS", "SUCCESS"], max_parallel=1)
    shutdown = ShutdownRequest()
    launcher = BlockingLauncher(shutdown)
    current = controller(campaign, f"signal-{reason}", launcher=launcher, shutdown=shutdown)
    timer = threading.Timer(0.03, lambda: shutdown.request(reason))
    timer.start()
    try:
        assert current.run(install_signal_handlers=False) is ExecutionStatus.INTERRUPTED
    finally:
        timer.cancel()
    tasks = state(tmp_path)["tasks"]
    assert tasks["task-1"]["status"] == "INTERRUPTED"
    assert tasks["task-2"]["status"] == "INCOMPLETE"


def test_signal_handler_maps_available_signals_to_shutdown_request():
    shutdown = ShutdownRequest()
    handler = SignalHandlers(shutdown)
    number = getattr(signal, "SIGUSR1", signal.SIGTERM)
    handler._handle(number, None)
    assert shutdown.requested
    assert shutdown.reason == signal.Signals(number).name


def test_truncated_output_and_missing_required_artifact_are_incomplete(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["TRUNCATED", "SUCCESS"], required_artifact=True)
    result = controller(campaign, "1005").run(install_signal_handlers=False)
    assert result is ExecutionStatus.INCOMPLETE
    tasks = state(tmp_path)["tasks"]
    assert tasks["task-1"]["status"] == "INCOMPLETE"
    assert tasks["task-2"]["status"] == "INCOMPLETE"


def test_completed_result_is_rejected_and_repeated_after_manifest_tamper(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS"], max_attempts=2)
    assert controller(campaign, "1006").run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    manifest = tmp_path / "work" / "task-1" / "attempt-0001" / "result_manifest.json"
    manifest.write_text(manifest.read_text() + " ", encoding="utf-8")
    assert controller(campaign, "1007").run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    saved = state(tmp_path)
    assert saved["tasks"]["task-1"]["attempts"] == 2
    assert [item["job_id"] for item in saved["allocation_history"]] == ["1006", "1007"]


def test_protected_input_hash_mismatch_never_launches(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS"])
    (tmp_path / "input" / "task1.fdf").write_text("altered", encoding="utf-8")
    assert controller(campaign, "1008").run(install_signal_handlers=False) is ExecutionStatus.INCOMPLETE
    assert state(tmp_path)["tasks"]["task-1"]["attempts"] == 0
    assert not (tmp_path / "work" / "task-1" / "attempt-0001").exists()


def test_summary_explicitly_has_no_login_node_dependency(tmp_path: Path):
    campaign, _ = make_package(tmp_path, ["SUCCESS"])
    current = controller(campaign, "1009")
    assert current.run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    summary = json.loads(current.summary_path.read_text())
    assert summary["login_node_persistent_process_required"] is False


def test_dependency_artifact_is_hash_bound_and_transferred(tmp_path: Path):
    campaign, config = make_package(
        tmp_path, ["ARTIFACT", "SUCCESS"], max_parallel=2, required_artifact=True
    )
    config["tasks"][1]["depends_on"] = ["task-1"]
    config["tasks"][1]["transfers"] = [{
        "from_task": "task-1",
        "artifact": "required.DM",
        "destination": "parent.DM",
    }]
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    assert controller(campaign, "dag-1").run(install_signal_handlers=False) is ExecutionStatus.INCOMPLETE
    # The second task intentionally does not create its own required.DM, but its
    # transferred parent artifact and provenance must still exist and validate.
    attempt = tmp_path / "work" / "task-2" / "attempt-0001"
    assert (attempt / "parent.DM").read_text() == "dm"
    transfer = json.loads((attempt / "transfer_manifest.json").read_text())["transfers"][0]
    assert transfer["from_task"] == "task-1"
    assert transfer["destination"] == "parent.DM"
    assert state(tmp_path)["tasks"]["task-1"]["status"] == "COMPLETED"


def test_protected_inputs_are_staged_at_declared_exact_destinations(
    tmp_path: Path,
) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"])
    config["tasks"][0]["input_destinations"] = {
        "input/task1.fdf": "nested/input.fdf",
        "pseudopotentials/C.psml": "species/C.psml",
    }
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    result = controller(campaign, "exact-destinations").run(
        install_signal_handlers=False
    )

    assert result is ExecutionStatus.COMPLETED
    attempt = tmp_path / "work" / "task-1" / "attempt-0001"
    assert (attempt / "nested" / "input.fdf").read_text() == "SUCCESS\n"
    assert (attempt / "species" / "C.psml").read_text() == "pseudo"
    assert not (attempt / "task1.fdf").exists()


def test_mutable_restart_dm_keeps_immutable_input_evidence(tmp_path: Path):
    campaign, config = make_package(
        tmp_path,
        ["ARTIFACT", "RESTART_MUTATES"],
        max_parallel=1,
        required_artifact=True,
    )
    config["tasks"][1]["depends_on"] = ["task-1"]
    config["tasks"][1]["transfers"] = [{
        "from_task": "task-1",
        "artifact": "required.DM",
        "destination": "required.DM",
    }]
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    assert (
        controller(campaign, "mutable-dm").run(install_signal_handlers=False)
        is ExecutionStatus.COMPLETED
    )
    attempt = tmp_path / "work" / "task-2" / "attempt-0001"
    manifest = json.loads((attempt / "result_manifest.json").read_text())
    transfer = manifest["transferred_inputs"][0]
    evidence = attempt / transfer["evidence_path"]

    assert evidence.read_text() == "dm"
    assert sha(evidence) == transfer["sha256"]
    assert (attempt / "required.DM").read_text() == "updated-dm"
    assert manifest["artifacts"]["required.DM"] == sha(attempt / "required.DM")
    assert manifest["restart_evidence"]["dm_read_succeeded"] is True
    assert manifest["parser_classification"] == "COMPLETED"


def test_legacy_mutated_dm_attempt_is_recovered_without_recalculation(
    tmp_path: Path,
):
    campaign, config = make_package(
        tmp_path,
        ["ARTIFACT", "RESTART_MUTATES"],
        max_parallel=1,
        required_artifact=True,
    )
    config["tasks"][1]["depends_on"] = ["task-1"]
    config["tasks"][1]["transfers"] = [{
        "from_task": "task-1",
        "artifact": "required.DM",
        "destination": "required.DM",
    }]
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    assert (
        controller(campaign, "legacy-first").run(install_signal_handlers=False)
        is ExecutionStatus.COMPLETED
    )

    attempt = tmp_path / "work" / "task-2" / "attempt-0001"
    manifest_path = attempt / "result_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    transfer = manifest["transferred_inputs"][0]
    for field in (
        "evidence_path",
        "evidence_sha256",
        "destination_sha256_before_execution",
        "destination_mutable_after_launch",
    ):
        transfer.pop(field)
    manifest["parser_classification"] = "UNKNOWN_WARNING"
    manifest.pop("restart_evidence")
    manifest.pop("parser_warnings")
    manifest.pop("parser_benign_warnings")
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    state_path = tmp_path / "state" / "campaign_state.json"
    wrapper = json.loads(state_path.read_text())
    payload = wrapper["payload"]
    payload["status"] = "INCOMPLETE"
    payload["tasks"]["task-2"].update({
        "status": "INCOMPLETE",
        "reason": "transferred input hash mismatch: required.DM",
        "result_manifest_sha256": sha(manifest_path),
    })
    wrapper["sha256"] = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    state_path.write_text(
        json.dumps(wrapper, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    assert (
        controller(campaign, "legacy-recovery").run(
            install_signal_handlers=False
        )
        is ExecutionStatus.COMPLETED
    )
    recovered = state(tmp_path)["tasks"]["task-2"]
    assert recovered["attempts"] == 1
    assert recovered["status"] == "COMPLETED"


def test_failed_dependency_blocks_child_without_launch(tmp_path: Path):
    campaign, config = make_package(tmp_path, ["FAIL", "SUCCESS"], max_parallel=2)
    config["tasks"][1]["depends_on"] = ["task-1"]
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    assert controller(campaign, "dag-fail").run(install_signal_handlers=False) is ExecutionStatus.FAILED
    tasks = state(tmp_path)["tasks"]
    assert tasks["task-1"]["status"] == "FAILED"
    assert tasks["task-2"]["status"] == "BLOCKED"
    assert not (tmp_path / "work" / "task-2").exists()


def test_hydra_requires_one_explicit_bootstrap_argument_pair(tmp_path: Path):
    source = tmp_path / "input.fdf"
    source.write_text("test\n", encoding="utf-8")
    spec = StepLaunchSpec(
        "u-site-1", "attempt-0001", tmp_path, source,
        tmp_path / "out", tmp_path / "err", 40, 1, "siesta",
        hosts=("tt1", "tt2"), processes_per_node=20, nodes=2,
    )
    with pytest.raises(ValueError, match="bootstrap"):
        HydraLauncher()
    with pytest.raises(ValueError, match="bootstrap"):
        HydraLauncher(arguments=("-bootstrap", ""))
    with pytest.raises(ValueError, match="bootstrap"):
        HydraLauncher(arguments=("-bootstrap", "ssh", "-bootstrap", "slurm"))
    command = HydraLauncher(arguments=("-bootstrap", "ssh")).build_command(spec)
    assert command[:7] == (
        "mpiexec.hydra", "-bootstrap", "ssh", "-hosts", "tt1,tt2", "-np", "40"
    )
    assert ("-ppn", "20") == command[7:9]
    assert command[-1] == "siesta"
    slurm = HydraLauncher(arguments=("-bootstrap", "slurm")).build_command(spec)
    assert slurm[slurm.index("-bootstrap") + 1] == "slurm"
    with pytest.raises(TypeError):
        HydraLauncher(
            arguments=("-bootstrap", "ssh"),
            fabric_uuid_environment="FI_PSM3_UUID",
        )
    with pytest.raises(TypeError):
        HydraLauncher(arguments=("-bootstrap", "ssh")).build_command(
            spec, fabric_uuid="00000000-0000-0000-0000-000000000001"
        )


def test_launcher_adapter_requires_hydra_bootstrap_only() -> None:
    with pytest.raises(ValueError, match="bootstrap"):
        launcher_registry.require("hydra").create()
    assert launcher_registry.require("hydra").create(
        arguments=("-bootstrap", "ssh")
    ).arguments == ("-bootstrap", "ssh")
    assert launcher_registry.require("srun").create() is not None
    assert launcher_registry.require("direct").create() is not None
    assert launcher_registry.require("openmpi").create() is not None


def test_schema2_hydra_controller_assigns_exclusive_hosts(tmp_path: Path):
    campaign, config = make_package(
        tmp_path, ["SUCCESS", "SUCCESS"], total_cpus=40, max_parallel=2,
        mpi_processes=20,
    )
    config["schema_version"] = "2.0"
    config["resources"]["nodes"] = 2
    config["runtime"].pop("srun_command")
    config["runtime"].pop("srun_arguments")
    config["runtime"]["launcher"] = {
        "kind": "hydra",
        "command": ["mpiexec.hydra"],
        "arguments": [],
        "bootstrap": "ssh",
        "processes_per_node": 20,
    }
    for task in config["tasks"]:
        task["nodes"] = 1
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    launcher = SuccessfulCapturingLauncher()
    env = environment(tmp_path, "hydra-job", total_cpus=40)
    env.update({
        "SLURM_NNODES": "2",
        "QRAFT_HOSTS": "tt76,tt77",
    })
    current = AllocationController.from_file(
        campaign, environment=env, launcher=launcher, poll_interval_seconds=0.01
    )
    assert current.run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    assert {spec.hosts for spec in launcher.specs} == {("tt76",), ("tt77",)}


def test_hydra_bootstrap_is_materialized_in_execution_spec_and_canonical_launcher(
    tmp_path: Path,
) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"], total_cpus=20, mpi_processes=20)
    config["schema_version"] = "2.0"
    config["resources"]["nodes"] = 1
    config["runtime"].pop("srun_command")
    config["runtime"].pop("srun_arguments")
    config["runtime"]["launcher"] = {
        "kind": "hydra",
        "command": ["mpiexec.hydra"],
        "arguments": [],
        "bootstrap": "ssh",
        "processes_per_node": 20,
    }
    config["tasks"][0]["nodes"] = 1
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    loaded = load_controller_config(campaign)
    assert loaded.launcher_bootstrap == "ssh"
    assert loaded.srun_arguments == ("-bootstrap", "ssh")
    first = translate_controller_config(loaded, root=tmp_path)
    assert first.execution_specs["task-1"].launcher_arguments == ("-bootstrap", "ssh")

    config["runtime"]["launcher"]["bootstrap"] = "slurm"
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    second = translate_controller_config(load_controller_config(campaign), root=tmp_path)
    assert first.execution_specs["task-1"].fingerprint != second.execution_specs["task-1"].fingerprint
    assert first.scientific_identities["task-1"].fingerprint == second.scientific_identities["task-1"].fingerprint

    env = environment(tmp_path, "hydra-canonical", total_cpus=20)
    env.update({"QRAFT_HOSTS": "tt76"})
    canonical = CanonicalController.from_file(campaign, environment=env)
    assert isinstance(canonical.launcher, HydraLauncher)
    assert canonical.launcher.arguments == ("-bootstrap", "slurm")


def test_runtime_composition_hydra_uses_execution_spec_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution = ExecutionSpec(
        partition="test", nodes=1, mpi_ranks=20, cpus_per_rank=1,
        memory_mb=None, launcher="hydra", executable="siesta", walltime_seconds=60,
        launcher_arguments=("-bootstrap", "ssh"),
    )
    env = environment(tmp_path, "hydra-compose", total_cpus=20)
    env.update({"QRAFT_HOSTS": "tt76", "SLURM_TASKS_PER_NODE": "20"})
    monkeypatch.setattr(
        "qraft.execution.runtime_composition.probe_launcher_placement",
        lambda **_kwargs: {"status": "PASS"},
    )
    composition = compose_runtime(
        execution, environment=env, placement_probe_root=tmp_path / "probe"
    )
    assert isinstance(composition.launcher, HydraLauncher)
    assert composition.launcher.arguments == execution.launcher_arguments


def test_runtime_composition_blocks_observed_runtime_contradiction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = ExecutionSpec(
        partition="local", nodes=1, mpi_ranks=1, cpus_per_rank=1,
        memory_mb=None, launcher="direct", executable="siesta",
        walltime_seconds=60,
    )
    monkeypatch.setattr(
        "qraft.execution.runtime_composition.observe_runtime_evidence",
        lambda *_args: ({
            "engine": {"runtime_instance": "instance-a"},
            "launcher": {"runtime_instance": "instance-b"},
            "environment": {},
        }, {}),
    )
    with pytest.raises(ValueError, match="RUNTIME_COMPATIBILITY_INCOMPATIBLE"):
        compose_runtime(execution, environment={})


def test_hash_bound_gate_task_runs_after_parent_and_emits_decision(tmp_path: Path):
    campaign, config = make_package(
        tmp_path, ["ARTIFACT", "SUCCESS"], max_parallel=2, required_artifact=True
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    selector = scripts / "select.py"
    selector.write_text(
        "from pathlib import Path\n"
        "assert Path('parent.DM').read_text() == 'dm'\n"
        "Path('selected.json').write_text('{\"selected\":\"parent\"}\\n')\n",
        encoding="utf-8",
    )
    gate = config["tasks"][1]
    gate.update({
        "kind": "gate",
        "input": "scripts/select.py",
        "input_hashes": {"scripts/select.py": sha(selector)},
        "required_artifacts": ["selected.json"],
        "mpi_processes": 1,
        "cpus_per_process": 1,
        "nodes": 0,
        "depends_on": ["task-1"],
        "transfers": [{
            "from_task": "task-1",
            "artifact": "required.DM",
            "destination": "parent.DM",
        }],
        "command": [sys.executable, "select.py"],
        "require_scf_converged": False,
    })
    campaign.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    assert controller(campaign, "gate-job").run(
        install_signal_handlers=False
    ) is ExecutionStatus.COMPLETED
    result = tmp_path / "work" / "task-2" / "attempt-0001" / "selected.json"
    assert json.loads(result.read_text())["selected"] == "parent"
    manifest = json.loads(
        (result.parent / "result_manifest.json").read_text()
    )
    assert manifest["task_kind"] == "gate"
    assert manifest["parser_classification"] == "GATE_EXIT_STATUS"


class BlockingLauncher:
    def __init__(self, shutdown: ShutdownRequest) -> None:
        self.shutdown = shutdown
        self.release = threading.Event()
        self.terminated = False

    def launch(self, spec) -> StepOutcome:
        spec.stdout_path.write_text("SIESTA started\nSCF iteration 1\n", encoding="utf-8")
        spec.stderr_path.write_text("", encoding="utf-8")
        self.release.wait(2)
        return StepOutcome(spec.task_id, spec.attempt_id, ("srun",), 143, 0.03, self.terminated)

    def terminate_all(self, *, kill: bool = False):
        self.terminated = True
        self.release.set()
        return ("active",)


class SuccessfulCapturingLauncher:
    def __init__(self) -> None:
        self.specs: list[StepLaunchSpec] = []

    def launch(self, spec: StepLaunchSpec) -> StepOutcome:
        self.specs.append(spec)
        spec.stdout_path.write_text(
            "Version: 5.4.2\nReading input FDF\nSCF cycle 1\n"
            "SCF cycle converged\nJob completed\n",
            encoding="utf-8",
        )
        spec.stderr_path.write_text("", encoding="utf-8")
        return StepOutcome(
            spec.task_id, spec.attempt_id, ("captured",), 0, 0.01, False
        )

    def terminate_all(self, *, kill: bool = False):
        return ()
