#!/usr/bin/env python3
"""Tiny deterministic workload for the real local Slurm acceptance test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


PAYLOAD = b"SIESTAFLOW_LOCAL_SLURM_PARENT_DM\n"


def _write_json(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("parent", "restart"))
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    rank = int(os.environ["SLURM_PROCID"])
    world_size = int(os.environ["SLURM_NTASKS"])
    job_id = os.environ["SLURM_JOB_ID"]
    step_id = os.environ["SLURM_STEP_ID"]
    artifact = run_dir / "parent.DM"

    if args.phase == "parent" and rank == 0:
        artifact.write_bytes(PAYLOAD)
    if args.phase == "restart":
        if not artifact.is_file() or artifact.read_bytes() != PAYLOAD:
            raise SystemExit("PARENT_ARTIFACT_TRANSFER_FAILED")

    _write_json(
        run_dir / f"{args.phase}.rank-{rank:04d}.json",
        {
            "job_id": job_id,
            "step_id": step_id,
            "phase": args.phase,
            "rank": rank,
            "world_size": world_size,
            "artifact_sha256": (
                hashlib.sha256(artifact.read_bytes()).hexdigest()
                if artifact.is_file()
                else None
            ),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
