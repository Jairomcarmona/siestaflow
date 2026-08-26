#!/usr/bin/env python3
"""Turn M10 raw login evidence into portable, non-executable evidence JSON."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _read(root: Path, name: str) -> str | None:
    path = root / name
    return path.read_text(encoding="utf-8", errors="replace").strip() if path.is_file() else None


def _version(value: str | None) -> str | None:
    found = re.search(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)", value or "")
    return found.group(1) if found else None


def _commands(raw: Path) -> dict[str, str | None]:
    return {path.stem.removeprefix("command_").replace("_", "."): _read(raw, path.name) or None for path in raw.glob("command_*.txt")}


def _partitions(value: str | None) -> list[dict[str, object]]:
    result = []
    for line in (value or "").splitlines():
        fields = line.split("|")
        if len(fields) != 6:
            continue
        name, availability, limit, nodes, cpus, memory = fields
        try:
            result.append({"name": name.rstrip("*"), "availability": availability, "time_limit": limit, "nodes": int(nodes), "cpus_per_node": int(cpus), "memory": int(memory), "default": name.endswith("*")})
        except ValueError:
            continue
    return result


def _associations(value: str | None, source: str) -> list[dict[str, object]]:
    result = []
    for line in (value or "").splitlines():
        fields = [field.strip() for field in line.strip("|").split("|")]
        if source == "squeue" and len(fields) >= 5:
            partition, account, qos = fields[2], fields[3], fields[4]
        elif len(fields) >= 2:
            account, partition, qos = fields[0], fields[1], fields[2] if len(fields) > 2 else None
        else:
            continue
        if account and partition:
            result.append({"account": account, "partition": partition.rstrip("*"), "qos": qos or None, "source": source})
    return result


def build(raw: Path) -> dict[str, object]:
    commands = _commands(raw)
    environment = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in (_read(raw, "environment_redacted.txt") or "").splitlines() if "=" in line}
    python_candidates = []
    for name in ("python", "python3"):
        executable = commands.get(name)
        if executable:
            python_candidates.append({"selected_mechanism": "PATH", "selected_executable": executable, "observed_version": _version(_read(raw, f"{name}_version.txt")), "environment_setup": [], "evidence_source": [f"command_{name}.txt", f"{name}_version.txt"]})
    siesta = commands.get("siesta")
    siesta_candidates = ([] if not siesta else [{"selected_mechanism": "PATH", "selected_executable": siesta, "observed_version": _version(_read(raw, "siesta_version.txt")) or "UNVERIFIED", "environment_setup": [], "evidence_source": ["command_siesta.txt", "siesta_version.txt"]}])
    launchers = {}
    for name in ("srun", "mpiexec.hydra"):
        executable = commands.get(name)
        if executable:
            candidate = {"selected_mechanism": "PATH", "selected_executable": executable, "arguments": [], "environment_setup": [], "evidence_source": [f"command_{name.replace('.', '_')}.txt"]}
            if name == "mpiexec.hydra":
                help_text = _read(raw, "mpiexec_hydra_help.txt") or ""
                bootstrap = environment.get("I_MPI_HYDRA_BOOTSTRAP")
                if "-n" in help_text and "-ppn" in help_text and bootstrap:
                    candidate.update({"arguments": ["-n", "64", "-ppn", "32"], "bootstrap": bootstrap, "evidence_source": [*candidate["evidence_source"], "mpiexec_hydra_help.txt", "environment_redacted.txt"]})
            launchers[name] = [candidate]
    return {"schema_version": "1.0", "raw_evidence_status": "OBSERVED", "observed_at": _read(raw, "observed_at.txt"), "hostname": _read(raw, "hostname.txt"), "user": _read(raw, "user.txt"), "system": _read(raw, "system.txt"), "shell": _read(raw, "shell.txt"), "working_path": _read(raw, "working_path.txt"), "commands": commands, "environment": environment, "module_available": _read(raw, "module_available.txt") == "true", "conda_available": _read(raw, "conda_available.txt") == "true", "spack_available": _read(raw, "spack_available.txt") == "true", "python_candidates": python_candidates, "siesta_candidates": siesta_candidates, "launcher_candidates": launchers, "module_candidates": {"python": (_read(raw, "module_python_candidates.txt") or "").splitlines(), "siesta": (_read(raw, "module_siesta_candidates.txt") or "").splitlines()}, "eligible_associations": _associations(_read(raw, "sacctmgr_assoc.txt"), "sacctmgr") + _associations(_read(raw, "squeue.txt"), "squeue"), "visible_partitions": _partitions(_read(raw, "sinfo.txt")), "scheduler_diagnostics": {"sacctmgr_exit_code": _read(raw, "sacctmgr_assoc.txt.exit_code"), "squeue_exit_code": _read(raw, "squeue.txt.exit_code")}, "scientific_calculation_performed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path); parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists(): raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: refusing to overwrite summary: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build(args.raw), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__": raise SystemExit(main())
