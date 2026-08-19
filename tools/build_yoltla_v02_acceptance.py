#!/usr/bin/env python3
"""Build the non-scientific two-stage Yoltla acceptance campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from qraft.controller_package import ControllerPackageBuilder


PACKAGE_ID = "QRAFT_V02_YOLTLA_TWO_STAGE_ACCEPTANCE"
PROFILES = {
    "q1h-20p": {
        "package_id": PACKAGE_ID,
        "partition": "q1h-20p",
        "nodes": 1,
        "tasks": 20,
        "tasks_per_node": 20,
        "memory": "64000M",
    },
    "tt2d-64p": {
        "package_id": f"{PACKAGE_ID}_TT2D64",
        "partition": "tt2d-64p",
        "nodes": 2,
        "tasks": 64,
        "tasks_per_node": 32,
        "memory": "256000M",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(
    repository: Path,
    output: Path,
    profile_name: str = "q1h-20p",
) -> Path:
    profile = PROFILES[profile_name]
    source_root = output / "source"
    source_root.mkdir(parents=True, exist_ok=False)
    (source_root / "input").mkdir()
    (source_root / "pseudopotentials").mkdir()
    source_package = (
        repository
        / "remote_validation"
        / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE"
    )
    base = (source_package / "input" / "smoke.fdf").read_text(encoding="utf-8")
    first = base + "\nDM.UseSaveDM F\n"
    second = base + "\nDM.UseSaveDM T\n"
    (source_root / "input" / "01_parent.fdf").write_text(
        first, encoding="utf-8", newline="\n"
    )
    (source_root / "input" / "02_restart.fdf").write_text(
        second, encoding="utf-8", newline="\n"
    )
    shutil.copy2(
        source_package / "pseudopotentials" / "C.psml",
        source_root / "pseudopotentials" / "C.psml",
    )
    inputs = {
        relative: sha(source_root / relative)
        for relative in (
            "input/01_parent.fdf",
            "input/02_restart.fdf",
            "pseudopotentials/C.psml",
        )
    }
    common = {
        "required_artifacts": ["Gr5x5_clean_v01.DM"],
        "mpi_processes": profile["tasks"],
        "cpus_per_process": 1,
        "nodes": profile["nodes"],
        "estimated_runtime_seconds": 1200,
        "max_attempts": 2,
        "require_scf_converged": True,
    }
    campaign = {
        "schema_version": "2.0",
        "campaign_id": profile["package_id"],
        "system_id": "SURF_Gr5x5_clean_v01_TECHNICAL_ACCEPTANCE",
        "classification": [
            "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE",
            "ENERGY_INTERPRETATION_FORBIDDEN",
        ],
        "slurm": {
            "partition": profile["partition"],
            "account": "vini",
            "qos": "normal",
        },
        "resources": {
            "nodes": profile["nodes"],
            "total_cpus": profile["tasks"],
            "memory": profile["memory"],
            "walltime": "01:00:00",
            "max_parallel_steps": 1,
            "shutdown_margin_seconds": 300,
            "termination_grace_seconds": 30,
        },
        "runtime": {
            "module_commands": [
                "module purge",
                "module load siesta/5.4.2",
                "module load python/3.12",
            ],
            "siesta_executable": "siesta",
            "executable_arguments": [],
            "launcher": {
                "kind": "hydra",
                "command": ["mpiexec.hydra"],
                "arguments": [],
                "bootstrap": "ssh",
                "processes_per_node": profile["tasks_per_node"],
            },
            "exclusive": True,
            "environment": {
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "I_MPI_PIN": "1",
                "I_MPI_PIN_DOMAIN": "core",
            },
        },
        "tasks": [
            {
                "task_id": "01_parent",
                "input": "input/01_parent.fdf",
                "input_hashes": {
                    "input/01_parent.fdf": inputs["input/01_parent.fdf"],
                    "pseudopotentials/C.psml": inputs["pseudopotentials/C.psml"],
                },
                **common,
            },
            {
                "task_id": "02_restart_from_parent_dm",
                "input": "input/02_restart.fdf",
                "input_hashes": {
                    "input/02_restart.fdf": inputs["input/02_restart.fdf"],
                    "pseudopotentials/C.psml": inputs["pseudopotentials/C.psml"],
                },
                "depends_on": ["01_parent"],
                "transfers": [{
                    "from_task": "01_parent",
                    "artifact": "Gr5x5_clean_v01.DM",
                    "destination": "Gr5x5_clean_v01.DM",
                }],
                **common,
            },
        ],
    }
    path = source_root / "campaign.json"
    path.write_text(
        json.dumps(campaign, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="q1h-20p",
    )
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    campaign = materialize(repository, output, args.profile)
    package_root = output / "package"
    package_root.mkdir()
    result = ControllerPackageBuilder(repository).build(campaign, package_root)
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
