#!/usr/bin/env python3
"""Resolve an M10 scheduler selection from current login evidence only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

RESOURCE_REQUEST = {"nodes": 2, "ntasks": 64, "cpus_per_task": 1, "processes_per_node": 32, "walltime": "00:20:00"}

def _visible(data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = data.get("visible_partitions", [])
    return {str(item.get("name")): item for item in raw if isinstance(raw, list) and isinstance(item, Mapping) and item.get("name")}

def _placement(name: str, view: Mapping[str, Any]) -> dict[str, Any]:
    failures = []
    if not isinstance(view.get("nodes"), int) or view["nodes"] < 2: failures.append("VISIBLE_NODES_INSUFFICIENT")
    if not isinstance(view.get("cpus_per_node"), int) or view["cpus_per_node"] < 32: failures.append("CPUS_PER_NODE_INSUFFICIENT")
    if not isinstance(view.get("memory"), int) or view["memory"] <= 0: failures.append("MEMORY_NOT_OBSERVED")
    if failures: raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: {','.join(failures)}")
    return {"partition": name, "memory": f"{view['memory']}M", "memory_source": {"source_file": view.get("source_file", "sinfo.txt"), "source_line": view.get("source_line", 1), "observed_mb": view["memory"]}}

def _candidates(data: Mapping[str, Any], visible: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    associations = data.get("eligible_associations", [])
    if isinstance(associations, list):
        for association in associations:
            if not isinstance(association, Mapping): continue
            account, partition = association.get("account"), association.get("partition")
            if isinstance(account, str) and partition in visible:
                result.append({"account": account, "partition": str(partition), "qos": association.get("qos"), "association_scope": association.get("scope", "CURRENT_USER_EVIDENCE"), "source_files": [association.get("source_file") or association.get("source") or "current_user_scheduler_evidence.txt"]})
    defaults = data.get("scheduler_defaults", {})
    if isinstance(defaults, Mapping) and defaults.get("account_omission_supported") is True:
        for name, view in visible.items():
            if view.get("default") is True:
                result.append({"account": None, "partition": name, "qos": None, "association_scope": "SAFE_SLURM_DEFAULT_OMISSION", "source_files": [str(defaults.get("source_file", "scheduler_defaults"))]})
    unique: dict[tuple[object, object, object], dict[str, Any]] = {}
    for item in result: unique[(item["account"], item["partition"], item.get("qos"))] = item
    return list(unique.values())

def resolve(summary_path: Path, *, account: str | None = None, partition: str | None = None, qos: str | None = None) -> dict[str, Any]:
    if (account is None) != (partition is None): raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: --account and --partition must be supplied together")
    try: data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error: raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: cannot read login evidence: {summary_path}") from error
    if not isinstance(data, Mapping): raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: login evidence must be an object")
    visible = _visible(data); candidates = _candidates(data, visible)
    if account is not None:
        candidates = [item for item in candidates if item["account"] == account and item["partition"] == partition and (qos is None or item.get("qos") == qos)]
        if not candidates: raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: requested scheduler selection is not supported by current evidence")
    if len(candidates) != 1:
        status = "SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS" if len(candidates) > 1 else "SCHEDULER_PROBE_NO_EVIDENCE_BOUND_CANDIDATE"
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: {status}")
    selected = candidates[0]; placement = _placement(selected["partition"], visible[selected["partition"]])
    defaults = data.get("scheduler_defaults", {}) if isinstance(data.get("scheduler_defaults", {}), Mapping) else {}
    chosen_qos = qos if qos is not None else selected.get("qos")
    if selected["account"] is None and defaults.get("account_omission_supported") is not True: raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: account omission is not justified")
    if chosen_qos is None and selected["account"] is None and defaults.get("qos_omission_supported") is not True: raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: QoS omission is not justified")
    return {"account": selected["account"], "partition": selected["partition"], "qos": chosen_qos, **placement, **RESOURCE_REQUEST, "association_scope": selected["association_scope"], "selection_policy": "UNIQUE_CURRENT_CLUSTER_EVIDENCE", "candidate_partitions": sorted({str(item["partition"]) for item in candidates}), "source_files": sorted(set(str(x) for x in selected["source_files"] + [placement["memory_source"]["source_file"]])), "evidence_status_by_field": {"account": "OMITTED_WITH_SCHEDULER_DEFAULT_EVIDENCE" if selected["account"] is None else "OBSERVED", "partition": "VERIFIED_BY_CROSS_SOURCE", "qos": "OMITTED_WITH_SCHEDULER_DEFAULT_EVIDENCE" if chosen_qos is None and selected["account"] is None else ("MISSING" if chosen_qos is None else "OBSERVED"), "memory": "OBSERVED", "resource_shape": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE"}, "resource_shape_status": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE"}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-evidence", required=True, type=Path); parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--account"); parser.add_argument("--partition"); parser.add_argument("--qos")
    args = parser.parse_args()
    if args.output.exists(): raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: refusing to overwrite selection: {args.output}")
    result = resolve(args.login_evidence, account=args.account, partition=args.partition, qos=args.qos)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0

if __name__ == "__main__": raise SystemExit(main())
