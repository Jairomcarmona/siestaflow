#!/usr/bin/env python3
"""Run an externally described local smoke through QRAFT."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qraft.local_execution import (
    InputBinding,
    LocalExecutionProfile,
    LocalExecutor,
    LocalRunSpec,
)
from qraft.project_packages import load_structured


def binding(root: Path, value: dict[str, str]) -> InputBinding:
    return InputBinding(root / value["source"], value["destination"], value["sha256"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-file", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    data = load_structured(args.spec)
    profile = LocalExecutionProfile.from_file(args.profile_file, args.profile)
    result = LocalExecutor().run(LocalRunSpec(
        run_id=args.run_id,
        destination=args.destination,
        profile=profile,
        input_binding=binding(args.source_root, data["input"]),
        resources=tuple(binding(args.source_root, item) for item in data.get("resources", [])),
    ))
    print(json.dumps({
        "run_id": result.run_id,
        "exit_code": result.exit_code,
        "termination_class": result.termination_class,
        "summary_path": str(result.summary_path),
    }, sort_keys=True))
    return 0 if result.exit_code == 0 else result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
