#!/usr/bin/env python3
"""Resolve the evidence-bound M10 scheduler profile from an M3 login probe."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


RESOURCE_REQUEST = {
    "nodes": 2,
    "ntasks": 64,
    "cpus_per_task": 1,
    "processes_per_node": 32,
    "walltime": "00:20:00",
}


def _scheduler_resolution_path() -> Path:
    """Locate the unmodified M3 resolver locally or in a copied discovery bundle."""

    here = Path(__file__).resolve().parent
    candidates = (
        here / "scripts" / "scheduler_resolution.py",
        here / "scheduler_resolution.py",
        here.parent / "remote_validation" / "M3_YOLTLA_ENVIRONMENT_PROBE" / "scripts" / "scheduler_resolution.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("M10_REMOTE_PROFILE_UNRESOLVED: scheduler resolution authority missing")


def _resolver() -> ModuleType:
    path = _scheduler_resolution_path()
    spec = importlib.util.spec_from_file_location("qraft_m3_scheduler_resolution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("M10_REMOTE_PROFILE_UNRESOLVED: scheduler resolution authority unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _models(summary: dict[str, Any], resolver: ModuleType) -> tuple[list[Any], list[Any], list[Any]]:
    try:
        associations = [resolver.SchedulerAssociation(**value) for value in summary["eligible_associations"]]
        visible = [resolver.VisiblePartition(**value) for value in summary["visible_partitions"]]
        policies = [resolver.PartitionPolicy(**value) for value in summary["partition_policies"]]
    except (KeyError, TypeError) as error:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: invalid login probe summary") from error
    return associations, visible, policies


def _placement(selection: dict[str, Any], visible: list[Any]) -> Any:
    view = next((item for item in visible if item.name == selection["partition"]), None)
    problems: list[str] = []
    if view is None:
        problems.append("SELECTED_PARTITION_NOT_VISIBLE")
    else:
        if view.nodes is None or view.nodes < RESOURCE_REQUEST["nodes"]:
            problems.append("VISIBLE_NODES_INSUFFICIENT")
        if view.cpus_per_node is None or view.cpus_per_node < RESOURCE_REQUEST["processes_per_node"]:
            problems.append("CPUS_PER_NODE_INSUFFICIENT")
        if view.memory is None:
            problems.append("MEMORY_NOT_OBSERVED")
    if problems:
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: {','.join(problems)}")
    return view


def resolve(summary_path: Path, *, account: str | None = None, partition: str | None = None, qos: str | None = None) -> dict[str, Any]:
    if (account is None) != (partition is None):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: --account and --partition must be supplied together")
    try:
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: cannot read login evidence: {summary_path}") from error
    if not isinstance(raw, dict):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: login evidence must be an object")

    authority = _resolver()
    associations, visible, policies = _models(raw, authority)
    request = authority.ResourceRequest(
        nodes=RESOURCE_REQUEST["nodes"],
        ntasks=RESOURCE_REQUEST["ntasks"],
        cpus_per_task=RESOURCE_REQUEST["cpus_per_task"],
        walltime=RESOURCE_REQUEST["walltime"],
    )
    resolution = authority.resolve_scheduler_candidates(associations, visible, policies, request)
    if account is not None:
        resolution = authority.apply_human_selection(resolution, account, partition, qos)
    selected = resolution.get("selected")
    if not isinstance(selected, dict):
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: "
            f"{resolution.get('status', 'SCHEDULER_PROBE_REQUIRES_HUMAN_SELECTION')}"
        )
    view = _placement(selected, visible)
    source_files = sorted(set(selected["source_files"] + [view.source_file]))
    return {
        "account": selected["account"],
        "partition": selected["partition"],
        "qos": selected.get("qos"),
        "memory": f"{view.memory}M",
        **RESOURCE_REQUEST,
        "association_scope": selected["association_scope"],
        "selection_policy": resolution["selection_policy"],
        "candidate_partitions": sorted({item["partition"] for item in resolution["candidates"]}),
        "source_files": source_files,
        "memory_source": {"source_file": view.source_file, "source_line": view.source_line, "observed_mb": view.memory},
        "evidence_status_by_field": {
            "account": "OBSERVED",
            "partition": "VERIFIED_BY_CROSS_SOURCE",
            "qos": "MISSING" if selected.get("qos") is None else "OBSERVED",
            "memory": "OBSERVED",
            "resource_shape": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE",
        },
        "resource_shape_status": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--account")
    parser.add_argument("--partition")
    parser.add_argument("--qos")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: refusing to overwrite selection: {args.output}")
    result = resolve(args.login_evidence, account=args.account, partition=args.partition, qos=args.qos)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
