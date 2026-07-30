from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


REPO = Path(__file__).resolve().parents[2]


def test_yoltla_acceptance_builder_produces_two_stage_hydra_package(tmp_path: Path):
    output = tmp_path / "acceptance"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_yoltla_v02_acceptance.py",
            "--output",
            str(output),
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    archive = Path(payload["zip_path"])
    assert archive.is_file()
    extraction = tmp_path / "extract"
    extraction.mkdir()
    with ZipFile(archive) as handle:
        handle.extractall(extraction)
    root = extraction / payload["package_id"]
    campaign = json.loads((root / "campaign.yaml").read_text())
    assert campaign["runtime"]["launcher"]["kind"] == "hydra"
    assert campaign["tasks"][1]["depends_on"] == ["01_parent"]
    assert campaign["tasks"][1]["transfers"][0]["artifact"].endswith(".DM")
    verified = subprocess.run(
        [sys.executable, "verify_package.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr
