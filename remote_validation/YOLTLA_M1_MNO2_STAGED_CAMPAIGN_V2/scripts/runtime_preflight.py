#!/usr/bin/env python3
"""Fail-closed launcher and environment probe executed inside the allocation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "runtime"))
import profilectl
from siestaflow.execution.resource_manager import ResourceManager
from siestaflow.execution.slurm_environment import SlurmEnvironment


class PreflightError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PreflightError(f"COMMAND_NOT_FOUND:{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PreflightError(f"COMMAND_TIMEOUT:{command[0]}") from exc
    if result.returncode:
        detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        raise PreflightError(f"COMMAND_FAILED:{command[0]}:{result.returncode}:{detail}")
    return result


def normalized_hosts(text: str) -> set[str]:
    return {
        line.strip().split(".", 1)[0]
        for line in text.splitlines()
        if line.strip() and " " not in line.strip()
    }


def launcher_probe(
    profile: dict[str, Any], slurm: SlurmEnvironment, prepared: Path
) -> dict[str, Any]:
    launcher = profile["runtime"]["launcher"]
    backend = launcher["backend"]
    evidence = prepared / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    expected = {host.split(".", 1)[0] for host in slurm.hosts}
    if backend == "hydra_ssh":
        if launcher.get("bootstrap") != "ssh":
            raise PreflightError("HYDRA_BOOTSTRAP_MUST_BE_SSH")
        hostfile = evidence / "runtime_preflight.hydra.hosts"
        hostfile.write_text(
            "".join(f"{host}:1\n" for host in slurm.hosts),
            encoding="utf-8",
            newline="\n",
        )
        command = [
            *map(str, launcher["command"]),
            "-bootstrap",
            "ssh",
            *map(str, launcher.get("arguments", [])),
            "-f",
            str(hostfile),
            "-n",
            str(slurm.nodes),
            "-ppn",
            "1",
            "/bin/hostname",
        ]
        siesta_command = [
            *map(str, launcher["command"]),
            "-bootstrap",
            "ssh",
            *map(str, launcher.get("arguments", [])),
            "-f",
            str(hostfile),
            "-n",
            str(slurm.nodes),
            "-ppn",
            "1",
            str(profile["runtime"]["siesta_executable"]),
            "--version",
        ]
    elif backend == "srun":
        command = [
            *map(str, launcher["command"]),
            *map(str, launcher.get("arguments", [])),
            "--exclusive",
            "--exact",
            f"--nodes={slurm.nodes}",
            f"--ntasks={slurm.nodes}",
            "--ntasks-per-node=1",
            f"--nodelist={','.join(slurm.hosts)}",
            "/bin/hostname",
        ]
        siesta_command = [*command[:-1], str(profile["runtime"]["siesta_executable"]), "--version"]
        hostfile = None
    else:
        raise PreflightError(f"UNSUPPORTED_LAUNCHER:{backend}")
    host_result = run(command, cwd=prepared)
    observed = normalized_hosts(host_result.stdout)
    if observed != expected:
        raise PreflightError(
            f"LAUNCHER_HOST_MISMATCH:expected={sorted(expected)}:observed={sorted(observed)}"
        )
    version_result = run(siesta_command, cwd=prepared)
    observed_version = profilectl.parse_siesta_version(
        (version_result.stdout or "") + "\n" + (version_result.stderr or "")
    )
    if observed_version != profile["runtime"]["required_siesta_version"]:
        raise PreflightError(f"MPI_SIESTA_VERSION_MISMATCH:{observed_version}")
    return {
        "backend": backend,
        "host_probe_command": command,
        "host_probe_stdout": host_result.stdout,
        "mpi_siesta_version_command": siesta_command,
        "mpi_siesta_version": observed_version,
        "hostfile_sha256": sha(hostfile) if hostfile else None,
    }


def topology_probe(profile: dict[str, Any], hosts: tuple[str, ...]) -> dict[str, Any]:
    layouts = profile["resource_layouts"]
    selected = layouts["available"][layouts["selected"]]
    manager = ResourceManager(hosts, int(profile["resources"]["tasks_per_node"]))
    reservations = []
    for index in range(int(selected["max_parallel_steps"])):
        reservation = manager.reserve(
            f"preflight-{index + 1}",
            int(selected["mpi_processes_per_step"]),
            int(selected["nodes_per_step"]),
        )
        if reservation is None:
            raise PreflightError("SELECTED_LAYOUT_CANNOT_BE_RESERVED_WITHOUT_OVERLAP")
        reservations.append(reservation.as_dict())
    snapshot = manager.snapshot()
    for index in range(len(reservations)):
        manager.release(f"preflight-{index + 1}")
    return {"selected_layout": layouts["selected"], "reservations": reservations, "snapshot": snapshot}


def preflight(profile_path: Path, prepared: Path) -> dict[str, Any]:
    try:
        profile = profilectl.validate(profile_path, production=True)
    except profilectl.ProfileError as exc:
        raise PreflightError(str(exc)) from exc
    modules = os.environ.get("LOADEDMODULES", "").split(":")
    for module in profile["modules"]["load"]:
        if module not in modules:
            raise PreflightError(f"DECLARED_MODULE_NOT_LOADED:{module}")
    profilectl.check_siesta_version(
        str(profile["runtime"]["siesta_executable"]),
        str(profile["runtime"]["required_siesta_version"]),
    )
    resources = profile["resources"]
    slurm = SlurmEnvironment.from_mapping(
        configured_walltime=str(resources["walltime"])
    )
    slurm.validate_capacity(
        nodes=int(resources["nodes"]),
        total_cpus=int(resources["total_cpus"]),
        tasks_per_node=int(resources["tasks_per_node"]),
    )
    if prepared.resolve() != slurm.submit_dir:
        raise PreflightError("PREPARED_ROOT_NOT_SLURM_SUBMIT_DIR")
    write_probe = prepared / "evidence/.runtime_preflight_write_probe"
    write_probe.parent.mkdir(parents=True, exist_ok=True)
    write_probe.write_text("write-ok\n", encoding="utf-8")
    write_probe.unlink()
    inputs = list((prepared / "input").glob("*.fdf"))
    if not inputs:
        raise PreflightError("NO_FDF_INPUTS_FOUND")
    for item in [*inputs, prepared / "pseudopotentials/Mn.psml", prepared / "pseudopotentials/O.psml"]:
        if not item.is_file() or not os.access(item, os.R_OK):
            raise PreflightError(f"INPUT_NOT_READABLE:{item}")
    topology = topology_probe(profile, slurm.hosts)
    launcher = launcher_probe(profile, slurm, prepared)
    report = {
        "schema_version": "2.0",
        "status": "RUNTIME_PREFLIGHT_PASS",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "job_id": slurm.job_id,
        "hosts": list(slurm.hosts),
        "nodes": slurm.nodes,
        "ntasks": slurm.ntasks,
        "tasks_per_node": slurm.tasks_per_node,
        "end_time_source": slurm.end_time_source,
        "working_directory_writable": True,
        "inputs_readable": True,
        "topology": topology,
        "launcher": launcher,
        "limitations": [
            "The two-node hostname and MPI SIESTA version probes validate launch reachability, not production scaling.",
            "Affinity non-overlap is proven for the internal reservation plan; remote CPU binding remains recorded and must be audited from scheduler/runtime evidence.",
        ],
    }
    output = prepared / "evidence/runtime_preflight.json"
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--prepared-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = preflight(args.profile.resolve(), args.prepared_root.resolve())
    except (
        PreflightError,
        profilectl.ProfileError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
