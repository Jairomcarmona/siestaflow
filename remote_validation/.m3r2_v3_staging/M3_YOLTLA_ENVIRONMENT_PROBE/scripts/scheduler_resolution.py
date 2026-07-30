"""Structured, evidence-bound SLURM association and partition resolution.

The module is deliberately standard-library-only so the same source can be
shipped in the remote probe package and imported by its generated scripts.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class AssociationScope(str, Enum):
    EXPLICIT_PARTITION_ASSOCIATION = "EXPLICIT_PARTITION_ASSOCIATION"
    ACCOUNT_WIDE_ASSOCIATION = "ACCOUNT_WIDE_ASSOCIATION"
    QOS_ONLY_ASSOCIATION = "QOS_ONLY_ASSOCIATION"
    INCOMPLETE_ASSOCIATION = "INCOMPLETE_ASSOCIATION"
    CONTRADICTORY_ASSOCIATION = "CONTRADICTORY_ASSOCIATION"


@dataclass(frozen=True)
class SchedulerAssociation:
    account: str | None
    partition: str | None
    qos: str | None
    scope: str
    source_file: str
    source_line: int
    evidence_status: str
    observed_at: str | None


@dataclass(frozen=True)
class VisiblePartition:
    name: str
    availability: str | None
    time_limit: str | None
    nodes: int | None
    cpus_per_node: int | None
    memory: int | None
    default: bool
    source_file: str
    source_line: int


@dataclass(frozen=True)
class PartitionPolicy:
    name: str
    allow_accounts: dict[str, Any]
    allow_qos: dict[str, Any]
    default: bool
    state: str | None
    min_nodes: int | None
    max_nodes: int | None
    max_time: str | None
    source_file: str
    source_line: int


@dataclass(frozen=True)
class ResourceRequest:
    nodes: int = 1
    ntasks: int = 1
    cpus_per_task: int = 1
    walltime: str = "00:02:00"


def _restriction(value: str | None) -> dict[str, Any]:
    if value is None:
        return {"kind": "MISSING", "values": []}
    value = value.strip()
    if not value:
        return {"kind": "MISSING", "values": []}
    if value.upper() == "ALL":
        return {"kind": "ALL", "values": []}
    if value.upper() == "N/A":
        return {"kind": "N/A", "values": []}
    return {"kind": "EXPLICIT_LIST", "values": [x for x in value.split(",") if x]}


def parse_sacctmgr_associations(text: str, source_file: str = "sacctmgr_assoc.txt", observed_at: str | None = None) -> tuple[list[SchedulerAssociation], list[dict[str, Any]]]:
    associations: list[SchedulerAssociation] = []
    diagnostics: list[dict[str, Any]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        parts = [x.strip() for x in raw.split("|")]
        if len(parts) != 3:
            diagnostics.append({"code": "SACCTMGR_ASSOCIATION_FIELD_COUNT_INVALID", "source_file": source_file, "source_line": number, "raw": raw})
            padded = (parts + [""] * 3)[:3]
            associations.append(SchedulerAssociation(padded[0] or None, padded[1] or None, padded[2] or None, AssociationScope.CONTRADICTORY_ASSOCIATION.value, source_file, number, "CONTRADICTORY", observed_at))
            continue
        account, partition, qos = (x or None for x in parts)
        if not account:
            scope = AssociationScope.QOS_ONLY_ASSOCIATION if qos and not partition else AssociationScope.CONTRADICTORY_ASSOCIATION if partition else AssociationScope.INCOMPLETE_ASSOCIATION
            status = "CONTRADICTORY" if scope is AssociationScope.CONTRADICTORY_ASSOCIATION else "MISSING"
            associations.append(SchedulerAssociation(None, partition, qos, scope.value, source_file, number, status, observed_at))
            diagnostics.append({"code": "SACCTMGR_ASSOCIATION_ACCOUNT_REQUIRED", "source_file": source_file, "source_line": number, "raw": raw})
            continue
        scope = AssociationScope.EXPLICIT_PARTITION_ASSOCIATION if partition else AssociationScope.ACCOUNT_WIDE_ASSOCIATION
        associations.append(SchedulerAssociation(account, partition, qos, scope.value, source_file, number, "OBSERVED", observed_at))
    return associations, diagnostics


def parse_sinfo_partitions(text: str, source_file: str = "sinfo.txt") -> tuple[list[VisiblePartition], list[dict[str, Any]]]:
    rows: list[VisiblePartition] = []
    diagnostics: list[dict[str, Any]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        parts = [x.strip() for x in raw.split("|")]
        if len(parts) < 6 or not parts[0]:
            diagnostics.append({"code": "SINFO_PARTITION_ROW_INVALID", "source_file": source_file, "source_line": number, "raw": raw})
            continue
        marked = parts[0].endswith("*")
        name = parts[0][:-1] if marked else parts[0]
        def integer(value: str) -> int | None:
            return int(value) if value.isdigit() else None
        rows.append(VisiblePartition(name, parts[1] or None, parts[2] or None, integer(parts[3]), integer(parts[4]), integer(parts[5]), marked, source_file, number))
    return rows, diagnostics


def parse_scontrol_partitions(text: str, source_file: str = "scontrol_partitions.txt") -> tuple[list[PartitionPolicy], list[dict[str, Any]]]:
    rows: list[PartitionPolicy] = []
    diagnostics: list[dict[str, Any]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", raw))
        name = fields.get("PartitionName")
        if not name:
            diagnostics.append({"code": "SCONTROL_PARTITION_NAME_MISSING", "source_file": source_file, "source_line": number, "raw": raw})
            continue
        def integer(key: str) -> int | None:
            value = fields.get(key, "")
            return int(value) if value.isdigit() else None
        rows.append(PartitionPolicy(name, _restriction(fields.get("AllowAccounts")), _restriction(fields.get("AllowQos")), fields.get("Default", "NO").upper() == "YES", fields.get("State"), integer("MinNodes"), integer("MaxNodes"), fields.get("MaxTime"), source_file, number))
    return rows, diagnostics


def _seconds(value: str | None) -> int | None:
    if not value or value.upper() in {"UNLIMITED", "INFINITE"}:
        return None
    match = re.fullmatch(r"(?:(\d+)-)?(\d+):(\d+):(\d+)", value)
    if not match:
        return None
    days, hours, minutes, seconds = (int(x or 0) for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _allows(restriction: dict[str, Any], value: str | None, *, observed: bool) -> bool:
    if not observed:
        return False
    kind = restriction["kind"]
    if kind == "ALL":
        return True
    if kind == "EXPLICIT_LIST":
        return value in restriction["values"] if value else False
    return False


def resolve_scheduler_candidates(associations: Iterable[SchedulerAssociation], visible_partitions: Iterable[VisiblePartition], partition_policies: Iterable[PartitionPolicy], resource_request: ResourceRequest = ResourceRequest()) -> dict[str, Any]:
    visible = {x.name: x for x in visible_partitions}
    policies = {x.name: x for x in partition_policies}
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for association in associations:
        if association.evidence_status != "OBSERVED" or not association.account:
            continue
        names = [association.partition] if association.partition else list(visible)
        for name in names:
            view, policy = visible.get(name), policies.get(name)
            reasons: list[str] = []
            if not view:
                reasons.append("PARTITION_NOT_VISIBLE")
            if not policy:
                reasons.append("PARTITION_POLICY_MISSING")
            if view and policy:
                if (view.availability or "").lower() not in {"up", "active", "available"}: reasons.append("PARTITION_NOT_AVAILABLE")
                if (policy.state or "").upper() != "UP": reasons.append("PARTITION_NOT_UP")
                if not _allows(policy.allow_accounts, association.account, observed=True): reasons.append("ACCOUNT_NOT_ALLOWED")
                if association.qos and not _allows(policy.allow_qos, association.qos, observed=True): reasons.append("QOS_NOT_ALLOWED")
                if policy.min_nodes is None or resource_request.nodes < policy.min_nodes: reasons.append("MIN_NODES_INCOMPATIBLE")
                if policy.max_nodes is None or resource_request.nodes > policy.max_nodes: reasons.append("MAX_NODES_INCOMPATIBLE")
                requested, maximum = _seconds(resource_request.walltime), _seconds(policy.max_time)
                if requested is None or (maximum is not None and requested > maximum): reasons.append("WALLTIME_INCOMPATIBLE")
            item = {"account": association.account, "partition": name, "qos": association.qos, "association_scope": association.scope, "default": bool(view and policy and (view.default or policy.default)), "source_files": sorted(set(filter(None, [association.source_file, view.source_file if view else None, policy.source_file if policy else None]))), "rejection_reasons": reasons}
            (rejected if reasons else candidates).append(item)
    defaults = [x for x in candidates if x["default"]]
    if len(defaults) == 1:
        status, selected, policy_name = "DEFAULT_PARTITION_RESOLVED_FROM_REAL_EVIDENCE", defaults[0], "UNIQUE_COMPATIBLE_DEFAULT_PARTITION"
    elif len(defaults) > 1:
        status, selected, policy_name = "SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS", None, None
    elif candidates:
        status, selected, policy_name = "SCHEDULER_PROBE_REQUIRES_HUMAN_SELECTION", None, None
    else:
        status, selected, policy_name = "SCHEDULER_PROBE_BLOCKED_NO_COMPATIBLE_PARTITION", None, None
    return {"status": status, "candidates": candidates, "rejected": rejected, "selected": selected, "selection_policy": policy_name, "resource_request": asdict(resource_request)}


def apply_human_selection(resolution: dict[str, Any], account: str, partition: str, qos: str | None = None) -> dict[str, Any]:
    matches = [x for x in resolution["candidates"] if x["account"] == account and x["partition"] == partition and x.get("qos") == qos]
    if len(matches) != 1:
        raise ValueError("USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE")
    result = dict(resolution)
    result.update(status="HUMAN_SELECTION_SUPPORTED_BY_EVIDENCE", selected=matches[0], selection_policy="HUMAN_SELECTION_EVIDENCE_BOUND")
    return result


def model_dicts(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [asdict(value) for value in values]


def standalone_source() -> str:
    return Path(__file__).read_text(encoding="utf-8")
