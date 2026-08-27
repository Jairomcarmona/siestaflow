#!/usr/bin/env python3
"""Resolve an M10 scheduler selection from current login evidence only."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping


RESOURCE_REQUEST = {"nodes": 2, "ntasks": 64, "cpus_per_task": 1, "processes_per_node": 32, "walltime": "00:20:00"}


def _mapping_by_name(data: Mapping[str, Any], field: str) -> dict[str, Mapping[str, Any]]:
    raw = data.get(field, [])
    if not isinstance(raw, list):
        return {}
    return {str(item["name"]): item for item in raw if isinstance(item, Mapping) and item.get("name")}


def _slurm_seconds(value: object) -> int | None:
    """Support the small current-evidence time grammar needed for MaxTime."""
    if not isinstance(value, str) or value.upper() in {"UNLIMITED", "INFINITE"}:
        return None if isinstance(value, str) else -1
    matched = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2})(?::(\d{2}))?", value)
    if not matched:
        return -1
    days, first, second, third = matched.groups()
    if third is None:
        hours, minutes, seconds = 0, int(first), int(second)
    else:
        hours, minutes, seconds = int(first), int(second), int(third)
    return (int(days or 0) * 86400) + (hours * 3600) + (minutes * 60) + seconds


def _policy_allows(policy: Mapping[str, Any], field: str, value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    allowed = policy.get(field)
    if not isinstance(allowed, Mapping):
        return False
    if allowed.get("kind") == "ALL":
        return True
    values = allowed.get("values")
    return isinstance(values, list) and value in values


def _placement(name: str, view: Mapping[str, Any], policy: Mapping[str, Any], account: object, qos: object) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(view.get("nodes"), int) or view["nodes"] < RESOURCE_REQUEST["nodes"]:
        failures.append("VISIBLE_NODES_INSUFFICIENT")
    if not isinstance(view.get("cpus_per_node"), int) or view["cpus_per_node"] < RESOURCE_REQUEST["processes_per_node"]:
        failures.append("CPUS_PER_NODE_INSUFFICIENT")
    if not isinstance(view.get("memory"), int) or view["memory"] <= 0:
        failures.append("MEMORY_NOT_OBSERVED")
    if str(view.get("availability", "")).lower() != "up":
        failures.append("VISIBLE_PARTITION_NOT_UP")
    if str(policy.get("state", "")).upper() != "UP":
        failures.append("PARTITION_POLICY_NOT_UP")
    min_nodes, max_nodes = policy.get("min_nodes"), policy.get("max_nodes")
    if not isinstance(min_nodes, int) or RESOURCE_REQUEST["nodes"] < min_nodes:
        failures.append("MIN_NODES_VIOLATED")
    if max_nodes is not None and (not isinstance(max_nodes, int) or RESOURCE_REQUEST["nodes"] > max_nodes):
        failures.append("MAX_NODES_VIOLATED")
    max_seconds = _slurm_seconds(policy.get("max_time"))
    requested_seconds = _slurm_seconds(RESOURCE_REQUEST["walltime"])
    if max_seconds is None:
        pass
    elif max_seconds < 0 or requested_seconds < 0 or requested_seconds > max_seconds:
        failures.append("MAX_TIME_VIOLATED")
    if not _policy_allows(policy, "allow_accounts", account):
        failures.append("ACCOUNT_NOT_ALLOWED_BY_PARTITION")
    if qos is not None and not _policy_allows(policy, "allow_qos", qos):
        failures.append("QOS_NOT_ALLOWED_BY_PARTITION")
    if failures:
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: {','.join(failures)}")
    return {
        "partition": name, "memory": f"{view['memory']}M",
        "memory_source": {"source_file": view.get("source_file", "sinfo.txt"), "source_line": view.get("source_line", 1), "observed_mb": view["memory"]},
        "policy_source": {"source_file": policy.get("source_file", "scontrol_partitions.txt"), "source_line": policy.get("source_line", 1)},
    }


def _association_candidates(data: Mapping[str, Any], visible: Mapping[str, Mapping[str, Any]], policies: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    associations = data.get("eligible_associations", [])
    if not isinstance(associations, list):
        associations = []
    for association in associations:
        if not isinstance(association, Mapping):
            continue
        account, partition, qos = association.get("account"), association.get("partition"), association.get("qos")
        if not isinstance(account, str):
            continue
        scope = str(association.get("scope", "CURRENT_USER_EVIDENCE"))
        names = visible if partition is None and scope == "GLOBAL_USER_ASSOCIATION" else {str(partition): visible[str(partition)]} if partition in visible else {}
        for name in names:
            policy = policies.get(name)
            if policy is None:
                continue
            result.append({
                "account": account, "partition": name, "qos": qos, "association_scope": scope,
                "source_files": [str(association.get("source_file") or association.get("source") or "current_user_scheduler_evidence.txt")],
            })
    return result


def _default_candidates(data: Mapping[str, Any], visible: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    defaults = data.get("scheduler_defaults", {})
    if not isinstance(defaults, Mapping) or defaults.get("account_omission_supported") is not True:
        return []
    return [{
        "account": None, "partition": name, "qos": None, "association_scope": "SAFE_SLURM_DEFAULT_OMISSION",
        "source_files": [str(defaults.get("source_file", "scheduler_defaults"))],
    } for name, view in visible.items() if view.get("default") is True]


def _candidates(data: Mapping[str, Any], visible: Mapping[str, Mapping[str, Any]], policies: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = _association_candidates(data, visible, policies) + _default_candidates(data, visible)
    unique: dict[tuple[object, object, object], dict[str, Any]] = {}
    for item in result:
        unique[(item["account"], item["partition"], item.get("qos"))] = item
    return list(unique.values())


def resolve(summary_path: Path, *, account: str | None = None, partition: str | None = None, qos: str | None = None) -> dict[str, Any]:
    if (account is None) != (partition is None):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: --account and --partition must be supplied together")
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: cannot read login evidence: {summary_path}") from error
    if not isinstance(data, Mapping):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: login evidence must be an object")
    visible = _mapping_by_name(data, "visible_partitions")
    policies = _mapping_by_name(data, "partition_policies")
    candidates = _candidates(data, visible, policies)
    if account is not None:
        candidates = [item for item in candidates if item["account"] == account and item["partition"] == partition and (qos is None or item.get("qos") == qos)]
        if not candidates:
            raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: requested scheduler selection is not supported by current evidence")
    accepted: list[tuple[dict[str, Any], dict[str, Any]]] = []
    failures: list[str] = []
    for item in candidates:
        chosen_qos = qos if qos is not None else item.get("qos")
        try:
            placement = _placement(item["partition"], visible[item["partition"]], policies[item["partition"]], item["account"], chosen_qos)
        except ValueError as error:
            failures.append(str(error))
            continue
        accepted.append((item, placement))
    if len(accepted) != 1:
        if len(accepted) > 1:
            raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS")
        if failures:
            raise ValueError(failures[0])
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: SCHEDULER_PROBE_NO_EVIDENCE_BOUND_CANDIDATE")
    selected, placement = accepted[0]
    defaults = data.get("scheduler_defaults", {}) if isinstance(data.get("scheduler_defaults"), Mapping) else {}
    chosen_qos = qos if qos is not None else selected.get("qos")
    if selected["account"] is None and defaults.get("account_omission_supported") is not True:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: account omission is not justified")
    if chosen_qos is None and selected["account"] is None and defaults.get("qos_omission_supported") is not True:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: QoS omission is not justified")
    source_files = [*selected["source_files"], placement["memory_source"]["source_file"], placement["policy_source"]["source_file"]]
    return {
        "account": selected["account"], "partition": selected["partition"], "qos": chosen_qos, **placement, **RESOURCE_REQUEST,
        "association_scope": selected["association_scope"], "selection_policy": "UNIQUE_CURRENT_CLUSTER_EVIDENCE",
        "candidate_partitions": sorted(item[0]["partition"] for item in accepted), "source_files": sorted(set(str(item) for item in source_files)),
        "evidence_status_by_field": {
            "account": "OMITTED_WITH_SCHEDULER_DEFAULT_EVIDENCE" if selected["account"] is None else "OBSERVED",
            "partition": "VERIFIED_BY_CROSS_SOURCE", "qos": "OMITTED_WITH_SCHEDULER_DEFAULT_EVIDENCE" if chosen_qos is None and selected["account"] is None else ("MISSING" if chosen_qos is None else "OBSERVED"),
            "memory": "OBSERVED", "resource_shape": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE",
        }, "resource_shape_status": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE",
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
