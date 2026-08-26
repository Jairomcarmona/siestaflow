from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


REPO = Path(__file__).resolve().parents[2]


def _build(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "m10"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run(
        [sys.executable, "tools/build_yoltla_m10_acceptance.py", "--output", str(output)],
        cwd=REPO, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return output, json.loads(result.stdout)


def test_m10_builder_builds_verifies_and_uses_only_canonical_workers(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path)
    for name, payload in manifest["packages"].items():
        archive = Path(payload["zip_path"])
        extraction = tmp_path / f"extract-{name}"
        extraction.mkdir()
        with ZipFile(archive) as handle:
            handle.extractall(extraction)
        root = extraction / payload["package_id"]
        verified = subprocess.run([sys.executable, "verify_package.py"], cwd=root, capture_output=True, text=True)
        assert verified.returncode == 0, verified.stderr
        worker = (root / "scripts" / "run_worker.py").read_text(encoding="utf-8")
        assert "CanonicalController" in worker
        assert "AllocationController.from_file" not in worker


def test_m10_backend_equivalence_and_preflight_shared_filesystem_gate(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path)
    equivalence = manifest["backend_equivalence"]
    assert equivalence["workflow_id_equal"]
    assert equivalence["workflow_definition_sha256_equal"]
    assert equivalence["scientific_identity_equal"]
    assert equivalence["execution_spec_different"]
    script = (output / "preflight" / "submit_m10_preflight.slurm").read_text(encoding="utf-8")
    assert "SLURM_SUBMIT_DIR" in script
    assert "srun --nodes=2 --ntasks=2 --ntasks-per-node=1" in script
    assert "sha256sum" in script
    assert "siesta --version" in script and "mpiexec.hydra" in script


def test_m10_continuation_boundary_is_deterministic_and_resumable(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path)
    campaign = json.loads((output / "sources" / "continuation" / "campaign.json").read_text(encoding="utf-8"))
    allocations = manifest["continuation_external_allocations"]
    assert allocations == {"first_seconds": 60, "second_seconds": 180, "same_package_root_and_config": True}
    assert campaign["resources"]["walltime"] == "00:03:00"
    assert campaign["resources"]["shutdown_margin_seconds"] == 10
    first, second = campaign["tasks"]
    assert first["task_id"] == "STAGE_A" and second["depends_on"] == ["STAGE_A"]
    assert first["estimated_runtime_seconds"] == 5
    assert second["estimated_runtime_seconds"] == 90
    assert "time.sleep(4)" in first["command"][-1]
    assert "time.sleep(2)" in second["command"][-1]
    assert allocations["first_seconds"] > first["estimated_runtime_seconds"] + campaign["resources"]["shutdown_margin_seconds"]
    assert allocations["first_seconds"] < second["estimated_runtime_seconds"] + campaign["resources"]["shutdown_margin_seconds"]
    assert allocations["second_seconds"] > second["estimated_runtime_seconds"] + campaign["resources"]["shutdown_margin_seconds"]
    assert first["kind"] == second["kind"] == "gate"
    package = output / "packages" / "continuation" / "QRAFT_M10_ALLOCATION_CONTINUATION_TECHNICAL"
    assert (package / "state").exists() is False
