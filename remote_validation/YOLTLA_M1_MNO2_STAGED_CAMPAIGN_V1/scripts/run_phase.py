#!/usr/bin/env python3
"""Run one prepared phase from inside its SLURM allocation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_phase.py CONTROLLER_JSON PHASE_ROOT")
    campaign = Path(sys.argv[1]).resolve()
    root = Path(sys.argv[2]).resolve()
    if os.environ.get("SLURM_SUBMIT_DIR") is None:
        raise SystemExit("SLURM_SUBMIT_DIR_NOT_SET")
    if Path(os.environ["SLURM_SUBMIT_DIR"]).resolve() != root:
        raise SystemExit("PHASE_ROOT_NOT_SLURM_SUBMIT_DIR")

    from siestaflow.execution.allocation_controller import (
        AllocationController,
        ExecutionStatus,
    )

    controller = AllocationController.from_file(campaign, root=root)
    status = controller.run()
    print(
        json.dumps(
            {
                "campaign_id": controller.config.campaign_id,
                "job_id": controller.slurm.job_id,
                "status": status.value,
                "summary": str(controller.summary_path),
                "login_node_persistent_process_required": False,
            },
            sort_keys=True,
        )
    )
    return 0 if status is ExecutionStatus.COMPLETED else 2


if __name__ == "__main__":
    raise SystemExit(main())

