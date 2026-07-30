#!/usr/bin/env python3
"""Create evidence-bound gate drafts and require explicit human acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PSEUDOS = ("external/pseudopotentials/Mn.psml", "external/pseudopotentials/O.psml")


class GateError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise GateError(f"EVIDENCE_MUST_LIVE_INSIDE_PACKAGE:{path}") from exc


def draft_f0(profile: Path, output_directory: Path, scope: str) -> dict[str, object]:
    evidence = [
        ROOT / "inputs/base/M1_U0_FM.pilot.NO_PRODUCTION.fdf",
        ROOT / PSEUDOS[0],
        ROOT / PSEUDOS[1],
        profile.resolve(),
        ROOT / "scripts/runtime_preflight.py",
        ROOT / "scripts/profilectl.py",
    ]
    for item in evidence:
        if not item.is_file():
            raise GateError(f"F0_EVIDENCE_MISSING:{item}")
    gate = {
        "schema_version": "1.0",
        "gate_id": "F0_EXECUTION_AUTHORIZATION",
        "decision": None,
        "accepted_by": None,
        "accepted_at": None,
        "authorized_scope": scope,
        "output_directory": str(output_directory.resolve()),
        "runtime_conditions": [
            "SIESTA version must be exactly 5.4.2",
            "declared MPI backend must pass runtime_preflight inside allocation",
            "only allocated hosts and non-overlapping slots may be used",
        ],
        "evidence_sha256": {relative(item): sha(item) for item in evidence},
    }
    target = ROOT / "gates/decisions/F0_EXECUTION_AUTHORIZATION.json"
    atomic(target, gate)
    return {"status": "F0_DRAFT_REQUIRES_EXPLICIT_ACCEPTANCE", "path": str(target)}


def accept(gate_id: str, accepted_by: str) -> dict[str, object]:
    target = ROOT / "gates/decisions" / f"{gate_id}.json"
    if not target.is_file():
        raise GateError(f"GATE_DRAFT_MISSING:{gate_id}")
    gate = json.loads(target.read_text(encoding="utf-8"))
    if gate.get("decision") not in (None, "DRAFT"):
        raise GateError("GATE_ALREADY_DECIDED")
    if not accepted_by.strip():
        raise GateError("ACCEPTED_BY_REQUIRED")
    for name, expected in gate.get("evidence_sha256", {}).items():
        item = ROOT / name
        if not item.is_file() or sha(item) != expected:
            raise GateError(f"GATE_EVIDENCE_CHANGED:{name}")
    gate["decision"] = "ACCEPTED"
    gate["accepted_by"] = accepted_by.strip()
    gate["accepted_at"] = datetime.now(timezone.utc).isoformat()
    atomic(target, gate)
    return {"status": "GATE_ACCEPTED", "gate_id": gate_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft-f0")
    draft.add_argument("--profile", required=True, type=Path)
    draft.add_argument("--output-directory", required=True, type=Path)
    draft.add_argument("--scope", required=True)
    approve = sub.add_parser("accept")
    approve.add_argument("--gate", required=True)
    approve.add_argument("--accepted-by", required=True)
    args = parser.parse_args()
    try:
        result = (
            draft_f0(args.profile, args.output_directory, args.scope)
            if args.command == "draft-f0"
            else accept(args.gate, args.accepted_by)
        )
    except (GateError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
