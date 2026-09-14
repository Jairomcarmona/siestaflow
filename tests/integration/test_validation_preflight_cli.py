from __future__ import annotations

import hashlib
import json
from pathlib import Path

from qraft.cli import main

from tests.validation_fixture import BASE_FDF


def _write_workflow(root: Path, fdf_text: str = BASE_FDF) -> tuple[Path, Path]:
    inputs = root / "inputs"
    inputs.mkdir()
    fdf = inputs / "system.fdf"
    fdf.write_text(fdf_text, encoding="utf-8")
    definition = {
        "schema_version": "1.0",
        "workflow_id": "validation-preflight",
        "project_id": "validation-project",
        "tasks": [
            {
                "task_id": "single-point",
                "kind": "calculation",
                "capability": "siestaflow.engine.siesta",
                "inputs": [
                    {
                        "name": "fdf",
                        "source": "inputs/system.fdf",
                        "destination": "system.fdf",
                        "media_type": "text/x-siesta-fdf",
                    }
                ],
                "outputs": [
                    {
                        "name": "density",
                        "path": "validation_fixture.DM",
                        "artifact_type": "siesta.density-matrix",
                        "media_type": "application/x-siesta-dm",
                    }
                ],
                "resources": {
                    "nodes": 1,
                    "mpi_processes": 1,
                    "processes_per_node": 1,
                    "cpus_per_process": 1,
                    "walltime_seconds": 60,
                },
            }
        ],
    }
    path = root / "workflow.json"
    path.write_text(
        json.dumps(definition, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path, fdf


def test_input_rules_and_contextual_validation_cli(capsys, tmp_path: Path) -> None:
    fdf = tmp_path / "valid.fdf"
    fdf.write_text(BASE_FDF, encoding="utf-8")

    assert main(["input", "rules", "--json"]) == 0
    rules = json.loads(capsys.readouterr().out)
    assert rules["engine_version"] == "5.4.2"
    assert rules["rules"]

    assert (
        main(
            [
                "input",
                "validate",
                str(fdf),
                "--engine-version",
                "5.4.2",
                "--explain",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS"
    assert report["metadata"]["execution_authorized"] is False


def test_workflow_preflight_is_read_only_and_hash_bound(
    capsys,
    tmp_path: Path,
) -> None:
    definition, fdf = _write_workflow(tmp_path)
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (definition, fdf)
    }

    assert main(["workflow", "preflight", str(definition), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["status"] == "PASS"
    assert report["subject"]["attributes"]["siesta_fdf_count"] == 1
    assert report["metadata"]["filesystem_changes"] == 0
    assert before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (definition, fdf)
    }
    assert sorted(tmp_path.rglob("*")) == sorted(
        [tmp_path / "inputs", definition, fdf]
    )


def test_workflow_preflight_blocks_invalid_external_fdf(
    capsys,
    tmp_path: Path,
) -> None:
    definition, _ = _write_workflow(
        tmp_path,
        BASE_FDF.replace("  0.0 0.0 18.0", "  0.0 0.0 0.0"),
    )

    assert main(["workflow", "preflight", str(definition), "--json"]) == 2
    report = json.loads(capsys.readouterr().out)

    assert report["status"] == "FAIL"
    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "LATTICE_MATRIX_SINGULAR"
    )
    assert finding["data"]["artifact_id"]
    assert len(finding["data"]["artifact_sha256"]) == 64
    assert finding["location"].startswith("inputs/system.fdf:")


def test_cli_profile_can_require_bader_without_mutating_input(
    capsys,
    tmp_path: Path,
) -> None:
    fdf = tmp_path / "valid.fdf"
    profile = tmp_path / "profile.json"
    fdf.write_text(BASE_FDF, encoding="utf-8")
    profile.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "profile_id": "final-bader",
                "periodicity": "slab",
                "required_outputs": ["bader"],
            }
        ),
        encoding="utf-8",
    )
    original = fdf.read_bytes()

    assert (
        main(
            [
                "input",
                "validate",
                str(fdf),
                "--profile",
                str(profile),
                "--json",
            ]
        )
        == 2
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED"
    assert "BADER_OUTPUT_NOT_ENABLED" in {
        item["code"] for item in report["findings"]
    }
    assert fdf.read_bytes() == original
