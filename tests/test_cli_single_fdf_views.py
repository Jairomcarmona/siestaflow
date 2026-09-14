"""Regression coverage for read-only views of canonical single-FDF runs."""
from __future__ import annotations

import hashlib
import json
import shlex
import sys
from pathlib import Path

import pytest

from qraft.cli import main
from qraft.protocols.single_fdf import execute_fdf_plan


@pytest.fixture
def completed_run(tmp_path: Path) -> Path:
    fdf = tmp_path / "calc.fdf"
    fdf.write_text("""SystemName View regression
SystemLabel views
NumberOfAtoms 1
NumberOfSpecies 1
MeshCutoff 200 Ry
NetCharge 0
Spin non-polarized
MD.TypeOfRun CG
MD.Steps 0
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10 0 0
0 10 0
0 0 10
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
%endblock AtomicCoordinatesAndAtomicSpecies
""", encoding="utf-8")
    (tmp_path / "C.psf").write_text("synthetic pseudo\n", encoding="utf-8")
    engine = tmp_path / "engine.py"
    engine.write_text(
        "import sys\nsys.stdin.read()\n"
        "print('Siesta started\\nSCF cycle 1\\nSCF converged\\nJob completed')\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    result = execute_fdf_plan(fdf, runs_root=runs, overrides={
        "launcher": "direct", "partition": "local", "executable": sys.executable,
        "executable_arguments": [str(engine)],
    })
    assert result["attempt"]["result"]["technical_validation"]["status"] == "PASS"
    return runs


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _json_view(command: str, runs: Path, capsys) -> dict:
    capsys.readouterr()
    assert main([command, "--runs-root", str(runs), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_completed_single_fdf_status_and_inventory_are_read_only(completed_run: Path, capsys) -> None:
    before = _snapshot(completed_run)
    status = _json_view("status", completed_run, capsys)
    assert status["state"] == "COMPLETED"
    assert status["progress"]["completed"] == status["progress"]["total"] == 1
    assert "results" in status["next_action"]
    assert status["runtime"]["status"] == "COMPLETED"
    results = _json_view("results", completed_run, capsys)
    present = {Path(item["path"]) for item in results["artifacts"] if item["status"] == "PRESENT"}
    for name in ("attempt.json", "stdout.txt", "stderr.txt", "workflow_runtime.json"):
        assert next(completed_run.rglob(name)) in present
    assert all(path.is_file() for path in present)
    assert _snapshot(completed_run) == before


def _save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    path.write_text(json.dumps({"schema_version": "1.0",
                                "payload": payload,
                                "sha256": hashlib.sha256(encoded.encode()).hexdigest()}), encoding="utf-8")


def test_multiple_runtimes_do_not_hide_failed_run(completed_run: Path, capsys) -> None:
    first = next(completed_run.glob("runtime/*/state/workflow_runtime.json"))
    wrapper = json.loads(first.read_text())
    payload = wrapper["payload"]
    payload["status"] = "FAILED"
    payload["tasks"]["run_siesta"]["status"] = "FAILED"
    _save_state(completed_run / "runtime" / "000-failed" / "state" / first.name, payload)
    status = _json_view("status", completed_run, capsys)
    assert status["state"] == "FAILED"
    assert status["progress"] == {"completed": 1, "total": 2}
    assert status["runtime"] is None
    assert len(status["runtimes"]) == 2


@pytest.mark.parametrize("corrupt", ["[]", "{}", '{"payload": {}}', "checksum"])
def test_corrupt_runtime_is_not_reported_not_started(completed_run: Path, capsys, corrupt: str) -> None:
    state = next(completed_run.glob("runtime/*/state/workflow_runtime.json"))
    if corrupt == "checksum":
        wrapper = json.loads(state.read_text())
        wrapper["sha256"] = "0" * 64
        corrupt = json.dumps(wrapper)
    state.write_text(corrupt, encoding="utf-8")
    before = _snapshot(completed_run)
    status = _json_view("status", completed_run, capsys)
    assert status["state"] == "UNREADABLE"
    assert status["progress"] is None
    assert _snapshot(completed_run) == before


def test_root_runtime_remains_supported(completed_run: Path, capsys) -> None:
    state = next(completed_run.glob("runtime/*/state/workflow_runtime.json"))
    destination = completed_run / "state" / state.name
    destination.parent.mkdir()
    state.rename(destination)
    status = _json_view("status", completed_run, capsys)
    assert status["state"] == "COMPLETED"
    assert status["runtime"]["path"] == str(destination)


def test_running_task_overrides_previous_completed_snapshot(completed_run: Path, capsys) -> None:
    state = next(completed_run.glob("runtime/*/state/workflow_runtime.json"))
    payload = json.loads(state.read_text())["payload"]
    payload["tasks"]["run_siesta"]["status"] = "RUNNING"
    _save_state(state, payload)
    status = _json_view("status", completed_run, capsys)
    assert status["state"] == "RUNNING"
    assert status["progress"] == {"completed": 0, "total": 1}


def test_corrupt_journal_is_reported_without_repair(completed_run: Path, capsys) -> None:
    state = next(completed_run.glob("runtime/*/state/workflow_runtime.json"))
    state.with_name("workflow_runtime.journal.jsonl").write_text("{invalid", encoding="utf-8")
    before = _snapshot(completed_run)
    assert _json_view("status", completed_run, capsys)["state"] == "UNREADABLE"
    assert _snapshot(completed_run) == before


def test_inventory_does_not_follow_external_evidence(completed_run: Path, capsys) -> None:
    outside = completed_run.parent / "outside.txt"
    outside.write_text("external evidence", encoding="utf-8")
    attempt = next(completed_run.rglob("attempt.json")).parent
    link = attempt / "outside.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    results = _json_view("results", completed_run, capsys)
    assert str(link) not in {item["path"] for item in results["artifacts"]}


@pytest.mark.parametrize("location", ["attempt", "runtime", "journal"])
@pytest.mark.parametrize("kind", ["cyclic", "dangling"])
def test_broken_evidence_links_do_not_break_views(
    completed_run: Path, capsys, location: str, kind: str,
) -> None:
    manifest = next(completed_run.rglob("attempt.json"))
    state = next(completed_run.glob("runtime/*/state/workflow_runtime.json"))
    link = {
        "attempt": manifest.parent / "broken.txt",
        "runtime": completed_run / "runtime" / "broken-runtime",
        "journal": state.with_name("workflow_runtime.journal.jsonl"),
    }[location]
    if link.exists():
        link.unlink()
    destination = link if kind == "cyclic" else link.with_name("missing-evidence")
    try:
        link.symlink_to(destination, target_is_directory=location == "runtime")
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    results = _json_view("results", completed_run, capsys)
    present = {item["path"] for item in results["artifacts"] if item["status"] == "PRESENT"}
    assert str(manifest) in present
    assert str(manifest.parent / "stdout.txt") in present
    assert str(link) not in present
    status = _json_view("status", completed_run, capsys)
    assert status["state"] == ("COMPLETED" if location == "attempt" else "UNREADABLE")


def test_runtime_next_action_quotes_root_with_spaces(completed_run: Path, capsys) -> None:
    spaced_root = completed_run.with_name("runs with spaces")
    completed_run.rename(spaced_root)
    status = _json_view("status", spaced_root, capsys)
    command = shlex.split(status["next_action"])
    assert command == ["qraft", "results", "--runs-root", str(spaced_root)]
    assert main(command[1:] + ["--json"]) == 0
    results = json.loads(capsys.readouterr().out)
    assert results["inventory_status"] == "RECORDED"
