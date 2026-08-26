from __future__ import annotations

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "src")]

from tools.build_yoltla_m10_acceptance import _copy_linux_text


def _selection(tmp_path: Path, *, qos: str | None = None) -> Path:
    path = tmp_path / "scheduler_selection.json"
    path.write_text(json.dumps({
        "account": "observed-account", "partition": "observed-partition", "qos": qos,
        "memory": "256000M", "nodes": 2, "ntasks": 64, "cpus_per_task": 1,
        "processes_per_node": 32, "walltime": "00:20:00",
        "source_files": ["sacctmgr_assoc.txt", "sinfo.txt", "scontrol_partitions.txt"],
        "evidence_status_by_field": {"account": "OBSERVED", "partition": "VERIFIED_BY_CROSS_SOURCE", "qos": "MISSING" if qos is None else "OBSERVED", "memory": "OBSERVED", "resource_shape": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE"},
        "resource_shape_status": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE",
    }, indent=2) + "\n", encoding="utf-8")
    return path


def _login_summary(tmp_path: Path, *, partitions: list[dict[str, object]] | None = None) -> Path:
    partition_rows = partitions or [{"name": "observed-partition", "default": True, "nodes": 2, "cpus_per_node": 64, "memory": 192000}]
    associations = []
    policies = []
    visible = []
    for number, row in enumerate(partition_rows, 1):
        name = str(row["name"])
        associations.append({"account": "observed-account", "partition": name, "qos": None, "scope": "EXPLICIT_PARTITION_ASSOCIATION", "source_file": "sacctmgr_assoc.txt", "source_line": number, "evidence_status": "OBSERVED", "observed_at": "2026-08-25T00:00:00Z"})
        visible.append({"name": name, "availability": "up", "time_limit": "01:00:00", "nodes": row["nodes"], "cpus_per_node": row["cpus_per_node"], "memory": row["memory"], "default": row["default"], "source_file": "sinfo.txt", "source_line": number})
        policies.append({"name": name, "allow_accounts": {"kind": "EXPLICIT_LIST", "values": ["observed-account"]}, "allow_qos": {"kind": "ALL", "values": []}, "default": row["default"], "state": "UP", "min_nodes": 1, "max_nodes": 4, "max_time": "01:00:00", "source_file": "scontrol_partitions.txt", "source_line": number})
    path = tmp_path / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"eligible_associations": associations, "visible_partitions": visible, "partition_policies": policies}, indent=2) + "\n", encoding="utf-8")
    return path


def _resolve(discovery: Path, summary: Path, output: Path, *selection: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(discovery / "resolve_m10_scheduler.py"), "--login-evidence", str(summary), "--output", str(output), *selection],
        cwd=output.parent,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
    )


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
    discovery = output / "scheduler_discovery"
    assert (discovery / "run_login_probe.sh").is_file()
    assert (discovery / "scripts" / "probe_common.sh").is_file()
    assert (discovery / "scripts" / "build_login_summary.py").is_file()
    assert (discovery / "scripts" / "scheduler_resolution.py").is_file()
    assert (discovery / "resolve_m10_scheduler.py").is_file()
    run_probe = discovery / "run_login_probe.sh"
    probe_common = discovery / "scripts" / "probe_common.sh"
    assert run_probe.read_bytes().startswith(b"#!/usr/bin/env bash\n")
    assert b"\r" not in run_probe.read_bytes()
    assert b"\r" not in probe_common.read_bytes()
    fixture = output / "scientific_fixture"
    source = REPO / "remote_validation" / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE"
    assert sha256((fixture / "input" / "smoke.fdf").read_bytes()).hexdigest() == sha256((source / "input" / "smoke.fdf").read_bytes()).hexdigest()
    assert sha256((fixture / "pseudopotentials" / "C.psml").read_bytes()).hexdigest() == sha256((source / "pseudopotentials" / "C.psml").read_bytes()).hexdigest()
    assert not list(output.rglob("submit.slurm"))


def test_linux_text_copy_normalizes_a_crlf_fixture(tmp_path: Path) -> None:
    source = tmp_path / "source.sh"
    destination = tmp_path / "destination.sh"
    source.write_bytes(b"#!/usr/bin/env bash\r\nset -euo pipefail\r\n")
    _copy_linux_text(source, destination)
    assert destination.read_bytes() == b"#!/usr/bin/env bash\nset -euo pipefail\n"


def test_self_contained_m10_resolver_uses_current_shape_and_observed_memory(tmp_path: Path) -> None:
    output, _ = _build(tmp_path)
    summary = _login_summary(tmp_path)
    selection = tmp_path / "current-selection.json"
    result = _resolve(output / "scheduler_discovery", summary, selection)
    assert result.returncode == 0, result.stderr
    payload = json.loads(selection.read_text(encoding="utf-8"))
    assert {field: payload[field] for field in ("nodes", "ntasks", "cpus_per_task", "processes_per_node", "walltime")} == {"nodes": 2, "ntasks": 64, "cpus_per_task": 1, "processes_per_node": 32, "walltime": "00:20:00"}
    assert payload["qos"] is None
    assert payload["memory"] == "192000M"
    assert payload["memory_source"] == {"source_file": "sinfo.txt", "source_line": 1, "observed_mb": 192000}
    assert payload["resource_shape_status"] == "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE"
    resolved, manifest = _build(tmp_path / "resolved", selection)
    assert manifest["scheduler_profile_status"] == "RESOLVED_FROM_CLUSTER_EVIDENCE"
    assert (resolved / "preflight" / "submit_m10_preflight.slurm").is_file()


def test_m10_resolver_requires_evidence_bound_human_selection_for_multiple_candidates(tmp_path: Path) -> None:
    output, _ = _build(tmp_path)
    summary = _login_summary(tmp_path, partitions=[
        {"name": "first", "default": True, "nodes": 2, "cpus_per_node": 32, "memory": 64000},
        {"name": "second", "default": True, "nodes": 2, "cpus_per_node": 32, "memory": 128000},
    ])
    automatic = _resolve(output / "scheduler_discovery", summary, tmp_path / "automatic.json")
    assert automatic.returncode != 0
    assert "SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS" in automatic.stderr
    selected = tmp_path / "selected.json"
    manual = _resolve(output / "scheduler_discovery", summary, selected, "--account", "observed-account", "--partition", "second")
    assert manual.returncode == 0, manual.stderr
    assert json.loads(selected.read_text(encoding="utf-8"))["partition"] == "second"


def test_m10_resolver_fails_closed_for_inadequate_placement_evidence(tmp_path: Path) -> None:
    output, _ = _build(tmp_path)
    for name, row in {
        "cpus": {"name": "small-cpu", "default": True, "nodes": 2, "cpus_per_node": 31, "memory": 64000},
        "nodes": {"name": "small-nodes", "default": True, "nodes": 1, "cpus_per_node": 32, "memory": 64000},
        "memory": {"name": "no-memory", "default": True, "nodes": 2, "cpus_per_node": 32, "memory": None},
    }.items():
        result = _resolve(output / "scheduler_discovery", _login_summary(tmp_path / name, partitions=[row]), tmp_path / f"{name}.json")
        assert result.returncode != 0
        assert "M10_REMOTE_PROFILE_UNRESOLVED" in result.stderr


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
    shell_files = [*output.rglob("*.sh"), *output.rglob("*.slurm")]
    assert shell_files
    assert all(b"\r" not in path.read_bytes() for path in shell_files)
    for name, payload in manifest["packages"].items():
        archive = Path(payload["zip_path"])
        extraction = tmp_path / f"extract-{name}"; extraction.mkdir()
        with ZipFile(archive) as handle:
            shell_members = [member for member in handle.namelist() if member.endswith((".sh", ".slurm"))]
            assert shell_members
            assert all(b"\r" not in handle.read(member) for member in shell_members)
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
