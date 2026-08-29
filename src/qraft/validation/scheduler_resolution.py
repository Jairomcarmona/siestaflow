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
    nodes: int | None = 1
    ntasks: int = 1
    cpus_per_task: int = 1
    walltime: str = "00:02:00"
    account: str | None = None
    qos: str | None = None


@dataclass(frozen=True)
class NodeCapability:
    """Node-level Slurm capacity evidence for one partition membership."""

    node: str
    partition: str
    cpus_per_node: int | None
    memory_mb: int | None
    state: str | None
    source_file: str
    source_line: int


@dataclass(frozen=True)
class DerivedPlacement:
    """Single validated placement authority consumed by execution layers."""

    partition: str
    nodes: int
    tasks_per_node: int
    ntasks: int
    cpus_per_task: int
    safe_cpus_per_node: int
    total_allocated_cpus: int
    walltime: str
    policy: str = "MAXIMUM_LEGAL_PLACEMENT"

    def __post_init__(self) -> None:
        for field in (
            "nodes",
            "tasks_per_node",
            "ntasks",
            "cpus_per_task",
            "safe_cpus_per_node",
            "total_allocated_cpus",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"DerivedPlacement {field} must be positive")
        if not self.partition.strip() or not self.walltime.strip():
            raise ValueError("DerivedPlacement requires partition and walltime")
        if self.ntasks != self.nodes * self.tasks_per_node:
            raise ValueError("DerivedPlacement ntasks mismatch")
        if self.tasks_per_node * self.cpus_per_task > self.safe_cpus_per_node:
            raise ValueError("DerivedPlacement CPU overcommit")
        if self.total_allocated_cpus != self.nodes * self.safe_cpus_per_node:
            raise ValueError("DerivedPlacement allocated CPU mismatch")

    @property
    def processes_per_node(self) -> int:
        return self.tasks_per_node

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def parse_sinfo_node_capabilities(
    text: str,
    source_file: str = "sinfo_nodes.txt",
) -> tuple[list[NodeCapability], list[dict[str, Any]]]:
    """Parse ``sinfo -N`` output formatted as ``%N|%P|%c|%m|%t``."""

    rows: list[NodeCapability] = []
    diagnostics: list[dict[str, Any]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        parts = [item.strip() for item in raw.split("|")]
        if len(parts) != 5 or not parts[0] or not parts[1]:
            diagnostics.append({
                "code": "SINFO_NODE_ROW_INVALID",
                "source_file": source_file,
                "source_line": number,
                "raw": raw,
            })
            continue

        def integer(value: str) -> int | None:
            return int(value) if value.isdigit() else None

        for partition in parts[1].split(","):
            name = partition.strip().removesuffix("*")
            if not name:
                continue
            rows.append(NodeCapability(
                node=parts[0],
                partition=name,
                cpus_per_node=integer(parts[2]),
                memory_mb=integer(parts[3]),
                state=parts[4] or None,
                source_file=source_file,
                source_line=number,
            ))
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


def _association_qos_allows(observed_qos: str | None, requested_qos: str | None) -> bool:
    if requested_qos is None:
        return observed_qos is None
    if observed_qos is None:
        return False
    return requested_qos in {
        item.strip() for item in observed_qos.split(",") if item.strip()
    }


def derive_fixed_partition_placement(
    visible: VisiblePartition,
    policy: PartitionPolicy,
    *,
    cpus_per_task: int = 1,
    walltime: str = "00:20:00",
) -> dict[str, Any]:
    """Derive the maximum legal MPI placement for a fixed-size partition.

    Capacity remains evidence, while the returned placement is explicitly
    marked as derived policy.  A node range is not guessed: callers must
    provide a separate, evidence-bound node-selection policy for that case.
    """

    failures: list[str] = []
    if visible.name != policy.name:
        failures.append("PARTITION_EVIDENCE_MISMATCH")
    if (visible.availability or "").casefold() not in {
        "up",
        "active",
        "available",
    }:
        failures.append("PARTITION_NOT_AVAILABLE")
    if (policy.state or "").upper() != "UP":
        failures.append("PARTITION_NOT_UP")
    if (
        isinstance(cpus_per_task, bool)
        or not isinstance(cpus_per_task, int)
        or cpus_per_task <= 0
    ):
        failures.append("CPUS_PER_TASK_INVALID")
    if (
        not isinstance(policy.min_nodes, int)
        or not isinstance(policy.max_nodes, int)
        or policy.min_nodes <= 0
        or policy.max_nodes <= 0
    ):
        failures.append("NODE_LIMITS_NOT_OBSERVED")
    elif policy.min_nodes != policy.max_nodes:
        failures.append("NODE_RANGE_AMBIGUOUS")
    nodes = policy.min_nodes if policy.min_nodes == policy.max_nodes else None
    if (
        nodes is not None
        and (not isinstance(visible.nodes, int) or visible.nodes < nodes)
    ):
        failures.append("VISIBLE_NODES_INSUFFICIENT")
    if not isinstance(visible.cpus_per_node, int) or visible.cpus_per_node <= 0:
        failures.append("CPUS_PER_NODE_NOT_OBSERVED")
    if not isinstance(visible.memory, int) or visible.memory <= 0:
        failures.append("MEMORY_NOT_OBSERVED")
    requested_seconds = _seconds(walltime)
    maximum_seconds = _seconds(policy.max_time)
    if requested_seconds is None or requested_seconds <= 0:
        failures.append("WALLTIME_INVALID")
    if not isinstance(policy.max_time, str) or not policy.max_time.strip():
        failures.append("MAX_TIME_NOT_OBSERVED")
    elif (
        maximum_seconds is None
        and policy.max_time.upper() not in {"UNLIMITED", "INFINITE"}
    ):
        failures.append("MAX_TIME_INVALID")
    elif maximum_seconds is not None and requested_seconds is not None and requested_seconds > maximum_seconds:
        failures.append("MAX_TIME_VIOLATED")

    processes_per_node = (
        visible.cpus_per_node // cpus_per_task
        if isinstance(visible.cpus_per_node, int)
        and isinstance(cpus_per_task, int)
        and not isinstance(cpus_per_task, bool)
        and cpus_per_task > 0
        else 0
    )
    if processes_per_node <= 0:
        failures.append("CPU_OVERCOMMIT")
    elif processes_per_node * cpus_per_task > visible.cpus_per_node:
        failures.append("CPU_OVERCOMMIT")
    if failures:
        raise ValueError("SCHEDULER_PLACEMENT_UNRESOLVED: " + ",".join(failures))

    assert nodes is not None
    assert visible.cpus_per_node is not None
    assert visible.memory is not None
    return {
        "capacity_evidence": {
            "partition": visible.name,
            "visible_nodes": visible.nodes,
            "cpus_per_node": visible.cpus_per_node,
            "memory_mb": visible.memory,
            "min_nodes": policy.min_nodes,
            "max_nodes": policy.max_nodes,
            "max_time": policy.max_time,
            "availability": visible.availability,
            "state": policy.state,
            "source_files": sorted({visible.source_file, policy.source_file}),
            "sources": {
                "visible_partition": {
                    "source_file": visible.source_file,
                    "source_line": visible.source_line,
                },
                "partition_policy": {
                    "source_file": policy.source_file,
                    "source_line": policy.source_line,
                },
            },
        },
        "derived_placement": {
            "policy": "MAXIMUM_LEGAL_PLACEMENT_FIXED_PARTITION",
            "nodes": nodes,
            "ntasks": nodes * processes_per_node,
            "cpus_per_task": cpus_per_task,
            "processes_per_node": processes_per_node,
            "total_cpus": nodes * visible.cpus_per_node,
            "walltime": walltime,
        },
    }


def derive_partition_placement(
    visible: VisiblePartition,
    policy: PartitionPolicy,
    node_capabilities: Iterable[NodeCapability],
    association: SchedulerAssociation,
    resource_request: ResourceRequest,
) -> DerivedPlacement:
    """Derive placement from live policy, node evidence and human selection.

    Fixed-size partitions derive their node count from policy.  Ranged
    partitions require ``resource_request.nodes`` to be explicitly supplied.
    The node-level evidence must cover every node visible to the partition and
    prove homogeneous CPU capacity; otherwise placement fails closed.
    """

    failures: list[str] = []
    if visible.name != policy.name:
        failures.append("PARTITION_EVIDENCE_MISMATCH")
    if (visible.availability or "").casefold() not in {
        "up",
        "active",
        "available",
    }:
        failures.append("PARTITION_NOT_AVAILABLE")
    if (policy.state or "").upper() != "UP":
        failures.append("PARTITION_NOT_UP")
    if association.evidence_status != "OBSERVED":
        failures.append("USER_ASSOCIATION_NOT_OBSERVED")
    if not resource_request.account or association.account != resource_request.account:
        failures.append("ACCOUNT_ASSOCIATION_MISMATCH")
    if association.partition not in {None, visible.name}:
        failures.append("PARTITION_ASSOCIATION_MISMATCH")
    if not _association_qos_allows(association.qos, resource_request.qos):
        failures.append("QOS_ASSOCIATION_MISMATCH")
    if not _allows(policy.allow_accounts, resource_request.account, observed=True):
        failures.append("ACCOUNT_NOT_ALLOWED")
    if resource_request.qos is not None and not _allows(
        policy.allow_qos, resource_request.qos, observed=True
    ):
        failures.append("QOS_NOT_ALLOWED")

    if (
        not isinstance(policy.min_nodes, int)
        or not isinstance(policy.max_nodes, int)
        or policy.min_nodes <= 0
        or policy.max_nodes <= 0
        or policy.min_nodes > policy.max_nodes
    ):
        failures.append("NODE_LIMITS_NOT_OBSERVED")
        nodes: int | None = None
    elif policy.min_nodes == policy.max_nodes:
        nodes = policy.min_nodes
        if resource_request.nodes not in {None, nodes}:
            failures.append("FIXED_PARTITION_NODE_MISMATCH")
    else:
        nodes = resource_request.nodes
        if nodes is None:
            failures.append("MANUAL_NODE_SELECTION_REQUIRED")
        elif (
            isinstance(nodes, bool)
            or not isinstance(nodes, int)
            or nodes < policy.min_nodes
            or nodes > policy.max_nodes
        ):
            failures.append("SELECTED_NODES_OUTSIDE_POLICY")

    if (
        isinstance(resource_request.cpus_per_task, bool)
        or not isinstance(resource_request.cpus_per_task, int)
        or resource_request.cpus_per_task <= 0
    ):
        failures.append("CPUS_PER_TASK_INVALID")

    requested_seconds = _seconds(resource_request.walltime)
    maximum_seconds = _seconds(policy.max_time)
    if requested_seconds is None or requested_seconds <= 0:
        failures.append("WALLTIME_INVALID")
    if not isinstance(policy.max_time, str) or not policy.max_time.strip():
        failures.append("MAX_TIME_NOT_OBSERVED")
    elif maximum_seconds is None and policy.max_time.upper() not in {
        "UNLIMITED",
        "INFINITE",
    }:
        failures.append("MAX_TIME_INVALID")
    elif (
        maximum_seconds is not None
        and requested_seconds is not None
        and requested_seconds > maximum_seconds
    ):
        failures.append("MAX_TIME_VIOLATED")

    selected_capabilities = [
        item for item in node_capabilities if item.partition == visible.name
    ]
    by_node: dict[str, NodeCapability] = {}
    for item in selected_capabilities:
        previous = by_node.get(item.node)
        if previous is not None and (
            previous.cpus_per_node != item.cpus_per_node
            or previous.memory_mb != item.memory_mb
        ):
            failures.append("CONTRADICTORY_NODE_CAPABILITY")
        by_node[item.node] = item
    if not by_node:
        failures.append("NODE_CAPABILITY_EVIDENCE_MISSING")
    if not isinstance(visible.nodes, int) or visible.nodes <= 0:
        failures.append("VISIBLE_NODES_NOT_OBSERVED")
    elif len(by_node) != visible.nodes:
        failures.append("NODE_CAPABILITY_EVIDENCE_INCOMPLETE")
    cpu_values = {item.cpus_per_node for item in by_node.values()}
    if None in cpu_values or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in cpu_values
    ):
        failures.append("CPUS_PER_NODE_NOT_OBSERVED")
    elif len(cpu_values) != 1:
        failures.append("HETEROGENEOUS_NODE_CAPABILITY")
    safe_cpus_per_node = (
        next(iter(cpu_values))
        if len(cpu_values) == 1 and None not in cpu_values
        else None
    )
    if (
        safe_cpus_per_node is not None
        and visible.cpus_per_node is not None
        and visible.cpus_per_node != safe_cpus_per_node
    ):
        failures.append("AGGREGATE_NODE_CAPABILITY_MISMATCH")
    if nodes is not None and isinstance(visible.nodes, int) and visible.nodes < nodes:
        failures.append("VISIBLE_NODES_INSUFFICIENT")

    tasks_per_node = (
        safe_cpus_per_node // resource_request.cpus_per_task
        if safe_cpus_per_node is not None
        and isinstance(resource_request.cpus_per_task, int)
        and not isinstance(resource_request.cpus_per_task, bool)
        and resource_request.cpus_per_task > 0
        else 0
    )
    if tasks_per_node <= 0:
        failures.append("CPU_OVERCOMMIT")
    if failures:
        prefix = (
            "MANUAL_NODE_SELECTION_REQUIRED"
            if failures == ["MANUAL_NODE_SELECTION_REQUIRED"]
            else "SCHEDULER_PLACEMENT_UNRESOLVED"
        )
        raise ValueError(f"{prefix}: {','.join(dict.fromkeys(failures))}")

    assert nodes is not None
    assert safe_cpus_per_node is not None
    return DerivedPlacement(
        partition=visible.name,
        nodes=nodes,
        tasks_per_node=tasks_per_node,
        ntasks=nodes * tasks_per_node,
        cpus_per_task=resource_request.cpus_per_task,
        safe_cpus_per_node=safe_cpus_per_node,
        total_allocated_cpus=nodes * safe_cpus_per_node,
        walltime=resource_request.walltime,
        policy=(
            "MAXIMUM_LEGAL_PLACEMENT_FIXED_PARTITION"
            if policy.min_nodes == policy.max_nodes
            else "MAXIMUM_LEGAL_PLACEMENT_EXPLICIT_NODES"
        ),
    )


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
            item = {"account": association.account, "partition": name, "qos": association.qos, "association_scope": association.scope, "default": bool(view and policy and view.default and policy.default), "source_files": sorted(set(filter(None, [association.source_file, view.source_file if view else None, policy.source_file if policy else None]))), "rejection_reasons": reasons}
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
