#!/usr/bin/env python3
"""Build a non-scientific two-stage controller package for local Slurm."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from siestaflow.controller_package import ControllerPackageBuilder


PACKAGE_ID = "SIESTAFLOW_LOCAL_SLURM_CONTROLLER_ACCEPTANCE"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(
    repository: Path,
    output: Path,
    *,
    siesta_executable: str,
    account: str,
) -> Path:
    source_root = output / "source"
    source_root.mkdir(parents=True, exist_ok=False)
    (source_root / "input").mkdir()
    (source_root / "pseudopotentials").mkdir()

    source_package = (
        repository
        / "remote_validation"
        / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE"
    )
    base_fdf = (
        source_package / "input" / "smoke.fdf"
    ).read_text(encoding="utf-8")
    (source_root / "input" / "01_parent.fdf").write_text(
        base_fdf + "\nDM.UseSaveDM F\n",
        encoding="utf-8",
        newline="\n",
    )
    (source_root / "input" / "02_restart.fdf").write_text(
        base_fdf + "\nDM.UseSaveDM T\n",
        encoding="utf-8",
        newline="\n",
    )
    shutil.copy2(
        source_package / "pseudopotentials" / "C.psml",
        source_root / "pseudopotentials" / "C.psml",
    )

    inputs = {
        relative: _sha256(source_root / relative)
        for relative in (
            "input/01_parent.fdf",
            "input/02_restart.fdf",
            "pseudopotentials/C.psml",
        )
    }
    common = {
        "required_artifacts": ["Gr5x5_clean_v01.DM"],
        "mpi_processes": 2,
        "cpus_per_process": 1,
        "nodes": 1,
        "estimated_runtime_seconds": 420,
        "max_attempts": 2,
        "require_scf_converged": True,
    }
    campaign = {
        "schema_version": "2.0",
        "campaign_id": PACKAGE_ID,
        "system_id": "SURF_Gr5x5_clean_v01_LOCAL_TECHNICAL_ACCEPTANCE",
        "classification": [
            "LOCAL_SLURM_INTEGRATION",
            "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE",
            "YOLTLA_RUNTIME_NOT_VERIFIED",
            "ENERGY_INTERPRETATION_FORBIDDEN",
        ],
        "slurm": {
            "partition": "local",
            "account": account,
            "qos": "normal",
        },
        "resources": {
            "nodes": 1,
            "total_cpus": 2,
            "memory": "6000M",
            "walltime": "00:20:00",
            "max_parallel_steps": 1,
            "shutdown_margin_seconds": 60,
            "termination_grace_seconds": 15,
        },
        "runtime": {
            "module_commands": [],
            "siesta_executable": siesta_executable,
            "executable_arguments": [],
            "launcher": {
                "kind": "srun",
                "command": ["srun"],
                "arguments": ["--mpi=pmix"],
            },
            "exclusive": True,
            "environment": {
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
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
                "transfers": [
                    {
                        "from_task": "01_parent",
                        "artifact": "Gr5x5_clean_v01.DM",
                        "destination": "Gr5x5_clean_v01.DM",
                    }
                ],
                **common,
            },
        ],
    }
    campaign_path = source_root / "campaign.json"
    campaign_path.write_text(
        json.dumps(campaign, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return campaign_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--siesta", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()

    repository = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    campaign = materialize(
        repository,
        output,
        siesta_executable=args.siesta,
        account=args.account,
    )
    package_root = output / "package"
    package_root.mkdir()
    result = ControllerPackageBuilder(repository).build(campaign, package_root)
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
