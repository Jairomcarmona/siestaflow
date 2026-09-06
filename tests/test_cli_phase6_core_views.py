"""Phase 6 core read-only status, results, and examples views."""

from __future__ import annotations

import json
from pathlib import Path

from qraft.cli import command_spec, main


def _runs_root(root: Path, *, state: str = "INTERRUPTED") -> Path:
    runs = root / "runs"
    runs.mkdir()
    (runs / "campaign-result.json").write_text(json.dumps({
        "execution_state": state,
        "technical_validation": "INCOMPLETE",
        "scientific_decision": "NOT_EVALUATED",
        "points": [{"technical_status": "PASS"}, {"technical_status": "PENDING"}],
    }), encoding="utf-8")
    return runs


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_status_and_results_project_recorded_state_without_writes(tmp_path: Path, capsys) -> None:
    runs = _runs_root(tmp_path)
    before = _snapshot(tmp_path)
    assert main(["status", "--runs-root", str(runs)]) == 0
    human = capsys.readouterr().out
    assert "QRAFT STATUS" in human and "STATE        INTERRUPTED" in human
    assert "qraft resume" in human

    assert main(["results", "--runs-root", str(runs), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["inventory_status"] == "RECORDED"
    assert any(item["status"] == "PRESENT" for item in result["artifacts"])
    assert _snapshot(tmp_path) == before


def test_examples_topics_are_command_spec_backed_and_conservative(capsys) -> None:
    topics = {item.name: item for item in command_spec(("examples",)).example_topics}
    assert tuple(topics) == ("minimal", "convergence", "relaxation", "resume", "slurm")
    assert main(["examples", "convergence", "--json"]) == 0
    convergence = json.loads(capsys.readouterr().out)
    assert convergence["execution"].startswith("SYNTHETIC")
    assert main(["examples", "slurm"]) == 2
    assert "COMING_LATER" in capsys.readouterr().out


def test_core_views_emit_one_json_value_for_empty_defaults(capsys) -> None:
    assert main(["status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "NOT_STARTED"
    assert main(["results", "--json"]) == 0
    results = json.loads(capsys.readouterr().out)
    assert results["inventory_status"] == "NOT_EVALUATED"
