from __future__ import annotations

import json
from pathlib import Path

import pytest

from qraft.execution.adaptive_gate import (
    consume_selection,
    main,
    select_metric,
    write_metric,
)


def metric(root: Path, name: str, value: str) -> Path:
    path = root / f"{name}.json"
    write_metric(path, variant_id=name, metric_name="score", metric_value=value)
    return path


def test_metric_is_canonical_and_preserves_decimal_text(tmp_path: Path) -> None:
    path = metric(tmp_path, "alpha", "2.500")
    assert json.loads(path.read_text()) == {
        "metric_name": "score",
        "metric_value": "2.500",
        "schema_version": "1.0",
        "variant_id": "alpha",
    }


@pytest.mark.parametrize("value", ["NaN", "Infinity", "not-a-number"])
def test_metric_rejects_nonfinite_or_malformed_values(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="finite decimal"):
        write_metric(
            tmp_path / "metric.json",
            variant_id="alpha",
            metric_name="score",
            metric_value=value,
        )


def test_minimum_selection_is_deterministic_and_ties_by_variant_id(tmp_path: Path) -> None:
    output = tmp_path / "selection.json"
    select_metric(
        output,
        inputs=[metric(tmp_path, "zeta", "1"), metric(tmp_path, "alpha", "1"), metric(tmp_path, "beta", "2")],
        metric_name="score",
        goal="minimum",
    )
    value = json.loads(output.read_text())
    assert [item["variant_id"] for item in value["candidates"]] == ["alpha", "beta", "zeta"]
    assert value["selected"] == {
        "metric_name": "score", "metric_value": "1", "variant_id": "alpha"
    }
    assert value["selection_reason"] == "minimum metric; ties resolved by variant_id"


def test_maximum_selection_uses_same_deterministic_tie_break(tmp_path: Path) -> None:
    output = tmp_path / "selection.json"
    select_metric(
        output,
        inputs=[metric(tmp_path, "zeta", "3"), metric(tmp_path, "alpha", "3")],
        metric_name="score",
        goal="maximum",
    )
    assert json.loads(output.read_text())["selected"]["variant_id"] == "alpha"


def test_selector_rejects_metric_identity_or_goal_mismatch(tmp_path: Path) -> None:
    wrong_metric = tmp_path / "wrong.json"
    write_metric(wrong_metric, variant_id="alpha", metric_name="other", metric_value="1")
    with pytest.raises(ValueError, match="metric identity mismatch"):
        select_metric(
            tmp_path / "selection.json",
            inputs=[wrong_metric, metric(tmp_path, "beta", "2")],
            metric_name="score",
            goal="minimum",
        )
    with pytest.raises(ValueError, match="goal must be"):
        select_metric(
            tmp_path / "selection.json",
            inputs=[metric(tmp_path, "alpha", "1"), metric(tmp_path, "beta", "2")],
            metric_name="score",
            goal="closest",
        )


@pytest.mark.parametrize("values", [["1"], ["1", "2", "3", "4"]])
def test_selector_requires_bounded_fan_in(tmp_path: Path, values: list[str]) -> None:
    with pytest.raises(ValueError, match="two or three"):
        select_metric(
            tmp_path / "selection.json",
            inputs=[metric(tmp_path, f"v{index}", value) for index, value in enumerate(values)],
            metric_name="score",
            goal="minimum",
        )


def test_invalid_metric_or_duplicate_variant_is_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"not":"a metric"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid metric schema"):
        select_metric(
            tmp_path / "selection.json",
            inputs=[metric(tmp_path, "alpha", "1"), invalid],
            metric_name="score",
            goal="minimum",
        )
    duplicate = tmp_path / "duplicate.json"
    write_metric(duplicate, variant_id="alpha", metric_name="score", metric_value="2")
    with pytest.raises(ValueError, match="unique variant_id"):
        select_metric(
            tmp_path / "selection.json",
            inputs=[metric(tmp_path, "alpha", "1"), duplicate],
            metric_name="score",
            goal="minimum",
        )


def test_consumer_preserves_selected_variant_and_rejects_tampering(tmp_path: Path) -> None:
    decision = tmp_path / "selection.json"
    select_metric(
        decision,
        inputs=[metric(tmp_path, "alpha", "2"), metric(tmp_path, "beta", "1")],
        metric_name="score",
        goal="minimum",
    )
    result = tmp_path / "result.json"
    consume_selection(result, selection=decision)
    assert json.loads(result.read_text())["selected_variant_id"] == "beta"
    data = json.loads(decision.read_text())
    data["selected"]["variant_id"] = "missing"
    decision.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="absent from provenance"):
        consume_selection(result, selection=decision)


@pytest.mark.parametrize("value", ["[]", "{\"schema_version\":\"9.0\"}"])
def test_consumer_rejects_malformed_decision_schema(tmp_path: Path, value: str) -> None:
    decision = tmp_path / "selection.json"
    decision.write_text(value, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid selection schema"):
        consume_selection(tmp_path / "result.json", selection=decision)


def test_cli_writes_metric_without_external_runtime(tmp_path: Path) -> None:
    output = tmp_path / "metric.json"
    assert main(["metric", "--output", str(output), "--variant-id", "a", "--metric-name", "score", "--metric-value", "4"]) == 0
    assert json.loads(output.read_text())["metric_value"] == "4"
