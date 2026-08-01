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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import contract_sha256


SNAPSHOT_SCHEMA_VERSION = "1.0"
_WALLTIME = re.compile(r"^(?:(?P<days>[0-9]+)-)?(?P<hours>[0-9]{1,2}):(?P<minutes>[0-9]{2}):(?P<seconds>[0-9]{2})$")


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
    match = re.fullmatch(r"([0-9]+)([KMGT]?)", str(value).strip(), re.I)
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
    """Parse a portable pipe fixture; unknown columns remain unknown.

    ``sjstat`` is optional.  Deployments can map its output to this stable
    six-column form: partition|state|nodes|idle_nodes|cpus_per_node|memory_mb|features.
    """
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        fields = [item.strip() for item in raw.split("|")]
        if len(fields) < 6 or not fields[0]:
            diagnostics.append({"code": "SJSTAT_ROW_INVALID", "source": source, "line": line_no})
            continue
        rows.append({"partition": fields[0], "state": fields[1] or None, "total_nodes": _int(fields[2]),
                     "idle_nodes": _int(fields[3]), "cpus_per_node": _int(fields[4]), "memory_mb": _int(fields[5]),
                     "features": sorted(filter(None, fields[6].split(","))) if len(fields) > 6 else [],
                     "source": source, "line": line_no})
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
        if maximum is not None and requested is not None and maximum < requested: reasons.append("INSUFFICIENT_WALLTIME")
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
        if not reasons and idle is not None and int(idle) == 0: state = "COMPATIBLE_NO_CURRENT_IDLE_CAPACITY"; review.append("NO_USABLE_NODES_OBSERVED")
        elif reasons: state = "INCOMPATIBLE"
        elif review: state = "REQUIRES_HUMAN_REVIEW"
        else: state = "COMPATIBLE"
        candidate = {"candidate_id": str(variant["variant_id"]), "partition": variant["name"], "state": state,
                     "rejection_reasons": sorted(set(reasons)), "review_codes": sorted(set(review)), "idle_nodes": idle,
                     "resources": {"nodes": profile.nodes, "ranks_per_node": profile.processes_per_node, "total_ranks": profile.total_cpus,
                                   "memory": profile.memory, "walltime": profile.walltime, "features": variant.get("features") or []},
                     "source_variant": variant}
        candidates.append(candidate)
    rank = {"COMPATIBLE": 0, "COMPATIBLE_NO_CURRENT_IDLE_CAPACITY": 1, "REQUIRES_HUMAN_REVIEW": 2, "INCOMPATIBLE": 3}
    candidates.sort(key=lambda item: (rank[item["state"]], -(item["idle_nodes"] or 0), item["candidate_id"]))
    for index, item in enumerate(candidates, 1):
        item["rank"] = index
        item["recommendation"] = ("RECOMMENDED_BY_CURRENT_SNAPSHOT" if index == 1 and item["state"] == "COMPATIBLE" else
                                  "COMPATIBLE_ALTERNATIVE" if item["state"] == "COMPATIBLE" else
                                  "COMPATIBLE_WITHOUT_IDLE_CAPACITY" if item["state"] == "COMPATIBLE_NO_CURRENT_IDLE_CAPACITY" else item["state"])
        item["ranking_reason"] = "deterministic structural fit; not a queue-time prediction"
    return {"snapshot_sha256": contract_sha256(snapshot), "snapshot_schema_version": snapshot["schema_version"],
            "snapshot_observed_at": snapshot["observed_at"], "candidates": candidates,
            "compatible": [item for item in candidates if item["state"] != "INCOMPATIBLE"],
            "incompatible": [item for item in candidates if item["state"] == "INCOMPATIBLE"]}
