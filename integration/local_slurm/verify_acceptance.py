#!/usr/bin/env python3
"""Verify and summarize evidence emitted by the local Slurm acceptance job."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from workload import PAYLOAD


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    parent = sorted(run_dir.glob("parent.rank-*.json"))
    restart = sorted(run_dir.glob("restart.rank-*.json"))
    artifact = run_dir / "parent.DM"
    issues: list[str] = []

    if len(parent) != 2:
        issues.append(f"PARENT_RANK_COUNT:{len(parent)}")
    if len(restart) != 2:
        issues.append(f"RESTART_RANK_COUNT:{len(restart)}")
    if not artifact.is_file() or artifact.read_bytes() != PAYLOAD:
        issues.append("PARENT_ARTIFACT_INVALID")
    if not (run_dir / "batch.completed").is_file():
        issues.append("BATCH_COMPLETION_MARKER_MISSING")

    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (*parent, *restart)
    ]
    if records and any(record.get("job_id") != args.job_id for record in records):
        issues.append("JOB_ID_MISMATCH")
    phases = {record.get("phase") for record in records}
    if records and phases != {"parent", "restart"}:
        issues.append("PHASE_SET_MISMATCH")

    status = (
        "LOCAL_SLURM_INTEGRATION_PASS"
        if not issues
        else "LOCAL_SLURM_INTEGRATION_FAIL"
    )
    summary = {
        "schema_version": "1.0",
        "status": status,
        "job_id": args.job_id,
        "scheduler_scope": "WSL2_SINGLE_NODE",
        "scientific_results_allowed": False,
        "yoltla_runtime_verified": False,
        "rank_records": len(records),
        "phases": sorted(str(item) for item in phases),
        "artifact_sha256": (
            hashlib.sha256(artifact.read_bytes()).hexdigest()
            if artifact.is_file()
            else None
        ),
        "issues": issues,
    }
    (run_dir / "acceptance_summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
