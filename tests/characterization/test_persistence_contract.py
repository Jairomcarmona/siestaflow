"""Observed persistence, resume, and dry-run behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qef.engines.qe.runner import QERunner
from qef.legacy.core.convergence_controller import ConvergenceController
from qef.legacy.core.logger import audit_workspace
from utils import check_run_allowed, get_run_status, set_run_status


def test_run_status_uses_atomic_snapshot_and_keeps_transition_history(tmp_path: Path):
    set_run_status(str(tmp_path), "pending", "queued")
    set_run_status(str(tmp_path), "running", "job 42")

    payload = json.loads((tmp_path / ".status.json").read_text(encoding="utf-8"))
    assert get_run_status(str(tmp_path)) == "running"
    assert payload["history"] == [{"status": "pending", "at": payload["history"][0]["at"]}]
    assert not (tmp_path / ".status.json.tmp").exists()
    with pytest.raises(RuntimeError, match="running"):
        check_run_allowed(str(tmp_path))


def test_resume_accepts_a_tampered_or_unverified_checksum(tmp_path: Path):
    state = {
        "version": "2.0.0",
        "project_uuid": "characterization",
        "config_snapshot": {
            "base_input": str(tmp_path / "missing.in"),
            "ecut_values": [30, 40],
            "kpoints_values": ["2 2 1"],
            "mpi_cmd": None,
            "module_qe": "qe/test",
            "dry_run": True,
            "async_mode": False,
        },
        "state": {
            "phase": "IDLE",
            "iteration": 7,
            "current_job_id": None,
            "converged_ecut": None,
            "converged_kpts": None,
            "system_type": "unknown",
            "hubbard_u_recommended": False,
            "history": {"ecut": [], "kpoints": [], "hubbard": []},
        },
        "integrity": {"last_checksum_md5": "definitely-wrong", "is_dirty": True},
    }
    (tmp_path / ".qef_convergence_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    resumed = ConvergenceController.resume(tmp_path)

    assert resumed._state["iteration"] == 7


def test_audit_workspace_dry_run_does_not_intercept_general_writes(tmp_path: Path):
    target = tmp_path / "written-during-dry-run.txt"

    with audit_workspace(dry_run=True):
        target.write_text("side effect", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "side effect"


def test_modern_qe_runner_adapter_calls_controller_with_stale_keywords(tmp_path: Path):
    runner = QERunner(tmp_path, tmp_path / "base.in", [30, 40], ["2 2 1"], True)

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        runner.run()

