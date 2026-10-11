"""Installed ADR-017 containment fixture; all children are synthetic and owned."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import qraft
from qraft.execution.controller_entrypoint import ControllerExtension, resolve_controller_entrypoint
from qraft.execution.controller_files import read_controller_json
from qraft.execution.controller_launcher import ControllerLauncher
from qraft.execution.controller_processes import PidfdSignals, process_identity
from qraft.execution.srun_launcher import StepLaunchSpec


def run_fixture(root, mode):
    now = datetime.now(timezone.utc)
    attempt = root / "work" / "fixture" / "attempt-0001"
    attempt.mkdir(parents=True)
    descriptor_relative = (attempt / ".qraft" / "controller-reservation.json").relative_to(root).as_posix()
    descriptor = {
        "contract": "qraft.controller-reservation@1.0", "run_fingerprint": "d" * 64,
        "task_id": "fixture", "attempt_id": "attempt-0001", "attempt_number": 1,
        "authority_generation": None,
        "capability": {"capability_id": "consumer.controller.fixture", "version": "1.0.0", "plugin_version": "1.0.0"},
        "allocation": {"scheduler": "local", "allocation_id": "fixture-only"},
        "reserved": {"hosts": ["localhost"], "nodes": 1, "runtime_cpus": 4, "min_cpus": 4,
                     "scheduler_cpus_on_host": {"value": 4, "source": "LOCAL_PROFILE_DECLARATION"}},
        "inner": {"launcher_kind": "openmpi", "launcher_command": ["/synthetic/never-executed-mpirun"],
                  "processes_per_node": 4, "cpus_per_process": 1, "max_concurrent": 1, "environment": {}},
        "deadline": {"stop_launching_at": (now + timedelta(seconds=300)).isoformat().replace("+00:00", "Z"),
                     "hard_stop_at": (now + timedelta(seconds=310)).isoformat().replace("+00:00", "Z")},
        "paths": {"state_dir": "controller-state/fixture", "stop_request": "controller-state/fixture/stop-request.json",
                  "inner_ledger": "work/fixture/attempt-0001/.qraft/inner-ledger.jsonl",
                  "resume_verdict": "work/fixture/attempt-0001/.qraft/resume-verdict.json"},
        "previous_attempt": None,
    }
    executable = resolve_controller_entrypoint(ControllerExtension(
        "qraft-test-controller", "qraft-test-controller", ("openmpi",), "NONE",
    ))
    spec = StepLaunchSpec("fixture", "attempt-0001", attempt, attempt / "unused",
                          attempt / "stdout.txt", attempt / "stderr.txt", 1, 1, str(executable),
                          ("--qraft-reservation", descriptor_relative, "--mode", mode))
    launcher = ControllerLauncher(root=root, grace_seconds=.2)
    launcher.bind_attempt(spec, descriptor)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(launcher.launch, spec)
        if mode == "escaped":
            deadline = time.monotonic() + 10
            paths = [root / name for name in ("leader.pid", "escaped.pid", "double-fork.pid")]
            while not all(path.exists() for path in paths):
                if future.done() or time.monotonic() > deadline:
                    launcher.terminate_all()
                    raise AssertionError("synthetic descendants did not start: " + (attempt / "stderr.txt").read_text())
                time.sleep(.01)
            identities = [process_identity(int(path.read_text())) for path in paths]
            assert launcher.terminate_all() == ("attempt-0001",)
        outcome = future.result(timeout=15)
    assert launcher.closure_proven("fixture", "attempt-0001"), (attempt / "stderr.txt").read_text()
    closure = read_controller_json(attempt / ".qraft" / "controller-closure.json")
    assert closure == {"state": "CLOSED", "method": "SUBREAPER_PIDFD", "remaining": []}
    assert (attempt / ".qraft" / "controller-state-manifest.json").is_file()
    if mode == "escaped":
        assert outcome.terminated_by_controller
        for identity in identities:
            try:
                current = process_identity(identity.pid)
            except FileNotFoundError:
                continue
            assert current != identity, "owned escaped descendant survived closure"
    else:
        assert outcome.exit_code == (75 if mode == "refuse" else 0)
    return {"mode": mode, "closure": closure["state"], "exit_code": outcome.exit_code}


def main():
    assert sys.flags.isolated
    assert Path(qraft.__file__).is_relative_to(Path(sys.prefix)), "checkout import is forbidden"
    assert "PYTHONPATH" not in os.environ
    extension = ControllerExtension("qraft-test-controller", "qraft-test-controller", ("openmpi",), "NONE")
    if os.name == "nt":
        try:
            resolve_controller_entrypoint(extension)
        except ValueError as exc:
            assert str(exc) == "CONTROLLER_REQUIRES_POSIX"
        else:
            raise AssertionError("Windows admitted a POSIX controller")
        print(json.dumps({"windows_native": "CONTROLLER_REQUIRES_POSIX", "scientific_job": False}))
        return
    signals = PidfdSignals()
    foreign = subprocess.Popen([sys.executable, "-I", "-c", "import time;time.sleep(60)"])
    foreign_identity = process_identity(foreign.pid)
    try:
        results = []
        for mode in ("normal", "escaped", "refuse"):
            with tempfile.TemporaryDirectory(prefix="qraft-installed-supervisor-") as directory:
                results.append(run_fixture(Path(directory), mode))
            signals.signal_identity(foreign_identity, 0)
            assert foreign.poll() is None, "supervisor signalled an unrelated fixture"
        print(json.dumps({"installed": True, "isolated": True, "scientific_job": False,
                          "foreign_untouched": True, "results": results}))
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)


if __name__ == "__main__":
    main()
