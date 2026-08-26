from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


REPO = Path(__file__).resolve().parents[2]


def _selection(tmp_path: Path, *, qos: str | None = None) -> Path:
    path = tmp_path / "scheduler_selection.json"
    path.write_text(json.dumps({
        "account": "observed-account", "partition": "observed-partition", "qos": qos,
        "memory": "256000M", "nodes": 2, "ntasks": 64, "cpus_per_task": 1,
        "source_files": ["sacctmgr_assoc.txt", "sinfo.txt", "scontrol_partitions.txt"],
        "evidence_status_by_field": {"account": "OBSERVED", "partition": "VERIFIED_BY_CROSS_SOURCE", "qos": "MISSING" if qos is None else "OBSERVED"},
    }, indent=2) + "\n", encoding="utf-8")
    return path


def _build(tmp_path: Path, selection: Path | None = None) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "m10"
    env = os.environ.copy(); env["PYTHONPATH"] = str(REPO / "src")
    command = [sys.executable, "tools/build_yoltla_m10_acceptance.py", "--output", str(output)]
    if selection is not None:
        command.extend(("--scheduler-selection", str(selection)))
    result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return output, json.loads(result.stdout)


def test_unresolved_bundle_has_discovery_and_no_authoritative_submit(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path)
    assert manifest["scheduler_profile_status"] == "UNRESOLVED"
    assert manifest["scientific_submit_scripts_generated"] is False
    assert manifest["historical_hint"]["status"] == "HISTORICAL_ONLY_NOT_CURRENT_AUTHORITY"
    assert (output / "scheduler_discovery" / "scheduler_resolution.py").is_file()
    assert (output / "scientific_fixture" / "input" / "smoke.fdf").is_file()
    assert not list(output.rglob("submit.slurm"))


def test_resolved_bundle_requires_explicit_evidence_bound_selection(tmp_path: Path) -> None:
    output = tmp_path / "missing"
    env = os.environ.copy(); env["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run([sys.executable, "tools/build_yoltla_m10_acceptance.py", "--output", str(output), "--scheduler-selection", str(tmp_path / "absent.json")], cwd=REPO, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "M10_REMOTE_PROFILE_UNRESOLVED" in result.stderr


def test_resolved_bundle_uses_selection_provenance_without_qos_fallback(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path, _selection(tmp_path))
    selected = manifest["scheduler_selection"]
    assert selected["account"] == "observed-account"
    assert selected["partition"] == "observed-partition"
    assert selected["qos"] is None
    assert selected["evidence_status_by_field"]["qos"] == "MISSING"
    assert (output / selected["relative_path"]).is_file() and selected["sha256"]
    preflight = (output / "preflight" / "submit_m10_preflight.slurm").read_text(encoding="utf-8")
    assert "#SBATCH --partition=observed-partition" in preflight
    assert "#SBATCH --account=observed-account" in preflight
    assert "#SBATCH --qos=" not in preflight
    assert "#SBATCH --output=preflight/preflight.%j.out" in preflight
    assert "#SBATCH --error=preflight/preflight.%j.err" in preflight
    assert (output / "preflight").is_dir()
    assert "srun --nodes=2 --ntasks=2 --ntasks-per-node=1" in preflight
    assert "command -v python3" in preflight and "command -v siesta" in preflight


def test_resolved_packages_are_canonical_and_backend_equivalent(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path, _selection(tmp_path, qos="observed-qos"))
    equivalence = manifest["backend_equivalence"]
    assert equivalence["workflow_id_equal"] and equivalence["workflow_definition_sha256_equal"]
    assert equivalence["scientific_identity_equal"] and equivalence["execution_spec_different"]
    for name, payload in manifest["packages"].items():
        archive = Path(payload["zip_path"])
        extraction = tmp_path / f"extract-{name}"; extraction.mkdir()
        with ZipFile(archive) as handle:
            handle.extractall(extraction)
        root = extraction / payload["package_id"]
        verified = subprocess.run([sys.executable, "verify_package.py"], cwd=root, capture_output=True, text=True)
        assert verified.returncode == 0, verified.stderr
        worker = (root / "scripts" / "run_worker.py").read_text(encoding="utf-8")
        assert "CanonicalController" in worker and "AllocationController.from_file" not in worker
        assert (root / "provenance" / "scheduler_selection.json").is_file()


def test_continuation_and_runbook_require_a_terminal_human_barrier(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path, _selection(tmp_path))
    campaign = json.loads((output / "sources" / "continuation" / "campaign.json").read_text(encoding="utf-8"))
    allocations = manifest["continuation_external_allocations"]
    first, second = campaign["tasks"]
    assert allocations == {"first_seconds": 60, "second_seconds": 180, "same_package_root_and_config": True}
    assert first["estimated_runtime_seconds"] == 5 and second["estimated_runtime_seconds"] == 90
    assert campaign["resources"]["shutdown_margin_seconds"] == 10
    runbook = (REPO / "docs" / "validation" / "m10_hpc_portability_production_acceptance" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert runbook.index("CONTINUATION JOB #1") < runbook.index("HUMAN GATE") < runbook.index("CONTINUATION JOB #2")
    assert "sacct" in runbook and "sbatch --test-only" in runbook
