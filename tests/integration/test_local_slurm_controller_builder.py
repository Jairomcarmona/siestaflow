from __future__ import annotations

import json
from pathlib import Path

from tools.build_local_slurm_controller_acceptance import (
    PACKAGE_ID,
    materialize,
)


REPO = Path(__file__).resolve().parents[2]
TEST_SIESTA = "/opt/siesta/5.4.2/bin/siesta"


def test_local_campaign_is_non_scientific_and_uses_real_srun(tmp_path: Path):
    campaign_path = materialize(
        REPO,
        tmp_path,
        siesta_executable=TEST_SIESTA,
        account="researcher",
    )
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))

    assert campaign["campaign_id"] == PACKAGE_ID
    assert campaign["slurm"]["partition"] == "local"
    assert campaign["slurm"]["account"] == "researcher"
    assert campaign["runtime"]["siesta_executable"] == TEST_SIESTA
    assert "\\" not in campaign["runtime"]["siesta_executable"]
    assert campaign["runtime"]["launcher"] == {
        "kind": "srun",
        "command": ["srun"],
        "arguments": ["--mpi=pmix"],
    }
    assert "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE" in campaign["classification"]
    assert "YOLTLA_RUNTIME_NOT_VERIFIED" in campaign["classification"]


def test_local_campaign_transfers_parent_dm_to_restart(tmp_path: Path):
    campaign = json.loads(
        materialize(
            REPO,
            tmp_path,
            siesta_executable=TEST_SIESTA,
            account="researcher",
        ).read_text(encoding="utf-8")
    )
    parent, restart = campaign["tasks"]

    assert parent["required_artifacts"] == ["Gr5x5_clean_v01.DM"]
    assert restart["depends_on"] == ["01_parent"]
    assert restart["transfers"] == [
        {
            "from_task": "01_parent",
            "artifact": "Gr5x5_clean_v01.DM",
            "destination": "Gr5x5_clean_v01.DM",
        }
    ]
