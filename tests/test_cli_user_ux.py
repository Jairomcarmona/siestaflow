from __future__ import annotations

import json
from pathlib import Path

import pytest

from qraft.campaign_spec import CampaignSpec
from qraft.cli import _CAMPAIGN_TEMPLATE, main
from qraft.output import ExecutionSession, OutputModel, QraftOutputWriter


def _status_root(tmp_path: Path, *, campaign_status: str, downstream_status: str) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    payload = {
        "execution_state": campaign_status,
        "technical_validation": "INCOMPLETE" if campaign_status == "INTERRUPTED" else ("FAIL" if campaign_status == "FAILED" else "PASS"),
        "scientific_decision": "CONVERGED",
        "selected_point": 100,
        "points": [{"technical_status": "PASS"} for _ in range(3)],
        "downstream": {
            "status": downstream_status,
            "technical_validation": "INCOMPLETE" if downstream_status == "INTERRUPTED" else ("FAIL" if downstream_status == "FAILED" else "PASS"),
            "selected_parameter": {"name": "mesh_cutoff", "value": 100, "unit": "Ry"},
        },
    }
    (root / "campaign-result.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_init_creates_editable_schema_valid_template(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "campaign.yaml"
    assert main(["init", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert "pseudo_manifest: pseudos/manifest.yaml" in text
    assert "qraft validate campaign.yaml --siesta /path/to/siesta" in text
    assert "relaxation:" in text and "enabled: false" in text
    assert "Created campaign template:" in capsys.readouterr().out
    assert CampaignSpec.load(target).campaign_id == "my-siesta-campaign"


def test_init_refuses_to_overwrite_without_force(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "campaign.yaml"
    target.write_text("keep", encoding="utf-8")
    assert main(["init", str(target)]) == 2
    assert target.read_text(encoding="utf-8") == "keep"
    assert "use --force to overwrite" in capsys.readouterr().err
    assert main(["init", str(target), "--force"]) == 0
    assert target.read_text(encoding="utf-8") == _CAMPAIGN_TEMPLATE


@pytest.mark.parametrize(
    ("campaign_status", "downstream_status", "expected"),
    [
        ("COMPLETED", "COMPLETED", "Campaign: COMPLETED"),
        ("INTERRUPTED", "INTERRUPTED", "Resume available: yes"),
        ("FAILED", "FAILED", "Failure: FAIL"),
    ],
)
def test_status_human_output_is_compact_and_json_remains_complete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], campaign_status: str,
    downstream_status: str, expected: str,
) -> None:
    root = _status_root(tmp_path, campaign_status=campaign_status, downstream_status=downstream_status)
    assert main(["status", "--runs-root", str(root)]) == 0
    rendered = capsys.readouterr().out
    assert expected in rendered
    assert "Progress: 3/3 convergence points" in rendered
    assert "Selected MeshCutoff: 100 Ry" in rendered
    assert f"Relaxation: {downstream_status}" in rendered
    assert main(["status", "--runs-root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["campaign"]["execution_state"] == campaign_status
    assert payload["campaign"]["downstream"]["selected_parameter"]["value"] == 100


def test_human_qraft_out_hides_internal_fdf_run_command(tmp_path: Path) -> None:
    writer = QraftOutputWriter(tmp_path / "qraft.out")
    writer.initialize(OutputModel())
    writer.start_session(ExecutionSession(
        "session", 1, "NEW", "2026-09-03T00:00:00Z",
        "qraft _fdf-run campaign.yaml", None, str(tmp_path),
    ))
    text = writer.path.read_text(encoding="utf-8")
    assert "Command          : qraft run campaign.yaml" in text
    assert "_fdf-run" not in text
