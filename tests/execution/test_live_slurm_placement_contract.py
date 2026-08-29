from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from qraft.controller_package import ControllerPackageBuilder
from qraft.core import ExecutionSpec, ScientificIdentity
from qraft.execution.allocation_controller import ControllerConfig
from qraft.execution.canonical_controller import CanonicalController
from qraft.execution.hydra_launcher import HydraLauncher
from qraft.execution.placement_validation import probe_launcher_placement
from qraft.execution.slurm_environment import (
    SlurmEnvironment,
    parse_slurm_tasks_per_node,
)
from qraft.execution.srun_launcher import SrunLauncher, StepLaunchSpec, StepOutcome
from qraft.slurm_resources import (
    LiveSlurmPlacementService,
    SlurmCommandOutput,
    discover_live_slurm,
    write_live_selection_provenance,
)
from qraft.validation.scheduler_resolution import ResourceRequest


def _slurm_outputs(*, include_new: bool = False, remove_beta: bool = False):
    partitions = {
        "partition_alpha": ("up", 4, 20, 64000, 1, 1, "01:00:00"),
        "partition_beta": ("up", 4, 32, 128000, 4, 4, "02:00:00"),
        "partition_gamma": ("up", 8, 24, 96000, 2, 8, "01:00:00"),
        "partition_heterogeneous": ("up", 4, 20, 64000, 4, 4, "01:00:00"),
        "partition_down": ("down", 2, 20, 64000, 2, 2, "01:00:00"),
    }
    if remove_beta:
        partitions.pop("partition_beta")
    if include_new:
        partitions["partition_new"] = ("up", 3, 12, 48000, 3, 3, "01:00:00")
    sinfo = "\n".join(
        f"{name}|{state}|{maximum}|{visible}|{cpus}|{memory}"
        for name, (state, visible, cpus, memory, _minimum, _maximum, maximum)
        in partitions.items()
    ) + "\n"
    policies = "\n".join(
        " ".join((
            f"PartitionName={name}",
            f"State={'UP' if state == 'up' else 'DOWN'}",
            f"MinNodes={minimum}",
            f"MaxNodes={maximum_nodes}",
            f"MaxTime={maximum}",
            "AllowAccounts=ALL",
            "AllowQos=ALL",
        ))
        for name, (state, _visible, _cpus, _memory, minimum, maximum_nodes, maximum)
        in partitions.items()
    ) + "\n"
    node_rows: list[str] = []
    for name, (state, visible, cpus, memory, *_rest) in partitions.items():
        capacities = [cpus] * visible
        if name == "partition_heterogeneous":
            capacities = [20, 20, 32, 32]
        for index, node_cpus in enumerate(capacities, 1):
            node_rows.append(
                f"{name}-node{index}|{name}|{node_cpus}|{memory}|{state}"
            )
    return {
        "sinfo": sinfo,
        "nodes": "\n".join(node_rows) + "\n",
        "policies": policies,
        "associations": "research_account||normal,expedited\n",
    }


class FakeSlurmRunner:
    def __init__(self, outputs):
        self.outputs = outputs
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        argv = tuple(command)
        self.commands.append(argv)
        if argv[0] == "sinfo" and "-N" in argv:
            text = self.outputs["nodes"]
        elif argv[0] == "sinfo":
            text = self.outputs["sinfo"]
        elif argv[0] == "scontrol":
            text = self.outputs["policies"]
        else:
            text = self.outputs["associations"]
        return SlurmCommandOutput(argv, 0, text)


def _service(**kwargs) -> tuple[LiveSlurmPlacementService, FakeSlurmRunner]:
    runner = FakeSlurmRunner(_slurm_outputs(**kwargs))
    evidence = discover_live_slurm(
        runner=runner,
        user="researcher",
        observed_at="2026-08-29T00:00:00Z",
    )
    return LiveSlurmPlacementService(evidence), runner


def _request(*, nodes=None, cpus_per_task=1, walltime="00:20:00", account="research_account", qos="normal"):
    return ResourceRequest(
        nodes=nodes,
        cpus_per_task=cpus_per_task,
        walltime=walltime,
        account=account,
        qos=qos,
    )


def test_live_discovery_is_injectable_and_tracks_new_or_removed_partitions():
    service, runner = _service()
    assert {item.name for item in service.evidence.visible_partitions} >= {
        "partition_alpha", "partition_beta", "partition_gamma"
    }
    assert any(item.partition == "partition_alpha" for item in service.evidence.node_capabilities)
    assert runner.commands == [
        ("sinfo", "-h", "-o", "%P|%a|%l|%D|%c|%m"),
        ("sinfo", "-N", "-h", "-o", "%N|%P|%c|%m|%t"),
        ("scontrol", "show", "partition", "-o"),
        ("sacctmgr", "-n", "-P", "show", "assoc", "user=researcher", "format=Account,Partition,QOS"),
    ]
    added, _ = _service(include_new=True)
    removed, _ = _service(remove_beta=True)
    assert "partition_new" in {item.name for item in added.evidence.visible_partitions}
    assert "partition_beta" not in {item.name for item in removed.evidence.visible_partitions}


def test_live_policy_rejects_invalid_association_and_down_partition():
    service, _ = _service()
    options = {
        item["partition"]: item
        for item in service.show_resources(resource_request=_request())
    }
    assert options["partition_alpha"]["status"] == "SELECTABLE"
    assert options["partition_gamma"]["status"] == "MANUAL_NODE_SELECTION_REQUIRED"
    assert options["partition_heterogeneous"]["status"] == "NOT_SELECTABLE"
    with pytest.raises(ValueError, match="USER_ASSOCIATION_NOT_UNIQUE"):
        service.select(partition="partition_alpha", resource_request=_request(account="other"))
    with pytest.raises(ValueError, match="USER_ASSOCIATION_NOT_UNIQUE"):
        service.select(partition="partition_alpha", resource_request=_request(qos="other"))
    with pytest.raises(ValueError, match="PARTITION_NOT_AVAILABLE|PARTITION_NOT_UP"):
        service.select(partition="partition_down", resource_request=_request())


def test_fixed_and_ranged_placement_math_is_live_evidence_bound():
    service, _ = _service()
    alpha = service.select(
        partition="partition_alpha", resource_request=_request()
    ).placement
    assert (alpha.nodes, alpha.tasks_per_node, alpha.ntasks) == (1, 20, 20)
    beta = service.select(
        partition="partition_beta", resource_request=_request(cpus_per_task=2)
    ).placement
    assert (beta.nodes, beta.tasks_per_node, beta.ntasks) == (4, 16, 64)
    with pytest.raises(ValueError, match="MANUAL_NODE_SELECTION_REQUIRED"):
        service.select(partition="partition_gamma", resource_request=_request())
    gamma = service.select(
        partition="partition_gamma", resource_request=_request(nodes=5)
    ).placement
    assert (gamma.nodes, gamma.tasks_per_node, gamma.ntasks) == (5, 24, 120)
    with pytest.raises(ValueError, match="SELECTED_NODES_OUTSIDE_POLICY"):
        service.select(
            partition="partition_gamma", resource_request=_request(nodes=9)
        )


def test_unsafe_capacity_walltime_and_overcommit_fail_closed():
    service, _ = _service()
    with pytest.raises(ValueError, match="HETEROGENEOUS_NODE_CAPABILITY"):
        service.select(
            partition="partition_heterogeneous", resource_request=_request()
        )
    with pytest.raises(ValueError, match="MAX_TIME_VIOLATED"):
        service.select(
            partition="partition_alpha",
            resource_request=_request(walltime="02:00:00"),
        )
    with pytest.raises(ValueError, match="CPU_OVERCOMMIT"):
        service.select(
            partition="partition_alpha",
            resource_request=_request(cpus_per_task=21),
        )


def _campaign(placement, launcher="hydra"):
    return {
        "campaign_id": "placement-contract",
        "slurm": {
            "partition": placement.partition,
            "account": "research_account",
            "qos": "normal",
        },
        "resources": {
            "nodes": placement.nodes,
            "ntasks": placement.ntasks,
            "cpus_per_task": placement.cpus_per_task,
            "total_cpus": placement.total_allocated_cpus,
            "memory": "1G",
            "walltime": placement.walltime,
            "shutdown_margin_seconds": 60,
        },
        "runtime": {
            "module_commands": [],
            "siesta_executable": "siesta",
            "launcher": {
                "kind": launcher,
                "processes_per_node": placement.tasks_per_node,
            },
            "environment": {},
        },
    }


def _launch_spec(tmp_path: Path, placement):
    return StepLaunchSpec(
        task_id="placement",
        attempt_id="attempt",
        workdir=tmp_path,
        input_path=tmp_path / "input",
        stdout_path=tmp_path / "stdout",
        stderr_path=tmp_path / "stderr",
        mpi_processes=placement.ntasks,
        cpus_per_process=placement.cpus_per_task,
        executable="hostname",
        hosts=tuple(f"node-{index}" for index in range(placement.nodes)),
        processes_per_node=placement.tasks_per_node,
        nodes=placement.nodes,
    )


def test_sbatch_hydra_and_srun_consume_one_derived_placement(tmp_path: Path):
    service, _ = _service()
    placement = service.select(
        partition="partition_beta", resource_request=_request(cpus_per_task=2)
    ).placement
    submit = ControllerPackageBuilder(Path.cwd())._slurm(_campaign(placement))
    hydra = HydraLauncher(arguments=("-bootstrap", "ssh"))
    srun = SrunLauncher(srun_command=("srun",))
    spec = _launch_spec(tmp_path, placement)
    hydra_command = hydra.build_command(spec)
    srun_command = srun.build_command(spec)
    assert "#SBATCH --nodes=4" in submit
    assert "#SBATCH --ntasks=64" in submit
    assert "#SBATCH --ntasks-per-node=16" in submit
    assert "#SBATCH --cpus-per-task=2" in submit
    assert hydra_command[hydra_command.index("-np") + 1] == "64"
    assert hydra_command[hydra_command.index("-ppn") + 1] == "16"
    assert "--nodes=4" in srun_command
    assert "--ntasks=64" in srun_command
    assert "--ntasks-per-node=16" in srun_command
    assert "--cpus-per-task=2" in srun_command

    changed = service.select(
        partition="partition_gamma", resource_request=_request(nodes=5)
    ).placement
    changed_submit = ControllerPackageBuilder(Path.cwd())._slurm(_campaign(changed, "srun"))
    changed_srun = SrunLauncher(srun_command=("srun",)).build_command(
        _launch_spec(tmp_path, changed)
    )
    assert "#SBATCH --nodes=5" in changed_submit
    assert "#SBATCH --ntasks=120" in changed_submit
    assert "--nodes=5" in changed_srun and "--ntasks=120" in changed_srun


def _environment(root: Path, **changes: str) -> dict[str, str]:
    values = {
        "SLURM_JOB_ID": "123",
        "SLURM_SUBMIT_DIR": str(root),
        "SLURM_JOB_END_TIME": str(time.time() + 300),
        "SLURM_NNODES": "4",
        "SLURM_NTASKS": "80",
        "SLURM_CPUS_PER_TASK": "1",
        "SLURM_TASKS_PER_NODE": "20(x4)",
        "SLURM_JOB_NODELIST": "node-[1-4]",
        "QRAFT_HOSTS": "node-1,node-2,node-3,node-4",
    }
    values.update(changes)
    return values


def test_slurm_tasks_per_node_parser_and_exact_allocation_gate(tmp_path: Path):
    assert parse_slurm_tasks_per_node("20(x2),16,8(x3)") == (
        20, 20, 16, 8, 8, 8
    )
    slurm = SlurmEnvironment.from_mapping(_environment(tmp_path))
    hosts = slurm.validate_exact_placement(
        nodes=4, ntasks=80, cpus_per_task=1, tasks_per_node=20
    )
    assert hosts == ("node-1", "node-2", "node-3", "node-4")

    for field, value, expected in (
        ("SLURM_NNODES", "3", "nodes"),
        ("SLURM_NTASKS", "64", "ntasks"),
        ("SLURM_TASKS_PER_NODE", "16(x4)", "tasks_per_node"),
    ):
        changes = {field: value}
        if field == "SLURM_NNODES":
            changes["QRAFT_HOSTS"] = "node-1,node-2,node-3"
        mismatched = SlurmEnvironment.from_mapping(_environment(tmp_path, **changes))
        with pytest.raises(ValueError, match=f"ALLOCATION_PLACEMENT_MISMATCH:.*{expected}"):
            mismatched.validate_exact_placement(
                nodes=4,
                ntasks=80,
                cpus_per_task=1,
                tasks_per_node=20,
                hosts=("node-1", "node-2", "node-3", "node-4"),
            )
    with pytest.raises(ValueError, match="ALLOCATION_PLACEMENT_MISMATCH:.*hosts"):
        slurm.validate_exact_placement(
            nodes=4,
            ntasks=80,
            cpus_per_task=1,
            tasks_per_node=20,
            hosts=("node-1", "node-2", "node-3"),
        )


class ProbeLauncher:
    def __init__(self, outputs: tuple[str, ...]):
        self.outputs = outputs
        self.calls = 0

    def launch(self, spec):
        self.calls += 1
        spec.stdout_path.write_text("\n".join(self.outputs) + "\n", encoding="utf-8")
        spec.stderr_path.write_text("", encoding="utf-8")
        return StepOutcome(
            spec.task_id,
            spec.attempt_id,
            ("fake-launcher", "hostname"),
            0,
            0.01,
            False,
        )

    def terminate_all(self, *, kill=False):
        return ()


def _execution():
    return ExecutionSpec(
        partition="partition_beta",
        nodes=4,
        mpi_ranks=80,
        cpus_per_rank=1,
        memory_mb=None,
        launcher="srun",
        executable="siesta",
        walltime_seconds=60,
    )


def test_launcher_probe_validates_rank_hosts_and_distribution(tmp_path: Path):
    hosts = ("nodeA", "nodeB", "nodeC", "nodeD")
    valid = tuple(host for host in hosts for _ in range(20))
    payload = probe_launcher_placement(
        launcher=ProbeLauncher(valid),
        execution=_execution(),
        hosts=hosts,
        root=tmp_path / "valid",
    )
    assert payload["status"] == "PASS"
    for invalid in (
        tuple(host for host in ("nodeA", "nodeB") for _ in range(32)),
        valid[:-1],
    ):
        with pytest.raises(ValueError, match="LAUNCHER_PLACEMENT_MISMATCH"):
            probe_launcher_placement(
                launcher=ProbeLauncher(invalid),
                execution=_execution(),
                hosts=hosts,
                root=tmp_path / f"invalid-{len(invalid)}",
            )


def test_canonical_controller_blocks_engine_construction_after_probe_mismatch(
    tmp_path: Path, monkeypatch
):
    config = ControllerConfig(
        campaign_id="contract",
        system_id="system",
        partition="partition_beta",
        nodes=4,
        total_cpus=80,
        max_parallel_steps=1,
        shutdown_margin_seconds=1,
        termination_grace_seconds=1,
        siesta_executable="siesta",
        executable_arguments=(),
        srun_command=("srun",),
        srun_arguments=(),
        exclusive=True,
        environment={},
        tasks=(),
        launcher_kind="srun",
        processes_per_node=20,
        ntasks=80,
        cpus_per_task=1,
    )
    slurm = SlurmEnvironment.from_mapping(_environment(tmp_path))
    controller = CanonicalController(
        root=tmp_path,
        config=config,
        slurm=slurm,
        launcher=ProbeLauncher(tuple(["nodeA"] * 80)),
    )
    monkeypatch.setattr(
        "qraft.execution.canonical_controller.translate_controller_config",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    with pytest.raises(ValueError, match="LAUNCHER_PLACEMENT_MISMATCH"):
        controller.run(install_signal_handlers=False)
    assert controller.runtime is None


def test_identity_execution_and_post_selection_provenance(tmp_path: Path):
    service, _ = _service()
    alpha = service.select(
        partition="partition_alpha", resource_request=_request()
    )
    beta = service.select(
        partition="partition_beta", resource_request=_request()
    )
    digest = "0" * 64
    identity = ScientificIdentity(
        engine="siesta",
        effective_fdf_sha256=digest,
        geometry_sha256=digest,
        species_mapping_sha256=digest,
        pseudopotentials={"C": digest},
        components={},
        included_scientific_files={"input.fdf": digest},
    )
    executions = [
        ExecutionSpec(
            partition=item.placement.partition,
            nodes=item.placement.nodes,
            mpi_ranks=item.placement.ntasks,
            cpus_per_rank=item.placement.cpus_per_task,
            memory_mb=None,
            launcher="srun",
            executable="siesta",
            walltime_seconds=1200,
        )
        for item in (alpha, beta)
    ]
    assert identity.fingerprint == identity.fingerprint
    assert executions[0].fingerprint != executions[1].fingerprint

    provenance = tmp_path / "live-slurm-selection.json"
    write_live_selection_provenance(alpha, provenance)
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["authority"] == "LIVE_SLURM_SELECTION_EVIDENCE"
    assert payload["runtime_authority_for_future_runs"] is False
    assert payload["human_selection"]["partition"] == "partition_alpha"
    assert payload["derived_placement"] == alpha.placement.to_dict()
    assert "login_summary" not in provenance.read_text(encoding="utf-8")
