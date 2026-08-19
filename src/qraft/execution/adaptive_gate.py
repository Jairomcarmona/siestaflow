"""Deterministic, allocation-local gates for the Phase 4.1 fixture.

The module has no SIESTA or scheduler dependency.  It is copied as a
hash-bound package input by ``run prepare`` and executed by the controller's
existing direct launcher.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return parsed


def _decimal_text(value: object, *, field: str) -> str:
    parsed = _decimal(value, field=field)
    return format(parsed, "f")


def write_metric(
    output: Path, *, variant_id: str, metric_name: str, metric_value: object
) -> None:
    if not variant_id or not metric_name:
        raise ValueError("variant_id and metric_name are required")
    _write(
        output,
        {
            "metric_name": metric_name,
            "metric_value": _decimal_text(metric_value, field="metric_value"),
            "schema_version": "1.0",
            "variant_id": variant_id,
        },
    )


def _metric(path: Path, *, metric_name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid metric input: {path}") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "variant_id", "metric_name", "metric_value"
    }:
        raise ValueError(f"invalid metric schema: {path}")
    if value["schema_version"] != "1.0" or value["metric_name"] != metric_name:
        raise ValueError(f"metric identity mismatch: {path}")
    variant_id = value["variant_id"]
    if not isinstance(variant_id, str) or not variant_id:
        raise ValueError(f"invalid metric variant: {path}")
    return {
        "variant_id": variant_id,
        "metric_name": metric_name,
        "metric_value": _decimal_text(value["metric_value"], field="metric_value"),
    }


def select_metric(
    output: Path,
    *,
    inputs: Sequence[Path],
    metric_name: str,
    goal: str,
) -> None:
    if goal not in {"minimum", "maximum"}:
        raise ValueError("goal must be minimum or maximum")
    if not 2 <= len(inputs) <= 3:
        raise ValueError("selector requires two or three metric inputs")
    candidates = sorted(
        (_metric(path, metric_name=metric_name) for path in inputs),
        key=lambda item: item["variant_id"],
    )
    if len({item["variant_id"] for item in candidates}) != len(candidates):
        raise ValueError("selector inputs must have unique variant_id values")
    if goal == "minimum":
        selected = min(
            candidates,
            key=lambda item: (_decimal(item["metric_value"], field="metric_value"), item["variant_id"]),
        )
    else:
        selected = min(
            candidates,
            key=lambda item: (-_decimal(item["metric_value"], field="metric_value"), item["variant_id"]),
        )
    _write(
        output,
        {
            "candidates": candidates,
            "goal": goal,
            "metric_name": metric_name,
            "schema_version": "1.0",
            "selected": selected,
            "selection_reason": f"{goal} metric; ties resolved by variant_id",
        },
    )


def consume_selection(output: Path, *, selection: Path) -> None:
    try:
        value = json.loads(selection.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid selection input: {selection}") from exc
    expected = {
        "schema_version", "metric_name", "goal", "candidates", "selected", "selection_reason"
    }
    if not isinstance(value, dict) or set(value) != expected or value["schema_version"] != "1.0":
        raise ValueError("invalid selection schema")
    selected = value["selected"]
    if not isinstance(selected, dict):
        raise ValueError("selection is missing selected candidate")
    candidate_ids = {
        item.get("variant_id") for item in value["candidates"] if isinstance(item, dict)
    }
    if selected.get("variant_id") not in candidate_ids:
        raise ValueError("selected candidate is absent from provenance")
    _decimal(selected.get("metric_value"), field="selected.metric_value")
    _write(
        output,
        {
            "metric_name": value["metric_name"],
            "metric_value": selected["metric_value"],
            "schema_version": "1.0",
            "selected_variant_id": selected["variant_id"],
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    metric = commands.add_parser("metric")
    metric.add_argument("--output", required=True, type=Path)
    metric.add_argument("--variant-id", required=True)
    metric.add_argument("--metric-name", required=True)
    metric.add_argument("--metric-value", required=True)
    select = commands.add_parser("select")
    select.add_argument("--output", required=True, type=Path)
    select.add_argument("--input", required=True, action="append", type=Path)
    select.add_argument("--metric-name", required=True)
    select.add_argument("--goal", required=True, choices=("minimum", "maximum"))
    consume = commands.add_parser("consume")
    consume.add_argument("--output", required=True, type=Path)
    consume.add_argument("--selection", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "metric":
            write_metric(args.output, variant_id=args.variant_id, metric_name=args.metric_name, metric_value=args.metric_value)
        elif args.command == "select":
            select_metric(args.output, inputs=args.input, metric_name=args.metric_name, goal=args.goal)
        else:
            consume_selection(args.output, selection=args.selection)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI exercised through package.
    raise SystemExit(main())
