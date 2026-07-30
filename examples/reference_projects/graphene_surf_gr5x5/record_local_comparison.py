#!/usr/bin/env python3
"""Record a no-overwrite technical comparison of isolated local runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from siestaflow.local_execution import compare_run_summaries
from siestaflow.project_packages import load_structured


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"REFUSING_OVERWRITE:{args.output}")
    labels = ("serial_control", "np2", "np4")
    summaries = {
        label: json.loads((args.runs_root / label / "evidence/summary.json").read_text())
        for label in labels
    }
    expected = load_structured(args.spec)["expected"]
    comparison = compare_run_summaries(summaries, reference="serial_control")
    comparison["expected"] = expected
    comparison["observed"] = {
        label: {
            "number_of_atoms": value["number_of_atoms"],
            "number_of_species": value["number_of_species"],
            "species": expected["species"],
            "run_id": value["run_id"],
            "input_hashes": value["input_hashes"],
        }
        for label, value in summaries.items()
    }
    if any(value["number_of_atoms"] != expected["number_of_atoms"] for value in summaries.values()):
        comparison["technical_acceptance"] = "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, sort_keys=True, indent=2) + "\n")
    print(args.output)
    return 0 if comparison["technical_acceptance"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
