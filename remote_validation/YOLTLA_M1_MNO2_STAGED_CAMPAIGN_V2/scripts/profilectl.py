#!/usr/bin/env python3
"""Build, validate and explicitly approve evidence-bound Yoltla profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from siestaflow.execution.time_utils import canonical_slurm_walltime

EXPECTED_VERSION = "5.4.2"
PRODUCTION = "VERIFIED_FOR_PRODUCTION"
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_./:+-]+$")
VERSION_PATTERNS = (
    re.compile(r"(?i)\bSIESTA(?:\s+version)?\s*[:=v-]*\s*(\d+\.\d+\.\d+)\b"),
    re.compile(r"(?i)\bversion\s+(\d+\.\d+\.\d+)\b"),
)


class ProfileError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"INVALID_JSON:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise ProfileError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def parse_siesta_version(output: str) -> str:
    versions: set[str] = set()
    for pattern in VERSION_PATTERNS:
        versions.update(pattern.findall(output))
    if len(versions) != 1:
        raise ProfileError("SIESTA_VERSION_OUTPUT_UNEXPECTED")
    return versions.pop()


def check_siesta_version(executable: str, required: str = EXPECTED_VERSION) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        raise ProfileError(f"SIESTA_EXECUTABLE_NOT_FOUND:{executable}")
    completed = subprocess.run(
        [resolved, "--version"], capture_output=True, text=True, timeout=30, check=False
    )
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    if completed.returncode:
        raise ProfileError(f"SIESTA_VERSION_COMMAND_FAILED:{completed.returncode}")
    observed = parse_siesta_version(output)
    if observed != required:
        raise ProfileError(f"SIESTA_VERSION_MISMATCH:{observed}:required={required}")
    return observed


def _positive(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"POSITIVE_INTEGER_REQUIRED:{field}") from exc
    if result <= 0:
        raise ProfileError(f"POSITIVE_INTEGER_REQUIRED:{field}")
    return result


def _structured_modules(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("purge"), bool):
        raise ProfileError("STRUCTURED_MODULES_REQUIRED")
    loads = data.get("load")
    if not isinstance(loads, list) or not loads:
        raise ProfileError("MODULE_LOAD_LIST_REQUIRED")
    if any(not isinstance(item, str) or not SAFE_TOKEN.fullmatch(item) for item in loads):
        raise ProfileError("UNSAFE_MODULE_TOKEN")
    if "siesta/5.4.2" not in loads:
        raise ProfileError("REQUIRED_SIESTA_MODULE_NOT_DECLARED")
    return data


def validate(path: Path, *, production: bool = False) -> dict[str, Any]:
    data = load(path)
    if data.get("schema_version") != "2.0":
        raise ProfileError("PROFILE_SCHEMA_MISMATCH")
    slurm = data.get("slurm")
    resources = data.get("resources")
    runtime = data.get("runtime")
    layouts = data.get("resource_layouts")
    if not all(isinstance(item, dict) for item in (slurm, resources, runtime, layouts)):
        raise ProfileError("PROFILE_SECTIONS_REQUIRED")
    expected = {"partition": "qz2d-128p", "account": "vini", "qos": "normal"}
    for field, value in expected.items():
        if slurm.get(field) != value:
            raise ProfileError(f"YOLTLA_PROFILE_MISMATCH:slurm.{field}")
    nodes = _positive(resources.get("nodes"), "resources.nodes")
    total = _positive(resources.get("total_cpus"), "resources.total_cpus")
    per_node = _positive(resources.get("tasks_per_node"), "resources.tasks_per_node")
    physical = _positive(
        resources.get("physical_cpus_per_node"), "resources.physical_cpus_per_node"
    )
    if (nodes, total, per_node) != (2, 80, 40):
        raise ProfileError("YOLTLA_RESOURCE_REQUEST_MUST_BE_2x40_EQUALS_80")
    if per_node > physical or total != nodes * per_node:
        raise ProfileError("INCOMPATIBLE_NODE_TASK_DISTRIBUTION")
    resources["walltime"] = canonical_slurm_walltime(str(resources.get("walltime")))
    if resources["walltime"] != "2-00:00:00":
        raise ProfileError("YOLTLA_WALLTIME_MUST_BE_TWO_DAYS")
    memory = resources.get("memory_policy")
    if not isinstance(memory, dict) or memory.get("mode") not in {
        "partition_default",
        "explicit_mb_per_node",
    }:
        raise ProfileError("MEMORY_POLICY_REQUIRED")
    if memory["mode"] == "partition_default" and memory.get("value") is not None:
        raise ProfileError("PARTITION_DEFAULT_MEMORY_MUST_OMIT_VALUE")
    if not str(memory.get("rationale") or "").strip():
        raise ProfileError("MEMORY_POLICY_RATIONALE_REQUIRED")
    _structured_modules(data.get("modules"))
    if runtime.get("required_siesta_version") != EXPECTED_VERSION:
        raise ProfileError("REQUIRED_SIESTA_VERSION_MUST_BE_5.4.2")
    launcher = runtime.get("launcher")
    if not isinstance(launcher, dict) or launcher.get("backend") not in {
        "srun",
        "hydra_ssh",
    }:
        raise ProfileError("VALID_LAUNCHER_BACKEND_REQUIRED")
    if launcher.get("backend") == "hydra_ssh" and launcher.get("bootstrap") != "ssh":
        raise ProfileError("HYDRA_BOOTSTRAP_MUST_BE_SSH")
    if str(launcher.get("bootstrap") or "").lower() == "slurm":
        raise ProfileError("HYDRA_BOOTSTRAP_SLURM_FORBIDDEN")
    available = layouts.get("available")
    selected = layouts.get("selected")
    if not isinstance(available, dict) or selected not in available:
        raise ProfileError("RESOURCE_LAYOUT_SELECTION_INVALID")
    for name, expected_pair in {
        "serial_80": (1, 80),
        "dual_40": (2, 40),
        "quad_20": (4, 20),
    }.items():
        item = available.get(name)
        if not isinstance(item, dict):
            raise ProfileError(f"RESOURCE_LAYOUT_MISSING:{name}")
        if (
            _positive(item.get("max_parallel_steps"), f"{name}.max_parallel_steps"),
            _positive(item.get("mpi_processes_per_step"), f"{name}.mpi_processes"),
        ) != expected_pair:
            raise ProfileError(f"RESOURCE_LAYOUT_INVALID:{name}")
    if production:
        if data.get("profile_status") != PRODUCTION:
            raise ProfileError(f"PROFILE_NOT_VERIFIED:{data.get('profile_status')}")
        if launcher.get("remote_validation_status") != "VERIFIED":
            raise ProfileError("LAUNCHER_NOT_REMOTELY_VERIFIED")
        if layouts.get("selection_status") != "HUMAN_ACCEPTED":
            raise ProfileError("RESOURCE_LAYOUT_NOT_HUMAN_ACCEPTED")
        evidence = data.get("evidence_sha256")
        if not isinstance(evidence, dict) or not evidence:
            raise ProfileError("PROFILE_EVIDENCE_HASHES_REQUIRED")
        for relative, expected_hash in evidence.items():
            target = ROOT / str(relative)
            if not target.is_file():
                raise ProfileError(f"PROFILE_EVIDENCE_MISSING:{relative}")
            if sha256(target) != expected_hash:
                raise ProfileError(f"PROFILE_EVIDENCE_HASH_MISMATCH:{relative}")
    return data


def build(evidence: Path, template: Path, output: Path) -> dict[str, Any]:
    if not inside(template, ROOT / "profiles"):
        raise ProfileError("TEMPLATE_MUST_LIVE_UNDER_IMMUTABLE_PROFILES")
    if not inside(output, ROOT / "site/profiles"):
        raise ProfileError("DERIVED_PROFILE_MUST_LIVE_UNDER_SITE_PROFILES")
    data = validate(template)
    required = data.get("required_remote_evidence")
    if not isinstance(required, list) or not required:
        raise ProfileError("REQUIRED_REMOTE_EVIDENCE_LIST_MISSING")
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for name in required:
        target = evidence / str(name)
        if not target.is_file() or target.stat().st_size == 0:
            missing.append(str(name))
            continue
        relative = target.resolve().relative_to(ROOT.resolve()).as_posix()
        hashes[relative] = sha256(target)
    if missing:
        raise ProfileError("REMOTE_EVIDENCE_MISSING_OR_EMPTY:" + ",".join(missing))
    data["profile_id"] = output.stem
    data["profile_status"] = "CANDIDATE_REMOTE_EVIDENCE_CAPTURED"
    data["evidence_sha256"] = dict(sorted(hashes.items()))
    data["evidence_observed_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(output, data)
    return {"status": data["profile_status"], "output": str(output), "evidence": len(hashes)}


def approve(path: Path, accepted_by: str, layout: str) -> dict[str, Any]:
    if not inside(path, ROOT / "site/profiles"):
        raise ProfileError("APPROVED_PROFILE_MUST_LIVE_UNDER_SITE_PROFILES")
    data = validate(path)
    if data.get("profile_status") != "CANDIDATE_REMOTE_EVIDENCE_CAPTURED":
        raise ProfileError("ONLY_EVIDENCE_CAPTURED_CANDIDATE_CAN_BE_APPROVED")
    if not accepted_by.strip():
        raise ProfileError("ACCEPTED_BY_REQUIRED")
    if layout not in data["resource_layouts"]["available"]:
        raise ProfileError("UNKNOWN_RESOURCE_LAYOUT")
    evidence_paths = [ROOT / item for item in data["evidence_sha256"]]
    evidence_by_name = {
        item.name: item.read_text(encoding="utf-8", errors="replace")
        for item in evidence_paths
    }
    for name, text in evidence_by_name.items():
        match = re.search(r"capture_exit_code=(\d+)", text)
        if match and int(match.group(1)) != 0:
            raise ProfileError(f"REMOTE_EVIDENCE_COMMAND_FAILED:{name}")
    observed = parse_siesta_version(evidence_by_name.get("siesta_version.txt", ""))
    if observed != EXPECTED_VERSION:
        raise ProfileError(f"REMOTE_SIESTA_VERSION_MISMATCH:{observed}")
    if "siesta/5.4.2" not in evidence_by_name.get("module_list.txt", ""):
        raise ProfileError("REMOTE_MODULE_LIST_DOES_NOT_SHOW_SIESTA_5.4.2")
    hydra_help = evidence_by_name.get("hydra_help.txt", "").lower()
    if "hydra" not in hydra_help and "mpiexec" not in hydra_help:
        raise ProfileError("HYDRA_HELP_EVIDENCE_UNEXPECTED")
    evidence_text = "\n".join(evidence_by_name.values())
    if "Submitted batch job" in evidence_text:
        raise ProfileError("EVIDENCE_CAPTURE_MUST_NOT_SUBMIT_A_REAL_JOB")
    data["resource_layouts"]["selected"] = layout
    data["resource_layouts"]["selection_status"] = "HUMAN_ACCEPTED"
    data["runtime"]["launcher"]["remote_validation_status"] = "VERIFIED"
    data["profile_status"] = PRODUCTION
    data["accepted_by"] = accepted_by.strip()
    data["accepted_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(path, data)
    validate(path, production=True)
    return {"status": PRODUCTION, "profile": str(path), "layout": layout}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("profile", type=Path)
    check.add_argument("--production", action="store_true")
    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("--evidence", required=True, type=Path)
    build_cmd.add_argument("--template", required=True, type=Path)
    build_cmd.add_argument("--output", required=True, type=Path)
    approve_cmd = sub.add_parser("approve")
    approve_cmd.add_argument("profile", type=Path)
    approve_cmd.add_argument("--accepted-by", required=True)
    approve_cmd.add_argument(
        "--layout", choices=("serial_80", "dual_40", "quad_20"), required=True
    )
    version = sub.add_parser("check-version")
    version.add_argument("--executable", default="siesta")
    version.add_argument("--required", default=EXPECTED_VERSION)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "validate":
            data = validate(args.profile.resolve(), production=args.production)
            result = {"status": "PROFILE_VALID", "profile_status": data["profile_status"]}
        elif args.command == "build":
            result = build(
                args.evidence.resolve(), args.template.resolve(), args.output.resolve()
            )
        elif args.command == "approve":
            result = approve(args.profile.resolve(), args.accepted_by, args.layout)
        else:
            result = {
                "status": "SIESTA_VERSION_VERIFIED",
                "version": check_siesta_version(args.executable, args.required),
            }
    except (ProfileError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2) + "\n", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
