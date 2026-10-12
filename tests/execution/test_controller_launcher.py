"""Reject executable substitution before creating a controller supervisor."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from qraft.execution import controller_launcher as module
from qraft.execution.controller_launcher import ControllerLauncher
from qraft.execution.srun_launcher import StepLaunchSpec


@pytest.mark.parametrize("grace", [-1, float("nan"), float("inf")])
def test_grace_cannot_prevent_escalation_forever(grace):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        ControllerLauncher(grace_seconds=grace)


def test_command_is_checked_against_bound_resolved_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(module, "PidfdSignals", lambda: object())
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("unbound executable launched"))
    work = tmp_path / "work" / "hf1" / "attempt-0001"
    work.mkdir(parents=True)
    relative = "work/hf1/attempt-0001/.qraft/controller-reservation.json"
    spec = StepLaunchSpec("hf1", "attempt-0001", work, work / "unused",
        work / "stdout", work / "stderr", 1, 1, "arbitrary-substitute", ("--qraft-reservation", relative))
    launcher = ControllerLauncher(root=tmp_path)
    launcher.bind_attempt(spec, {"task_id": "hf1", "attempt_id": "attempt-0001"},
                          entrypoint=Path("/installed/declared-controller"))
    with pytest.raises(ValueError, match="resolved entrypoint"):
        launcher.launch(spec)
    assert not (work / "stdout").exists()
    assert not launcher.closure_proven("hf1", "attempt-0001")


@pytest.mark.parametrize("name", [
    "controller-reservation.json", "controller-supervisor-ready.json",
    "controller-closure.json", "controller-state-manifest.json",
])
def test_staged_attempt_ipc_cannot_become_a_closure_proof(tmp_path, monkeypatch, name):
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(module, "PidfdSignals", lambda: object())
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("staged IPC launched"))
    work = tmp_path / "work" / "hf1" / "attempt-0001"
    metadata = work / ".qraft"
    metadata.mkdir(parents=True)
    (metadata / name).write_text(
        '{"state":"CLOSED","method":"SUBREAPER_PIDFD","remaining":[]}', encoding="utf-8",
    )
    entrypoint = Path("/installed/declared-controller")
    relative = "work/hf1/attempt-0001/.qraft/controller-reservation.json"
    spec = StepLaunchSpec("hf1", "attempt-0001", work, work / "unused",
        work / "stdout", work / "stderr", 1, 1, str(entrypoint), ("--qraft-reservation", relative))
    launcher = ControllerLauncher(root=tmp_path)
    launcher.bind_attempt(spec, {"task_id": "hf1", "attempt_id": "attempt-0001"}, entrypoint=entrypoint)
    with pytest.raises(ValueError, match="IPC must be absent"):
        launcher.launch(spec)
    assert not (work / "stdout").exists()
    assert not launcher.closure_proven("hf1", "attempt-0001")
