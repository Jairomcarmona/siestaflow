"""Allocation-local placement gates that run before scientific engines."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..core import ExecutionSpec
from .srun_launcher import StepLaunchSpec, StepLauncher


def probe_launcher_placement(
    *,
    launcher: StepLauncher,
    execution: ExecutionSpec,
    hosts: tuple[str, ...],
    root: Path,
) -> dict[str, Any]:
    """Run ``hostname`` through the real launcher and validate rank geometry."""

    if len(hosts) != execution.nodes or len(set(hosts)) != execution.nodes:
        raise ValueError(
            "LAUNCHER_PLACEMENT_MISMATCH: allocated host evidence is invalid"
        )
    evidence_root = root / "evidence" / "launcher-placement"
    evidence_root.mkdir(parents=True, exist_ok=True)
    index = 1
    while (evidence_root / f"probe-{index:04d}").exists():
        index += 1
    workdir = evidence_root / f"probe-{index:04d}"
    workdir.mkdir()
    input_path = workdir / "stdin.txt"
    input_path.write_text("", encoding="utf-8")
    stdout_path = workdir / "stdout.txt"
    stderr_path = workdir / "stderr.txt"
    outcome = launcher.launch(StepLaunchSpec(
        task_id="qraft-launcher-placement-probe",
        attempt_id=f"probe-{index:04d}",
        workdir=workdir,
        input_path=input_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        mpi_processes=execution.mpi_ranks,
        cpus_per_process=execution.cpus_per_rank,
        executable="hostname",
        hosts=hosts,
        processes_per_node=execution.ranks_per_node,
        nodes=execution.nodes,
    ))
    observed = tuple(
        line.strip()
        for line in stdout_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    counts = Counter(observed)
    failures: list[str] = []
    if outcome.exit_code != 0:
        failures.append(f"exit_code={outcome.exit_code}")
    if len(observed) != execution.mpi_ranks:
        failures.append(
            f"ranks expected={execution.mpi_ranks} actual={len(observed)}"
        )
    if set(counts) != set(hosts):
        failures.append(
            f"hosts expected={sorted(hosts)} actual={sorted(counts)}"
        )
    invalid_counts = {
        host: counts.get(host, 0)
        for host in hosts
        if counts.get(host, 0) != execution.ranks_per_node
    }
    if invalid_counts:
        failures.append(
            "ranks_per_host "
            f"expected={execution.ranks_per_node} actual={invalid_counts}"
        )
    payload = {
        "schema_version": "1.0",
        "status": "FAIL" if failures else "PASS",
        "execution_spec_sha256": execution.fingerprint,
        "expected": {
            "nodes": execution.nodes,
            "ntasks": execution.mpi_ranks,
            "tasks_per_node": execution.ranks_per_node,
            "hosts": list(hosts),
        },
        "observed": {
            "rank_outputs": len(observed),
            "hosts": sorted(counts),
            "ranks_per_host": dict(sorted(counts.items())),
            "exit_code": outcome.exit_code,
        },
        "command": list(outcome.command),
        "failures": failures,
    }
    (workdir / "placement.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        raise ValueError(
            "LAUNCHER_PLACEMENT_MISMATCH: " + "; ".join(failures)
        )
    return payload
