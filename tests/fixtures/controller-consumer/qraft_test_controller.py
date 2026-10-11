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
    parser.add_argument("--mode", choices=("normal", "escaped", "refuse"), default="normal")
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
