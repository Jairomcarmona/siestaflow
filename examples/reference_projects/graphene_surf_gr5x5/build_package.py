#!/usr/bin/env python3
"""Build the external M3B1 upload artifact without executing remote tools."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from qraft.real_smoke import RealSiestaSmokePackager, RealSmokeSpec
from qraft.slurm_renderer import SlurmProfile


PROJECT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = RealSmokeSpec(
        package_id="M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE",
        system_id="SURF_Gr5x5_clean_v01",
        geometry_path=PROJECT / "systems/SURF_Gr5x5_clean_v01.xyz",
        seed_fdf_path=PROJECT / "systems/SURF_Gr5x5_clean_v01.seed.fdf",
        pseudopotential_path=PROJECT / "pseudopotentials/C.psml",
        element="C",
        atomic_number=6,
        pseudopotential_provenance="PseudoDojo nc-sr-05 PBE stringent PSML; ONCVPSP metadata audited by T04A2/T06F",
        pseudopotential_license="CC-BY-4.0",
        redistribution_status="PERMITTED_WITH_ATTRIBUTION",
        profile=SlurmProfile(
            name="yoltla-m3b1-runtime-pending",
            verified_for_siesta=False,
            partition="q1h-20p",
            account="vini",
            qos="normal",
            nodes=1,
            ntasks=20,
            cpus_per_task=1,
            memory=None,
            walltime="00:10:00",
            signal="B:USR1@60",
            launcher_command=None,
        ),
    )
    try:
        plan = RealSiestaSmokePackager(spec).package(args.output)
    except (FileNotFoundError, PermissionError) as exc:
        print(f"C_PSEUDOPOTENTIAL_NOT_AVAILABLE_FOR_PACKAGING:{exc}")
        print("M3B1_PACKAGE_NOT_READY")
        return 2
    print(json.dumps(asdict(plan), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
