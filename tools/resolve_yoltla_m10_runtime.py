#!/usr/bin/env python3
"""Resolve reviewed M10 runtime choices from raw-login summary evidence."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping


PYTHON_REQUIREMENT = (3, 11)
SRUN_PLACEMENT = ["--nodes=2", "--ntasks=64", "--ntasks-per-node=32"]


def _version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str): return None
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", value)
    return None if match is None else (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _candidates(data: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    raw = data.get(key, [])
    if not isinstance(raw, list): return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _select(candidates: list[dict[str, Any]], executable: str | None, label: str) -> dict[str, Any]:
    matches = [item for item in candidates if executable is None or item.get("selected_executable") == executable]
    if len(matches) != 1:
        reason = "missing" if not matches else "ambiguous"
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: {label} candidate is {reason}; select an evidence-supported executable")
    selected = matches[0]
    if selected.get("selected_mechanism") not in {"PATH", "MODULE", "OTHER_EVIDENCE_BOUND"}:
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: {label} mechanism is not evidence-bound")
    if not isinstance(selected.get("selected_executable"), str) or not selected["selected_executable"]:
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: {label} executable missing")
    if not isinstance(selected.get("environment_setup", []), list) or not all(isinstance(x, str) and x.strip() for x in selected.get("environment_setup", [])):
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: {label} environment setup invalid")
    if not selected.get("evidence_source"):
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: {label} evidence missing")
    observed = selected["selected_executable"]
    selected["observed_path"] = observed
    selected["selected_executable"] = observed.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", selected["selected_executable"]):
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: {label} executable is unsafe")
    return selected


def resolve(summary_path: Path, *, python: str | None = None, siesta: str | None = None, srun: str | None = None, hydra: str | None = None, require_hydra: bool = False) -> dict[str, Any]:
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: cannot read login evidence: {summary_path}") from error
    if not isinstance(data, Mapping): raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: login evidence must be an object")
    selected_python = _select(_candidates(data, "python_candidates"), python, "Python")
    version = _version(selected_python.get("observed_version"))
    if version is None or version < PYTHON_REQUIREMENT:
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: Python evidence does not satisfy >=3.11")
    selected_siesta = _select(_candidates(data, "siesta_candidates"), siesta, "SIESTA")
    launchers = data.get("launcher_candidates", {})
    if not isinstance(launchers, Mapping): raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: launcher evidence missing")
    selected_srun = _select(_candidates(launchers, "srun"), srun, "srun")
    selected_srun["arguments"] = SRUN_PLACEMENT
    selected_srun["required"] = True
    result: dict[str, Any] = {"schema_version": "1.0", "status": "RESOLVED_FROM_CURRENT_CLUSTER_EVIDENCE", "python": {"requirement": ">=3.11", **selected_python}, "siesta": selected_siesta, "launchers": {"srun": selected_srun}}
    hydra_candidates = _candidates(launchers, "mpiexec.hydra")
    if require_hydra:
        selected_hydra = _select(hydra_candidates, hydra, "Hydra")
        arguments = selected_hydra.get("arguments", [])
        if not isinstance(arguments, list) or not arguments:
            raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: Hydra requires reviewed launcher arguments")
        if not isinstance(selected_hydra.get("bootstrap"), str) or not selected_hydra["bootstrap"]:
            raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: Hydra requires reviewed bootstrap strategy")
        selected_hydra["required"] = True
        result["launchers"]["hydra"] = selected_hydra
    elif hydra is not None:
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: --hydra requires --require-hydra")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-evidence", required=True, type=Path); parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python"); parser.add_argument("--siesta"); parser.add_argument("--srun"); parser.add_argument("--hydra"); parser.add_argument("--require-hydra", action="store_true")
    args = parser.parse_args()
    if args.output.exists(): raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: refusing to overwrite selection: {args.output}")
    result = resolve(args.login_evidence, python=args.python, siesta=args.siesta, srun=args.srun, hydra=args.hydra, require_hydra=args.require_hydra)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__": raise SystemExit(main())
