#!/usr/bin/env python3
"""Turn M10 raw login and optional module-probe evidence into reviewable JSON."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


def _read(root: Path, name: str) -> str | None:
    path = root / name
    return path.read_text(encoding="utf-8", errors="replace").strip() if path.is_file() else None


def _version(value: str | None) -> str | None:
    found = re.search(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)", value or "")
    return found.group(1) if found else None


def _commands(root: Path) -> dict[str, str | None]:
    return {
        path.stem.removeprefix("command_").replace("_", "."): _read(root, path.name) or None
        for path in root.glob("command_*.txt")
    }


def _absolute_library_runtime_root(value: str | None) -> str | None:
    """Normalize an observed dynamic-library path to its installation root."""
    if not value or not value.startswith("/"):
        return None
    path = PurePosixPath(re.sub(r"/+", "/", value.strip()))
    for parent in path.parents:
        if parent.name in {"lib", "lib64"}:
            return str(parent.parent)
    return None


def _dynamic_runtime_facts(root: Path, artifact: str) -> tuple[dict[str, str], list[str]]:
    """Extract one unambiguous runtime instance from canonicalized library evidence."""
    evidence = _read(root, f"{artifact}_realpaths.txt")
    if evidence is None or _read(root, f"{artifact}.txt.exit_code") != "0":
        return {}, []
    roots = {
        runtime_root
        for line in evidence.splitlines()
        if re.fullmatch(r"/\S*/libmpi(?:fort|cxx)?\.so(?:\.\d+)*", line)
        for runtime_root in [_absolute_library_runtime_root(line)]
        if runtime_root is not None
    }
    if len(roots) == 1:
        return {"mpi_runtime_instance": roots.pop()}, []
    if len(roots) > 1:
        return {}, ["mpi_runtime_instance has multiple canonical dynamic-link origins"]
    return {}, []


def _environment_runtime_facts(root: Path) -> dict[str, str]:
    value = _read(root, "i_mpi_root_realpath.txt")
    if not value or not re.fullmatch(r"/\S+", value):
        return {}
    return {"mpi_runtime_instance": str(PurePosixPath(value))}


def _add_engine_runtime_evidence(
    candidate: dict[str, object], root: Path, source_prefix: str,
) -> None:
    facts, conflicts = _dynamic_runtime_facts(root, "siesta_dynamic_dependencies")
    if facts:
        candidate["compatibility_facts"] = facts
        candidate["compatibility_fact_sources"] = {
            "mpi_runtime_instance": [f"{source_prefix}siesta_dynamic_dependencies_realpaths.txt"]
        }
        candidate["evidence_source"] = [
            *candidate["evidence_source"],
            f"{source_prefix}siesta_dynamic_dependencies.txt",
            f"{source_prefix}siesta_dynamic_dependencies.txt.exit_code",
            f"{source_prefix}siesta_dynamic_dependencies_realpaths.txt",
        ]
    if conflicts:
        candidate["compatibility_conflicts"] = conflicts
    environment_facts = _environment_runtime_facts(root)
    if environment_facts:
        candidate["environment_compatibility_facts"] = environment_facts
        candidate["environment_compatibility_fact_sources"] = {
            "mpi_runtime_instance": [f"{source_prefix}i_mpi_root_realpath.txt"]
        }
        candidate["evidence_source"] = [
            *candidate["evidence_source"], f"{source_prefix}i_mpi_root_realpath.txt"
        ]


def _add_launcher_runtime_evidence(
    candidate: dict[str, object], root: Path, source_prefix: str,
) -> None:
    facts, conflicts = _dynamic_runtime_facts(root, "mpiexec_hydra_dynamic_dependencies")
    if facts:
        candidate["compatibility_facts"] = facts
        candidate["compatibility_fact_sources"] = {
            "mpi_runtime_instance": [f"{source_prefix}mpiexec_hydra_dynamic_dependencies_realpaths.txt"]
        }
        candidate["evidence_source"] = [
            *candidate["evidence_source"],
            f"{source_prefix}mpiexec_hydra_dynamic_dependencies.txt",
            f"{source_prefix}mpiexec_hydra_dynamic_dependencies.txt.exit_code",
            f"{source_prefix}mpiexec_hydra_dynamic_dependencies_realpaths.txt",
        ]
    if conflicts:
        candidate["compatibility_conflicts"] = conflicts


def _partitions(value: str | None) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for line_number, line in enumerate((value or "").splitlines(), 1):
        fields = line.split("|")
        if len(fields) != 6:
            continue
        name, availability, limit, nodes, cpus, memory = fields
        try:
            result.append({
                "name": name.rstrip("*"), "availability": availability, "time_limit": limit,
                "nodes": int(nodes), "cpus_per_node": int(cpus), "memory": int(memory),
                "default": name.endswith("*"), "source_file": "sinfo.txt", "source_line": line_number,
            })
        except ValueError:
            continue
    return result


def _associations(value: str | None, source: str) -> list[dict[str, object]]:
    """Preserve global sacctmgr associations without promoting queue evidence."""
    result: list[dict[str, object]] = []
    for line_number, line in enumerate((value or "").splitlines(), 1):
        fields = [field.strip() for field in line.strip("|").split("|")]
        if source == "squeue":
            if len(fields) < 5:
                continue
            partition, account, qos = fields[2], fields[3], fields[4]
            if not account or not partition:
                continue
            result.append({
                "account": account, "partition": partition.rstrip("*"), "qos": qos or None,
                "scope": "CURRENT_USER_QUEUE_EVIDENCE", "source": source,
                "source_file": "squeue.txt", "source_line": line_number,
            })
            continue
        if len(fields) < 2 or not fields[0]:
            continue
        account, partition = fields[0], fields[1]
        qos = fields[2] if len(fields) > 2 else None
        result.append({
            "account": account, "partition": partition.rstrip("*") or None, "qos": qos or None,
            "scope": "GLOBAL_USER_ASSOCIATION" if not partition else "PARTITION_SPECIFIC_ASSOCIATION",
            "source": source, "source_file": "sacctmgr_assoc.txt", "source_line": line_number,
        })
    return result


def _policy_values(value: str | None) -> dict[str, object]:
    values = (value or "").strip()
    if values.upper() == "ALL":
        return {"kind": "ALL", "values": []}
    return {"kind": "EXPLICIT_LIST", "values": [item for item in values.split(",") if item]}


def _policies(value: str | None) -> list[dict[str, object]]:
    """Parse only the scontrol fields M10 needs from `show partition -o`."""
    result: list[dict[str, object]] = []
    required = ("PartitionName", "State", "MinNodes", "MaxNodes", "MaxTime", "AllowAccounts", "AllowQos")
    for line_number, line in enumerate((value or "").splitlines(), 1):
        tokens = dict(re.findall(r"(PartitionName|State|MinNodes|MaxNodes|MaxTime|AllowAccounts|AllowQos)=([^\s]+)", line))
        if not all(field in tokens for field in required):
            continue
        try:
            min_nodes = int(tokens["MinNodes"])
            max_nodes = None if tokens["MaxNodes"].upper() == "UNLIMITED" else int(tokens["MaxNodes"])
        except ValueError:
            continue
        result.append({
            "name": tokens["PartitionName"].rstrip("*"), "state": tokens["State"],
            "min_nodes": min_nodes, "max_nodes": max_nodes, "max_time": tokens["MaxTime"],
            "allow_accounts": _policy_values(tokens["AllowAccounts"]),
            "allow_qos": _policy_values(tokens["AllowQos"]),
            "source_file": "scontrol_partitions.txt", "source_line": line_number,
        })
    return result


def _module_setup(probe: Path) -> list[str]:
    return [line for line in (_read(probe, "module_setup_commands.txt") or "").splitlines() if line]


def _observed_once(raw: Path, name: str, module: str) -> bool:
    return (raw / name).is_file() and (_read(raw, name) or "").splitlines().count(module) == 1


def _runtime_probe_is_bound(raw: Path, probe: Path, setup: list[str]) -> bool:
    python_module = _read(probe, "selected_python_module.txt")
    siesta_module = _read(probe, "selected_siesta_module.txt")
    if not python_module or not siesta_module:
        return False
    if not _observed_once(raw, "module_python_candidates.txt", python_module):
        return False
    if not _observed_once(raw, "module_siesta_candidates.txt", siesta_module):
        return False
    return setup == ["module purge", f"module load {python_module}", f"module load {siesta_module}"]


_RAW_LOGIN_PROBE_ARTIFACTS = (
    "observed_at.txt", "hostname.txt", "user.txt", "system.txt", "shell.txt",
    "path.txt", "working_path.txt", "environment_redacted.txt", "module_available.txt",
    "conda_available.txt", "spack_available.txt",
)
_RUNTIME_PROBE_ARTIFACTS = (
    "selected_python_module.txt", "selected_siesta_module.txt",
    "module_setup_commands.txt", "module_mechanism.exit_code",
)


def _validate_evidence_directory(path: Path, artifacts: tuple[str, ...], label: str) -> None:
    if not path.exists():
        raise ValueError(f"M10_LOGIN_SUMMARY_UNRESOLVED: {label} evidence directory missing")
    if not path.is_dir():
        raise ValueError(f"M10_LOGIN_SUMMARY_UNRESOLVED: {label} evidence path is not a directory")
    missing = [name for name in artifacts if not (path / name).is_file()]
    if missing:
        raise ValueError(f"M10_LOGIN_SUMMARY_UNRESOLVED: {label} evidence is incomplete: {', '.join(missing)}")


def _hydra_launcher_mechanisms(help_text: str) -> list[str]:
    """Extract the launcher mechanisms advertised by the observed Hydra help."""
    lines = help_text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^\s*-launcher(?:\s|$)", line):
            continue
        section = [line]
        for following in lines[index + 1:]:
            if re.match(r"^\s*-\w", following):
                break
            section.append(following)
        groups = re.findall(r"\(([^)]*)\)", "\n".join(section))
        mechanisms = [token for group in groups for token in re.findall(r"[A-Za-z0-9._-]+", group)]
        return list(dict.fromkeys(mechanisms))
    return []


def _module_candidates(raw: Path, probe: Path | None) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, list[dict[str, object]]]]:
    """Use only a successful explicit module probe as executable authority."""
    if probe is None:
        return [], [], {}
    setup = _module_setup(probe)
    if (
        not setup
        or not _runtime_probe_is_bound(raw, probe, setup)
        or _read(probe, "module_purge.exit_code") != "0"
        or _read(probe, "module_load_python.exit_code") != "0"
        or _read(probe, "module_load_siesta.exit_code") != "0"
    ):
        return [], [], {}
    commands = _commands(probe)
    environment = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in (_read(probe, "environment_redacted.txt") or "").splitlines() if "=" in line
    }
    source_prefix = "runtime_probe/"
    python_candidates = [
        {
            "selected_mechanism": "MODULE", "selected_executable": executable,
            "observed_version": _version(_read(probe, f"{name}_version.txt")),
            "environment_setup": setup,
            "evidence_source": [f"{source_prefix}module_setup_commands.txt", f"{source_prefix}command_{name}.txt", f"{source_prefix}{name}_version.txt"],
        }
        for name in ("python", "python3") if (executable := commands.get(name))
    ]
    siesta = commands.get("siesta")
    siesta_candidates = [] if not siesta else [{
        "selected_mechanism": "MODULE", "selected_executable": siesta,
        "observed_version": _version(_read(probe, "siesta_version.txt")) or "UNVERIFIED",
        "environment_setup": setup,
        "evidence_source": [f"{source_prefix}module_setup_commands.txt", f"{source_prefix}command_siesta.txt", f"{source_prefix}siesta_version.txt"],
    }]
    if siesta_candidates:
        _add_engine_runtime_evidence(siesta_candidates[0], probe, source_prefix)
    launchers: dict[str, list[dict[str, object]]] = {}
    srun = commands.get("srun")
    if srun:
        launchers["srun"] = [{
            "selected_mechanism": "MODULE", "selected_executable": srun, "arguments": [],
            "environment_setup": setup,
            "evidence_source": [f"{source_prefix}module_setup_commands.txt", f"{source_prefix}command_srun.txt"],
        }]
    hydra = commands.get("mpiexec.hydra")
    if hydra:
        help_text = _read(probe, "mpiexec_hydra_help.txt") or ""
        candidate: dict[str, object] = {
            "selected_mechanism": "MODULE", "selected_executable": hydra, "arguments": [],
            "observed_launcher_mechanisms": _hydra_launcher_mechanisms(help_text),
            "bootstrap_selection_required": "I_MPI_HYDRA_BOOTSTRAP" not in environment,
            "environment_setup": setup,
            "evidence_source": [f"{source_prefix}module_setup_commands.txt", f"{source_prefix}command_mpiexec_hydra.txt", f"{source_prefix}mpiexec_hydra_help.txt"],
        }
        bootstrap = environment.get("I_MPI_HYDRA_BOOTSTRAP")
        if bootstrap:
            candidate["bootstrap"] = bootstrap
            candidate["evidence_source"] = [*candidate["evidence_source"], f"{source_prefix}environment_redacted.txt"]
        _add_launcher_runtime_evidence(candidate, probe, source_prefix)
        launchers["mpiexec.hydra"] = [candidate]
    return python_candidates, siesta_candidates, launchers


def build(raw: Path, runtime_probe: Path | None = None) -> dict[str, object]:
    _validate_evidence_directory(raw, _RAW_LOGIN_PROBE_ARTIFACTS, "raw login probe")
    if runtime_probe is not None:
        _validate_evidence_directory(runtime_probe, _RUNTIME_PROBE_ARTIFACTS, "runtime candidate probe")
    commands = _commands(raw)
    environment = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in (_read(raw, "environment_redacted.txt") or "").splitlines() if "=" in line
    }
    python_candidates: list[dict[str, object]] = []
    for name in ("python", "python3"):
        executable = commands.get(name)
        if executable:
            python_candidates.append({
                "selected_mechanism": "PATH", "selected_executable": executable,
                "observed_version": _version(_read(raw, f"{name}_version.txt")), "environment_setup": [],
                "evidence_source": [f"command_{name}.txt", f"{name}_version.txt"],
            })
    siesta = commands.get("siesta")
    siesta_candidates: list[dict[str, object]] = [] if not siesta else [{
        "selected_mechanism": "PATH", "selected_executable": siesta,
        "observed_version": _version(_read(raw, "siesta_version.txt")) or "UNVERIFIED", "environment_setup": [],
        "evidence_source": ["command_siesta.txt", "siesta_version.txt"],
    }]
    if siesta_candidates:
        _add_engine_runtime_evidence(siesta_candidates[0], raw, "")
    launchers: dict[str, list[dict[str, object]]] = {}
    for name in ("srun", "mpiexec.hydra"):
        executable = commands.get(name)
        if executable:
            candidate: dict[str, object] = {
                "selected_mechanism": "PATH", "selected_executable": executable, "arguments": [],
                "observed_launcher_mechanisms": _hydra_launcher_mechanisms(_read(raw, "mpiexec_hydra_help.txt") or "") if name == "mpiexec.hydra" else [],
                "bootstrap_selection_required": name == "mpiexec.hydra" and "I_MPI_HYDRA_BOOTSTRAP" not in environment,
                "environment_setup": [], "evidence_source": [f"command_{name.replace('.', '_')}.txt"],
            }
            if name == "mpiexec.hydra":
                bootstrap = environment.get("I_MPI_HYDRA_BOOTSTRAP")
                if bootstrap:
                    candidate["bootstrap"] = bootstrap
                    candidate["evidence_source"] = [*candidate["evidence_source"], "mpiexec_hydra_help.txt", "environment_redacted.txt"]
                _add_launcher_runtime_evidence(candidate, raw, "")
            launchers[name] = [candidate]
    module_python, module_siesta, module_launchers = _module_candidates(raw, runtime_probe)
    python_candidates.extend(module_python)
    siesta_candidates.extend(module_siesta)
    for name, candidates in module_launchers.items():
        launchers.setdefault(name, []).extend(candidates)
    return {
        "schema_version": "1.0", "raw_evidence_status": "OBSERVED", "observed_at": _read(raw, "observed_at.txt"),
        "hostname": _read(raw, "hostname.txt"), "user": _read(raw, "user.txt"), "system": _read(raw, "system.txt"),
        "shell": _read(raw, "shell.txt"), "working_path": _read(raw, "working_path.txt"),
        "commands": commands, "environment": environment,
        "module_available": _read(raw, "module_available.txt") == "true",
        "conda_available": _read(raw, "conda_available.txt") == "true",
        "spack_available": _read(raw, "spack_available.txt") == "true",
        "python_candidates": python_candidates, "siesta_candidates": siesta_candidates,
        "launcher_candidates": launchers,
        "module_candidates": {"python": (_read(raw, "module_python_candidates.txt") or "").splitlines(), "siesta": (_read(raw, "module_siesta_candidates.txt") or "").splitlines()},
        "runtime_probe": None if runtime_probe is None else {"path": str(runtime_probe), "status": "VERIFIED" if module_python or module_siesta else "NOT_EXECUTABLE_EVIDENCE"},
        "eligible_associations": _associations(_read(raw, "sacctmgr_assoc.txt"), "sacctmgr") + _associations(_read(raw, "squeue.txt"), "squeue"),
        "visible_partitions": _partitions(_read(raw, "sinfo.txt")), "partition_policies": _policies(_read(raw, "scontrol_partitions.txt")),
        "scheduler_diagnostics": {"sacctmgr_exit_code": _read(raw, "sacctmgr_assoc.txt.exit_code"), "squeue_exit_code": _read(raw, "squeue.txt.exit_code")},
        "scientific_calculation_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--runtime-probe", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: refusing to overwrite summary: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build(args.raw, args.runtime_probe), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
