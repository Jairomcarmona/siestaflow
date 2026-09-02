from __future__ import annotations

from pathlib import Path

import pytest

from qraft.execution.openmpi_launcher import OpenMpiLauncher
from qraft.execution.srun_launcher import StepLaunchSpec


def _spec(
    tmp_path: Path,
    *,
    hosts: tuple[str, ...] = (),
    nodes: int | None = None,
    mpi_processes: int = 4,
    processes_per_node: int | None = None,
) -> StepLaunchSpec:
    return StepLaunchSpec(
        task_id="placement",
        attempt_id="attempt",
        workdir=tmp_path,
        input_path=tmp_path / "input.fdf",
        stdout_path=tmp_path / "stdout.txt",
        stderr_path=tmp_path / "stderr.txt",
        mpi_processes=mpi_processes,
        cpus_per_process=1,
        executable="hostname",
        hosts=hosts,
        nodes=nodes,
        processes_per_node=processes_per_node,
    )


def test_openmpi_host_slots_represent_one_host_four_ranks(tmp_path: Path) -> None:
    command = OpenMpiLauncher().build_command(_spec(
        tmp_path, hosts=("node-a",), nodes=1, mpi_processes=4,
        processes_per_node=4,
    ))
    assert command == (
        "mpirun", "-np", "4", "--host", "node-a:4",
        "--map-by", "ppr:4:node", "hostname",
    )


def test_openmpi_host_slots_represent_two_hosts_four_ranks_each(tmp_path: Path) -> None:
    command = OpenMpiLauncher().build_command(_spec(
        tmp_path, hosts=("node-a", "node-b"), nodes=2, mpi_processes=8,
        processes_per_node=4,
    ))
    assert command == (
        "mpirun", "-np", "8", "--host", "node-a:4,node-b:4",
        "--map-by", "ppr:4:node", "hostname",
    )


def test_openmpi_host_slots_do_not_hardcode_ranks_per_host(tmp_path: Path) -> None:
    command = OpenMpiLauncher().build_command(_spec(
        tmp_path, hosts=("node-a", "node-b"), nodes=2, mpi_processes=6,
        processes_per_node=3,
    ))
    assert command == (
        "mpirun", "-np", "6", "--host", "node-a:3,node-b:3",
        "--map-by", "ppr:3:node", "hostname",
    )


@pytest.mark.parametrize(
    ("hosts", "nodes", "mpi_processes", "processes_per_node", "message"),
    [
        (("node-a", "node-b"), 2, 7, 4, "placement mismatch"),
        (("node-a", "node-b"), 1, 8, 4, "placement nodes"),
        (("node-a",), 1, 4, None, "processes_per_node"),
    ],
)
def test_openmpi_rejects_inconsistent_explicit_host_placement(
    tmp_path: Path,
    hosts: tuple[str, ...],
    nodes: int,
    mpi_processes: int,
    processes_per_node: int | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        OpenMpiLauncher().build_command(_spec(
            tmp_path, hosts=hosts, nodes=nodes, mpi_processes=mpi_processes,
            processes_per_node=processes_per_node,
        ))


def test_openmpi_without_hosts_preserves_local_command_behavior(tmp_path: Path) -> None:
    command = OpenMpiLauncher(arguments=("--bind-to", "none")).build_command(
        _spec(tmp_path)
    )
    assert command == (
        "mpirun", "--bind-to", "none", "-np", "4", "hostname",
    )


def test_openmpi_preserves_configured_argument_order_with_host_slots(tmp_path: Path) -> None:
    command = OpenMpiLauncher(arguments=("--bind-to", "none", "--mca", "btl", "self,vader")).build_command(_spec(
        tmp_path, hosts=("node-a",), nodes=1, mpi_processes=2,
        processes_per_node=2,
    ))
    assert command == (
        "mpirun", "--bind-to", "none", "--mca", "btl", "self,vader",
        "-np", "2", "--host", "node-a:2", "--map-by", "ppr:2:node",
        "hostname",
    )
