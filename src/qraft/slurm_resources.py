"""Read-only Slurm capability snapshots and deterministic run resolution.

This module deliberately knows no cluster names.  A snapshot is evidence about
one observation; a resolved profile is a human-confirmed decision for one run.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .contracts import contract_sha256
from .validation.scheduler_resolution import (
    DerivedPlacement,
    NodeCapability,
    PartitionPolicy,
    ResourceRequest,
    SchedulerAssociation,
    VisiblePartition,
    derive_partition_placement,
    model_dicts,
    parse_sacctmgr_associations as parse_live_associations,
    parse_scontrol_partitions as parse_live_partition_policies,
    parse_sinfo_node_capabilities,
    parse_sinfo_partitions as parse_live_visible_partitions,
    allows_restriction,
)


SNAPSHOT_SCHEMA_VERSION = "1.0"
_WALLTIME = re.compile(r"^(?:(?P<days>[0-9]+)-)?(?P<hours>[0-9]{1,2}):(?P<minutes>[0-9]{2}):(?P<seconds>[0-9]{2})$")


@dataclass(frozen=True)
class SlurmCommandOutput:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str = ""


class SlurmCommandRunner(Protocol):
    def run(self, command: Sequence[str]) -> SlurmCommandOutput: ...


class SubprocessSlurmCommandRunner:
    """Injectable read-only command boundary for production Slurm discovery."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = float(timeout_seconds)

    def run(self, command: Sequence[str]) -> SlurmCommandOutput:
        argv = tuple(map(str, command))
        result = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=self.timeout_seconds,
        )
        return SlurmCommandOutput(
            argv=argv,
            returncode=int(result.returncode),
            stdout=result.stdout,
            stderr=result.stderr,
        )


@dataclass(frozen=True)
class LiveSlurmEvidence:
    observed_at: str
    visible_partitions: tuple[VisiblePartition, ...]
    partition_policies: tuple[PartitionPolicy, ...]
    associations: tuple[SchedulerAssociation, ...]
    node_capabilities: tuple[NodeCapability, ...]
    commands: tuple[SlurmCommandOutput, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "authority": "LIVE_SLURM_DISCOVERY",
            "observed_at": self.observed_at,
            "commands": [
                {
                    "argv": list(item.argv),
                    "returncode": item.returncode,
                    "stdout_sha256": hashlib.sha256(
                        item.stdout.encode("utf-8")
                    ).hexdigest(),
                }
                for item in self.commands
            ],
            "visible_partitions": model_dicts(self.visible_partitions),
            "partition_policies": model_dicts(self.partition_policies),
            "associations": model_dicts(self.associations),
            "node_capabilities": model_dicts(self.node_capabilities),
        }


@dataclass(frozen=True)
class LiveSlurmSelection:
    evidence: LiveSlurmEvidence
    association: SchedulerAssociation
    resource_request: ResourceRequest
    partition: str
    placement: DerivedPlacement

    def provenance(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "authority": "LIVE_SLURM_SELECTION_EVIDENCE",
            "runtime_authority_for_future_runs": False,
            "observed_at": self.evidence.observed_at,
            "sources": self.evidence.to_dict(),
            "association": asdict(self.association),
            "resource_request": asdict(self.resource_request),
            "human_selection": {
                "partition": self.partition,
                "nodes": self.resource_request.nodes,
                "explicit": True,
            },
            "resolved_selection": {
                "account": self.resource_request.account,
                "qos": self.resource_request.qos,
            },
            "derived_placement": self.placement.to_dict(),
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def walltime_seconds(value: str | None) -> int | None:
    if value is None or str(value).upper() in {"UNLIMITED", "INFINITE", "UNKNOWN", ""}:
        return None
    match = _WALLTIME.fullmatch(str(value))
    if match is None:
        return None
    groups = match.groupdict()
    hours, minutes, seconds = (int(groups[key]) for key in ("hours", "minutes", "seconds"))
    if minutes >= 60 or seconds >= 60:
        return None
    return int(groups["days"] or 0) * 86400 + hours * 3600 + minutes * 60 + seconds


def memory_megabytes(value: str | int | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"([0-9]+)([KMGT]?)(?:B)?", str(value).strip(), re.I)
    if match is None:
        return None
    number, unit = int(match.group(1)), match.group(2).upper()
    return number * {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}[unit]


def _int(value: str | None) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _restriction(value: str | None) -> list[str] | None:
    if value is None or value.strip().upper() in {"", "ALL", "N/A", "UNKNOWN"}:
        return None
    return sorted(item for item in value.split(",") if item)


def parse_sinfo(text: str, *, source: str = "sinfo") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse the documented ``%P|%a|%l|%D|%c|%m`` machine format."""
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = [item.strip() for item in raw.split("|")]
        if len(fields) < 6 or not fields[0]:
            diagnostics.append({"code": "SINFO_ROW_INVALID", "source": source, "line": line_no})
            continue
        partition = fields[0].removesuffix("*")
        rows.append({"partition": partition, "state": fields[1] or None, "walltime": fields[2] or None,
                     "total_nodes": _int(fields[3]), "cpus_per_node": _int(fields[4]),
                     "memory_mb": _int(fields[5]), "source": source, "line": line_no})
    return rows, diagnostics


def parse_scontrol_partitions(text: str, *, source: str = "scontrol show partition") -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    values: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", raw))
        name = fields.get("PartitionName")
        if not name:
            diagnostics.append({"code": "SCONTROL_PARTITION_NAME_MISSING", "source": source, "line": line_no})
            continue
        values[name] = {"state": fields.get("State"), "walltime": fields.get("MaxTime"),
                        "min_nodes": _int(fields.get("MinNodes")), "max_nodes": _int(fields.get("MaxNodes")),
                        "exclusive_user": fields.get("ExclusiveUser", "NO").upper() == "YES",
                        "accounts": _restriction(fields.get("AllowAccounts")), "qos": _restriction(fields.get("AllowQos")),
                        "source": source, "line": line_no}
    return values, diagnostics


def parse_scontrol_nodes(text: str, *, source: str = "scontrol show node") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", raw))
        if "NodeName" not in fields:
            diagnostics.append({"code": "SCONTROL_NODE_NAME_MISSING", "source": source, "line": line_no})
            continue
        rows.append({"node": fields["NodeName"], "state": fields.get("State"), "cpus_per_node": _int(fields.get("CPUTot")),
                     "memory_mb": _int(fields.get("RealMemory")), "features": sorted(filter(None, (fields.get("AvailableFeatures") or "").split(","))),
                     "source": source, "line": line_no})
    return rows, diagnostics


def parse_sacctmgr_associations(text: str, *, source: str = "sacctmgr show assoc") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = [item.strip() for item in raw.split("|")]
        if len(fields) < 3 or not fields[0]:
            diagnostics.append({"code": "SACCTMGR_ASSOCIATION_INVALID", "source": source, "line": line_no})
            continue
        rows.append({"account": fields[0], "partition": fields[1] or None, "qos": fields[2] or None, "source": source, "line": line_no})
    return rows, diagnostics


def parse_sjstat_c(text: str, *, source: str = "sjstat -c") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse optional ``sjstat -c`` capacity rows without cluster constants."""
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if (
            stripped.casefold() == "scheduling pool data:"
            or set(stripped) == {"-"}
            or stripped.casefold().startswith("pool ")
        ):
            continue
        if "|" in stripped:  # Backward-compatible normalized fixture form.
            fields = [item.strip() for item in stripped.split("|")]
            if len(fields) < 6 or not fields[0]:
                diagnostics.append({"code": "SJSTAT_ROW_INVALID", "source": source, "line": line_no})
                continue
            rows.append({"partition": fields[0].removesuffix("*"), "default_partition": fields[0].endswith("*"),
                         "state": fields[1] or None, "total_nodes": _int(fields[2]), "usable_nodes": _int(fields[2]),
                         "idle_nodes": _int(fields[3]), "cpus_per_node": _int(fields[4]), "memory_mb": _int(fields[5]),
                         "features": sorted(filter(None, fields[6].split(","))) if len(fields) > 6 else [],
                         "source": source, "line": line_no})
            continue
        fields = stripped.split()
        if len(fields) != 7:
            diagnostics.append({"code": "SJSTAT_ROW_INVALID", "source": source, "line": line_no})
            continue
        memory = memory_megabytes(fields[1])
        cpus, total, usable, free = (_int(item) for item in fields[2:6])
        if memory is None or None in {cpus, total, usable, free}:
            diagnostics.append({"code": "SJSTAT_ROW_INVALID", "source": source, "line": line_no})
            continue
        name = fields[0].removesuffix("*")
        rows.append({"partition": name, "default_partition": fields[0].endswith("*"), "state": None,
                     "total_nodes": total, "usable_nodes": usable, "idle_nodes": free,
                     "cpus_per_node": cpus, "memory_mb": memory,
                     "features": sorted(filter(None, fields[6].split(","))), "source": source, "line": line_no})
    return rows, diagnostics


def build_snapshot(*, cluster_id: str, observed_at: str, sinfo: str = "", scontrol_partitions: str = "", scontrol_nodes: str = "", sacctmgr: str = "", sjstat: str = "") -> dict[str, Any]:
    sinfo_rows, diagnostics = parse_sinfo(sinfo)
    policies, result = parse_scontrol_partitions(scontrol_partitions); diagnostics += result
    _, result = parse_scontrol_nodes(scontrol_nodes); diagnostics += result
    associations, result = parse_sacctmgr_associations(sacctmgr); diagnostics += result
    sjstat_rows, result = parse_sjstat_c(sjstat); diagnostics += result
    by_partition: dict[str, list[dict[str, Any]]] = {}
    for row in [*sinfo_rows, *sjstat_rows]:
        by_partition.setdefault(str(row["partition"]), []).append(row)
    partitions: list[dict[str, Any]] = []
    for name in sorted(set(by_partition) | set(policies)):
        policy = policies.get(name, {})
        variants = by_partition.get(name) or [{}]
        for index, row in enumerate(variants, 1):
            related = [item for item in associations if item["partition"] in {None, name}]
            accounts = sorted({item["account"] for item in related}) or policy.get("accounts")
            qos = sorted({item["qos"] for item in related if item["qos"]}) or policy.get("qos")
            partitions.append({"variant_id": f"{name}:{index}", "name": name, "state": row.get("state") or policy.get("state"),
                               "walltime": row.get("walltime") or policy.get("walltime"), "total_nodes": row.get("total_nodes"),
                               "usable_nodes": row.get("total_nodes"), "idle_nodes": row.get("idle_nodes"), "cpus_per_node": row.get("cpus_per_node"),
                               "memory_mb": row.get("memory_mb"), "features": row.get("features", []), "node_type": None,
                               "default_partition": bool(row.get("default_partition", False)),
                               "min_nodes": policy.get("min_nodes"), "max_nodes": policy.get("max_nodes"),
                               "exclusive_user": policy.get("exclusive_user"),
                               "accounts": accounts, "qos": qos, "sources": sorted({str(item.get("source")) for item in (row, policy) if item}),
                               "unknown_fields": sorted(key for key, value in {"idle_nodes": row.get("idle_nodes"), "cpus_per_node": row.get("cpus_per_node"), "memory_mb": row.get("memory_mb")}.items() if value is None)})
    return {"schema_version": SNAPSHOT_SCHEMA_VERSION, "scheduler": "slurm", "cluster_id": cluster_id,
            "observed_at": observed_at, "sources": sorted({str(item.get("source")) for item in [*sinfo_rows, *sjstat_rows, *policies.values(), *associations]}),
            "diagnostics": diagnostics, "partitions": partitions}


def write_snapshot(snapshot: Mapping[str, Any], path: Path) -> str:
    validate_snapshot(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return sha256_file(path)


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    validate_snapshot(snapshot)
    return snapshot, sha256_file(path)


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION or snapshot.get("scheduler") != "slurm":
        raise ValueError("unsupported Slurm capability snapshot")
    if not isinstance(snapshot.get("cluster_id"), str) or not snapshot["cluster_id"]:
        raise ValueError("snapshot cluster_id is required")
    if not isinstance(snapshot.get("partitions"), list):
        raise ValueError("snapshot partitions must be a list")
    for item in snapshot["partitions"]:
        if not isinstance(item, Mapping) or not item.get("variant_id") or not item.get("name"):
            raise ValueError("snapshot partition variant is invalid")


def discover_live_slurm(
    *,
    runner: SlurmCommandRunner | None = None,
    user: str | None = None,
    observed_at: str | None = None,
) -> LiveSlurmEvidence:
    """Query live Slurm through the injectable read-only command boundary."""

    selected_runner = runner or SubprocessSlurmCommandRunner()
    selected_user = str(user or getpass.getuser()).strip()
    if not selected_user:
        raise ValueError("LIVE_SLURM_DISCOVERY_UNRESOLVED: user is required")
    commands = (
        ("sinfo", "-h", "-o", "%P|%a|%l|%D|%c|%m"),
        ("sinfo", "-N", "-h", "-o", "%N|%P|%c|%m|%t"),
        ("scontrol", "show", "partition", "-o"),
        (
            "sacctmgr",
            "-n",
            "-P",
            "show",
            "assoc",
            f"user={selected_user}",
            "format=Account,Partition,QOS",
        ),
    )
    outputs = tuple(selected_runner.run(command) for command in commands)
    failed = [item for item in outputs if item.returncode != 0]
    if failed:
        commands_failed = ",".join(item.argv[0] for item in failed)
        raise ValueError(
            "LIVE_SLURM_DISCOVERY_UNRESOLVED: command failed: "
            f"{commands_failed}"
        )

    observed = observed_at or utc_now()
    visible, diagnostics = parse_live_visible_partitions(
        outputs[0].stdout, "sinfo"
    )
    nodes, node_diagnostics = parse_sinfo_node_capabilities(
        outputs[1].stdout, "sinfo -N"
    )
    policies, policy_diagnostics = parse_live_partition_policies(
        outputs[2].stdout, "scontrol show partition"
    )
    associations, association_diagnostics = parse_live_associations(
        outputs[3].stdout,
        "sacctmgr show assoc",
        observed_at=observed,
    )
    all_diagnostics = [
        *diagnostics,
        *node_diagnostics,
        *policy_diagnostics,
        *association_diagnostics,
    ]
    if all_diagnostics:
        codes = ",".join(sorted({str(item["code"]) for item in all_diagnostics}))
        raise ValueError(
            "LIVE_SLURM_DISCOVERY_UNRESOLVED: invalid command output: "
            f"{codes}"
        )
    return LiveSlurmEvidence(
        observed_at=observed,
        visible_partitions=tuple(visible),
        partition_policies=tuple(policies),
        associations=tuple(associations),
        node_capabilities=tuple(nodes),
        commands=outputs,
    )


class LiveSlurmPlacementService:
    """Canonical application service for live human-selected placement."""

    def __init__(self, evidence: LiveSlurmEvidence) -> None:
        self.evidence = evidence

    @classmethod
    def discover(
        cls,
        *,
        runner: SlurmCommandRunner | None = None,
        user: str | None = None,
        observed_at: str | None = None,
    ) -> "LiveSlurmPlacementService":
        return cls(discover_live_slurm(
            runner=runner,
            user=user,
            observed_at=observed_at,
        ))

    @staticmethod
    def _qos_values(item: SchedulerAssociation) -> set[str]:
        return {
            value.strip()
            for value in str(item.qos or "").split(",")
            if value.strip()
        }

    @staticmethod
    def _partition_associations(
        partition: str, associations: Sequence[SchedulerAssociation]
    ) -> list[SchedulerAssociation]:
        matches = [
            item
            for item in associations
            if item.evidence_status == "OBSERVED"
            and item.partition in {None, partition}
        ]
        return matches

    def _association(
        self,
        partition: str,
        policy: PartitionPolicy,
        request: ResourceRequest,
    ) -> tuple[SchedulerAssociation, ResourceRequest]:
        candidates = self._partition_associations(
            partition, self.evidence.associations
        )
        if request.account is not None:
            accounts = {request.account}
        else:
            accounts = {
                str(item.account)
                for item in candidates
                if item.account is not None
                and allows_restriction(
                    policy.allow_accounts, item.account, observed=True
                )
            }
            if not accounts:
                raise ValueError(
                    "SCHEDULER_PLACEMENT_UNRESOLVED: "
                    "ACCOUNT_ASSOCIATION_NOT_OBSERVED"
                )
            if len(accounts) != 1:
                raise ValueError(
                    "ACCOUNT_SELECTION_REQUIRED"
                )
        account = next(iter(accounts))
        account_matches = [
            item for item in candidates if item.account == account
        ]
        explicit = [
            item for item in account_matches if item.partition == partition
        ]
        account_candidates = explicit or [
            item for item in account_matches if item.partition is None
        ]
        if not account_candidates:
            raise ValueError(
                "SCHEDULER_PLACEMENT_UNRESOLVED: "
                "ACCOUNT_ASSOCIATION_NOT_OBSERVED"
            )
        if request.qos is not None:
            qos = request.qos
            if not any(qos in self._qos_values(item) for item in account_candidates):
                raise ValueError(
                    "SCHEDULER_PLACEMENT_UNRESOLVED: "
                    "QOS_ASSOCIATION_NOT_OBSERVED"
                )
        else:
            qoses = {
                qos
                for item in account_candidates
                for qos in self._qos_values(item)
                if allows_restriction(policy.allow_qos, qos, observed=True)
            }
            if len(qoses) > 1:
                raise ValueError("QOS_SELECTION_REQUIRED")
            if len(qoses) == 1:
                qos = next(iter(qoses))
            elif (
                all(item.qos is None for item in account_candidates)
                and policy.allow_qos["kind"] in {"ALL", "N/A"}
            ):
                qos = None
            else:
                raise ValueError(
                    "SCHEDULER_PLACEMENT_UNRESOLVED: "
                    "QOS_ASSOCIATION_NOT_OBSERVED"
                )
        association = next(
            item for item in account_candidates
            if qos is None or qos in self._qos_values(item)
        )
        return (
            replace(association, account=account, qos=qos),
            replace(request, account=account, qos=qos),
        )

    def _normalized_visible_partition(
        self,
        partition: str,
        rows: Sequence[VisiblePartition],
    ) -> VisiblePartition:
        """Bind aggregate ``sinfo`` visibility to node-level evidence.

        Aggregate rows can be split by Slurm state.  Their node counts are not
        capacity authority: the unique ``sinfo -N`` node set is authoritative.
        """

        availability = {item.availability for item in rows}
        time_limits = {item.time_limit for item in rows}
        if len(availability) != 1 or len(time_limits) != 1:
            raise ValueError(
                "SCHEDULER_PLACEMENT_UNRESOLVED: "
                "AGGREGATE_PARTITION_EVIDENCE_CONTRADICTORY"
            )
        capabilities = [
            item for item in self.evidence.node_capabilities
            if item.partition == partition
        ]
        by_node: dict[str, NodeCapability] = {}
        for item in capabilities:
            previous = by_node.get(item.node)
            if previous is not None and (
                previous.cpus_per_node != item.cpus_per_node
                or previous.memory_mb != item.memory_mb
            ):
                raise ValueError(
                    "SCHEDULER_PLACEMENT_UNRESOLVED: "
                    "CONTRADICTORY_NODE_CAPABILITY"
                )
            by_node[item.node] = item
        if not by_node:
            raise ValueError(
                "SCHEDULER_PLACEMENT_UNRESOLVED: "
                "NODE_CAPABILITY_EVIDENCE_MISSING"
            )
        cpu_values = {item.cpus_per_node for item in by_node.values()}
        memory_values = {item.memory_mb for item in by_node.values()}
        aggregate_cpus = {
            item.cpus_per_node for item in rows
            if item.cpus_per_node is not None
        }
        aggregate_memory = {
            item.memory for item in rows if item.memory is not None
        }
        if (
            len(aggregate_cpus) > 1
            or len(aggregate_memory) > 1
            or (
                len(cpu_values) == 1
                and aggregate_cpus
                and aggregate_cpus != cpu_values
            )
            or (
                len(memory_values) == 1
                and aggregate_memory
                and aggregate_memory != memory_values
            )
        ):
            raise ValueError(
                "SCHEDULER_PLACEMENT_UNRESOLVED: "
                "AGGREGATE_NODE_CAPABILITY_MISMATCH"
            )
        exemplar = rows[0]
        return VisiblePartition(
            name=partition,
            availability=exemplar.availability,
            time_limit=exemplar.time_limit,
            nodes=len(by_node),
            cpus_per_node=(
                next(iter(cpu_values)) if len(cpu_values) == 1 else None
            ),
            memory=(
                next(iter(memory_values)) if len(memory_values) == 1 else None
            ),
            default=any(item.default for item in rows),
            source_file=exemplar.source_file,
            source_line=min(item.source_line for item in rows),
        )

    def select(
        self,
        *,
        partition: str,
        resource_request: ResourceRequest,
    ) -> LiveSlurmSelection:
        name = str(partition).strip()
        if not name:
            raise ValueError("MANUAL_PARTITION_SELECTION_REQUIRED")
        visible = [
            item for item in self.evidence.visible_partitions if item.name == name
        ]
        policies = [
            item for item in self.evidence.partition_policies if item.name == name
        ]
        if not visible or len(policies) != 1:
            raise ValueError(
                "SCHEDULER_PLACEMENT_UNRESOLVED: "
                "PARTITION_EVIDENCE_NOT_UNIQUE"
            )
        normalized_visible = self._normalized_visible_partition(name, visible)
        association, resolved_request = self._association(
            name, policies[0], resource_request
        )
        placement = derive_partition_placement(
            normalized_visible,
            policies[0],
            self.evidence.node_capabilities,
            association,
            resolved_request,
        )
        return LiveSlurmSelection(
            evidence=self.evidence,
            association=association,
            resource_request=resolved_request,
            partition=name,
            placement=placement,
        )

    def show_resources(
        self, *, resource_request: ResourceRequest
    ) -> tuple[dict[str, Any], ...]:
        """Report live compatibility without choosing or ranking a partition."""

        names = sorted({item.name for item in self.evidence.partition_policies})
        options: list[dict[str, Any]] = []
        for name in names:
            try:
                selection = self.select(
                    partition=name,
                    resource_request=resource_request,
                )
            except ValueError as error:
                text = str(error)
                status = (
                    "MANUAL_NODE_SELECTION_REQUIRED"
                    if "MANUAL_NODE_SELECTION_REQUIRED" in text
                    else "NOT_SELECTABLE"
                )
                options.append({
                    "partition": name,
                    "status": status,
                    "reason": text,
                    "derived_placement": None,
                })
            else:
                options.append({
                    "partition": name,
                    "status": "SELECTABLE",
                    "reason": "STATIC_POLICY_COMPATIBILITY",
                    "derived_placement": selection.placement.to_dict(),
                })
        return tuple(options)


def write_live_selection_provenance(
    selection: LiveSlurmSelection, path: Path
) -> str:
    payload = selection.provenance()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return sha256_file(path)


def discover_snapshot(*, cluster_id: str, observed_at: str | None = None) -> dict[str, Any]:
    """Run only read-only Slurm commands; missing commands become evidence."""
    commands = {"sinfo": ["sinfo", "-h", "-o", "%P|%a|%l|%D|%c|%m"], "scontrol_partitions": ["scontrol", "show", "partition", "-o"],
                "scontrol_nodes": ["scontrol", "show", "node", "-o"], "sacctmgr": ["sacctmgr", "-n", "-P", "show", "assoc", f"user={getpass.getuser()}", "format=Account,Partition,QOS"]}
    output: dict[str, str] = {}; unavailable: list[dict[str, str]] = []
    for key, command in commands.items():
        if shutil.which(command[0]) is None:
            unavailable.append({"code": "DISCOVERY_COMMAND_UNAVAILABLE", "command": command[0]}); continue
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        output[key] = result.stdout if result.returncode == 0 else ""
        if result.returncode:
            unavailable.append({"code": "DISCOVERY_COMMAND_FAILED", "command": command[0]})
    snapshot = build_snapshot(cluster_id=cluster_id, observed_at=observed_at or utc_now(), **output)
    snapshot["diagnostics"] = [*snapshot["diagnostics"], *unavailable]
    return snapshot


def resolve_candidates(*, profile: Any, snapshot: Mapping[str, Any], required_features: tuple[str, ...] = ()) -> dict[str, Any]:
    """Pure ranking.  It reports observed capacity; it never predicts queue time."""
    validate_snapshot(snapshot)
    requested_memory = memory_megabytes(profile.memory)
    candidates: list[dict[str, Any]] = []
    for variant in snapshot["partitions"]:
        reasons: list[str] = []; review: list[str] = []
        maximum = walltime_seconds(variant.get("walltime")); requested = walltime_seconds(profile.walltime)
        if maximum is None: review.append("UNKNOWN_REQUIRED_CAPABILITY")
        elif requested is not None and maximum < requested: reasons.append("INSUFFICIENT_WALLTIME")
        if variant.get("min_nodes") is not None and profile.nodes < int(variant["min_nodes"]):
            reasons.append("MIN_NODES_INCOMPATIBLE")
        if variant.get("max_nodes") is not None and profile.nodes > int(variant["max_nodes"]):
            reasons.append("MAX_NODES_INCOMPATIBLE")
        if variant.get("usable_nodes") is not None and int(variant["usable_nodes"]) < profile.nodes: reasons.append("INSUFFICIENT_NODES")
        if variant.get("cpus_per_node") is None: review.append("UNKNOWN_REQUIRED_CAPABILITY")
        elif int(variant["cpus_per_node"]) < int(profile.processes_per_node or profile.total_cpus): reasons.append("INSUFFICIENT_CPUS_PER_NODE")
        if requested_memory is not None:
            if variant.get("memory_mb") is None: review.append("UNKNOWN_REQUIRED_CAPABILITY")
            elif float(variant["memory_mb"]) < requested_memory: reasons.append("INSUFFICIENT_MEMORY")
        if not set(required_features).issubset(set(variant.get("features") or ())): reasons.append("REQUIRED_FEATURE_MISSING")
        for field, value, code in (("accounts", profile.account, "ACCOUNT_NOT_AUTHORIZED"), ("qos", profile.qos, "QOS_NOT_AUTHORIZED")):
            allowed = variant.get(field)
            if allowed is None: review.append("UNKNOWN_REQUIRED_CAPABILITY")
            elif value not in allowed: reasons.append(code)
        if profile.launcher_kind not in {"hydra", "srun"}: reasons.append("LAUNCHER_NOT_SUPPORTED")
        idle = variant.get("idle_nodes")
        if idle is None: review.append("UNKNOWN_REQUIRED_CAPABILITY")
        if not reasons and idle is not None and int(idle) == 0: state = "COMPATIBLE_NO_CURRENT_IDLE_CAPACITY"; review.append("NO_USABLE_NODES_OBSERVED")
        elif reasons: state = "INCOMPATIBLE"
        elif review: state = "REQUIRES_HUMAN_REVIEW"
        else: state = "COMPATIBLE"
        cpus_per_node = variant.get("cpus_per_node")
        reserved_cpus = (profile.nodes * int(cpus_per_node)) if cpus_per_node is not None else None
        memory_per_node = variant.get("memory_mb")
        candidate = {"candidate_id": str(variant["variant_id"]), "partition": variant["name"], "state": state,
                     "rejection_reasons": sorted(set(reasons)), "review_codes": sorted(set(review)), "idle_nodes": idle,
                     "resources": {"nodes": profile.nodes, "ranks_per_node": profile.processes_per_node, "total_ranks": profile.total_cpus,
                                   "memory": profile.memory, "walltime": profile.walltime, "features": variant.get("features") or []},
                     "source_variant": variant,
                     "score": {
                         "wasted_cpus": (reserved_cpus - profile.total_cpus) if reserved_cpus is not None else None,
                         "reserved_cpus": reserved_cpus,
                         "walltime_slack_seconds": (maximum - requested) if maximum is not None and requested is not None else None,
                         "memory_excess_mb": (profile.nodes * float(memory_per_node) - profile.nodes * requested_memory) if memory_per_node is not None and requested_memory is not None else None,
                         "free_nodes": idle,
                         "uncertainty_count": len(set(review)),
                     }}
        candidates.append(candidate)
    rank = {"COMPATIBLE": 0, "COMPATIBLE_NO_CURRENT_IDLE_CAPACITY": 1, "REQUIRES_HUMAN_REVIEW": 2, "INCOMPATIBLE": 3}
    def sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        score = item["score"]
        unknown = float("inf")
        return (
            rank[item["state"]],
            score["wasted_cpus"] if score["wasted_cpus"] is not None else unknown,
            score["reserved_cpus"] if score["reserved_cpus"] is not None else unknown,
            score["walltime_slack_seconds"] if score["walltime_slack_seconds"] is not None else unknown,
            score["memory_excess_mb"] if score["memory_excess_mb"] is not None else unknown,
            -(score["free_nodes"] or 0),
            score["uncertainty_count"],
            item["candidate_id"],
        )
    candidates.sort(key=sort_key)
    for index, item in enumerate(candidates, 1):
        item["rank"] = index
        item["recommendation"] = ("RECOMMENDED_BY_CURRENT_SNAPSHOT" if index == 1 and item["state"] == "COMPATIBLE" else
                                  "COMPATIBLE_ALTERNATIVE" if item["state"] == "COMPATIBLE" else
                                  "COMPATIBLE_WITHOUT_IDLE_CAPACITY" if item["state"] == "COMPATIBLE_NO_CURRENT_IDLE_CAPACITY" else item["state"])
        item["ranking_reason"] = "deterministic fit by CPU waste, reservation, walltime, memory, free nodes, and uncertainty; not a queue-time prediction"
    return {"snapshot_sha256": contract_sha256(snapshot), "snapshot_schema_version": snapshot["schema_version"],
            "snapshot_observed_at": snapshot["observed_at"], "candidates": candidates,
            "compatible": [item for item in candidates if item["state"] != "INCOMPATIBLE"],
            "incompatible": [item for item in candidates if item["state"] == "INCOMPATIBLE"]}
