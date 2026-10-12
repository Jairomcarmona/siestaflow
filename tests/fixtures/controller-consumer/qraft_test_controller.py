"""Synthetic installed controller: never invokes SIESTA or a scheduler."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from qraft.execution.controller_files import atomic_controller_json, read_controller_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qraft-reservation", required=True)
    parser.add_argument("--mode", choices=("normal", "escaped", "refuse", "runtime",
                        "runtime-resume", "runtime-refuse", "runtime-badledger"), default="normal")
    args = parser.parse_args()
    descriptor = read_controller_json(Path(args.qraft_reservation))
    state = Path(descriptor["paths"]["state_dir"])
    assert state.joinpath("owner.json").exists()
    assert os.environ["QRAFT_CONTROLLER_RESERVATION"] == args.qraft_reservation
    if args.mode == "refuse":
        return 75
    if args.mode == "normal":
        atomic_controller_json(state / "synthetic-checkpoint.json", {"native_id": "fixture:opaque"})
        return 0
    if args.mode.startswith("runtime"):
        ledger = Path(descriptor["paths"]["inner_ledger"])
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_bytes(b'{"invalid":true}\n' if args.mode == "runtime-badledger" else b'')
        previous = descriptor["previous_attempt"]
        if previous and args.mode == "runtime-refuse":
            atomic_controller_json(Path(descriptor["paths"]["resume_verdict"]), {
                "contract": "qraft.controller-resume-verdict@1.0",
                "task_id": descriptor["task_id"], "attempt_id": descriptor["attempt_id"],
                "previous_attempt_id": previous["attempt_id"],
                "decision": "REFUSE", "reason": "RESUME_EVIDENCE_INVALID",
                "checkpoint_identity": None, "check_resume": None,
                "blocking": [], "continuation": None, "scientific_effect": "NONE",
            })
            return 75
        atomic_controller_json(state / "synthetic-checkpoint.json", {"native_id": "fixture:opaque"})
        if args.mode in {"runtime", "runtime-badledger"} or previous:
            time.sleep(.15)
            print("synthetic-only:accepted")
            return 0
        # First attempt remains alive until its own supervisor requests stop.
        atomic_controller_json(ledger.with_name("runtime-controller-ready.json"), {"pid": os.getpid()})
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
        while True:
            time.sleep(.05)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    escaped_code = """
import os,signal,time
from pathlib import Path
signal.signal(signal.SIGTERM,signal.SIG_IGN)
os.setsid()
Path('escaped.pid').write_text(str(os.getpid()))
while True:time.sleep(.1)
"""
    double_fork_code = """
import os,signal,time
from pathlib import Path
signal.signal(signal.SIGTERM,signal.SIG_IGN)
if os.fork():os._exit(0)
os.setsid()
if os.fork():os._exit(0)
Path('double-fork.pid').write_text(str(os.getpid()))
while True:time.sleep(.1)
"""
    subprocess.Popen([sys.executable, "-I", "-c", escaped_code])
    subprocess.Popen([sys.executable, "-I", "-c", double_fork_code])
    Path("leader.pid").write_text(str(os.getpid()))
    while True:
        time.sleep(.1)


if __name__ == "__main__":
    raise SystemExit(main())
