from __future__ import annotations

import json
from pathlib import Path

import pytest

from qraft.execution_profile import SlurmExecutionProfile


def _value() -> dict:
    return {
        "schema_version": "1.0",
        "profile_id": "strict-profile",
        "target": "slurm",
        "slurm": {
            "partition": "tt2d-64p",
            "account": "vini",
            "qos": "normal",
        },
        "allocation": {
            "nodes": 2,
            "total_cpus": 64,
            "memory": "500G",
            "walltime": "2-00:00:00",
            "max_parallel_steps": 1,
            "shutdown_margin_seconds": 1800,
            "termination_grace_seconds": 30,
        },
        "runtime": {
            "module_commands": [
                "module purge",
                "module load siesta/5.4.2 python/3.12",
            ],
            "siesta_executable": "siesta",
            "executable_arguments": [],
            "launcher": {
                "kind": "hydra",
                "command": ["mpiexec.hydra"],
                "arguments": [],
                "bootstrap": "ssh",
                "processes_per_node": 32,
            },
            "exclusive": True,
            "environment": {"OMP_NUM_THREADS": "1"},
        },
        "task_policy": {
            "max_attempts": 2,
            "require_scf_converged": True,
        },
    }


def _write(root: Path, value: dict) -> Path:
    path = root / "profile.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def test_profile_is_strict_and_hash_stable(tmp_path: Path) -> None:
    first = SlurmExecutionProfile.load(_write(tmp_path, _value()))
    second = SlurmExecutionProfile.load(tmp_path / "profile.json")
    assert first.sha256 == second.sha256
    assert first.nodes * int(first.processes_per_node or 0) == first.total_cpus


def test_resolved_profile_preserves_derived_cpu_geometry(tmp_path: Path) -> None:
    profile = SlurmExecutionProfile.load(_write(tmp_path, _value())).resolved(
        partition="partition_beta",
        account="research_account",
        qos="normal",
        nodes=4,
        ranks_per_node=16,
        cpus_per_task=2,
        walltime="01:00:00",
    )
    assert profile.ntasks == 64
    assert profile.total_cpus == 128
    assert profile.cpus_per_task == 2
    assert profile.processes_per_node == 16


def test_profile_rejects_arbitrary_shell_commands(tmp_path: Path) -> None:
    value = _value()
    value["runtime"]["module_commands"] = ["curl https://example.invalid"]
    with pytest.raises(ValueError, match="module_commands permits only"):
        SlurmExecutionProfile.load(_write(tmp_path, value))


def test_profile_rejects_hydra_placement_mismatch(tmp_path: Path) -> None:
    value = _value()
    value["runtime"]["launcher"]["processes_per_node"] = 20
    with pytest.raises(ValueError, match="nodes \\* processes_per_node"):
        SlurmExecutionProfile.load(_write(tmp_path, value))


def test_profile_rejects_unknown_fields(tmp_path: Path) -> None:
    value = _value()
    value["runtime"]["shell_preamble"] = "arbitrary"
    with pytest.raises(ValueError, match="runtime fields mismatch"):
        SlurmExecutionProfile.load(_write(tmp_path, value))
