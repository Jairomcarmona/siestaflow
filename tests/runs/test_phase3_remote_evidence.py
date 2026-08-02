from __future__ import annotations

import json
import hashlib
from pathlib import Path
import zipfile


FIXTURES = Path(__file__).parents[1] / "fixtures" / "phase3"
EVIDENCE = FIXTURES / "yoltla_job_781100"


def _json(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_yoltla_job_781100_proves_canonical_parent_dm_child_path() -> None:
    summary = _json("campaign_summary.json")
    parent = _json("01_parent-result-manifest.json")
    child = _json("02_restart_from_parent_dm-result-manifest.json")
    run = _json("run.lock.json")
    workflow = _json("workflow.lock.json")
    profile = _json("execution-profile.json")

    accounting = (EVIDENCE / "slurm-sacct-781100.txt").read_text(encoding="utf-8")
    assert "781100|phase3-yoltla-ttv3-mem128-r4-0a51e51|tt2d-80p|COMPLETED|0:0|" in accounting
    assert summary["status"] == "COMPLETED" and summary["completed_tasks"] == 2
    assert all(item["status"] == "COMPLETED" for item in summary["tasks"].values())

    assert parent["exit_code"] == 0 and parent["normal_termination"] and parent["scf_converged"]
    assert child["exit_code"] == 0 and child["normal_termination"] and child["scf_converged"]
    assert child["restart_evidence"] == {"dm_read_attempted": True, "dm_read_succeeded": True}

    transfer = child["transferred_inputs"][0]
    dm_sha = parent["artifacts"]["phase3_acceptance.DM"]
    assert transfer["sha256"] == transfer["evidence_sha256"] == transfer["destination_sha256_before_execution"] == dm_sha
    assert transfer["source_result_manifest_sha256"] == summary["tasks"]["01_parent"]["result_manifest_sha256"]
    assert "Attempting to read DM from file... Succeeded..." in (EVIDENCE / "child-dm-read-781100.txt").read_text(encoding="utf-8")

    payload = run["payload"]
    resolution = payload["metadata"]["execution_resolution"]
    assert payload["workflow_lock_sha256"] == workflow["content_sha256"]
    assert payload["metadata"]["source_identity"] == {"source_commit": "0a51e51e74decfba6de11a740c47c5770f45770a", "source_tree_dirty": False}
    assert (resolution["selected_nodes"], resolution["selected_total_ranks"], resolution["selected_ranks_per_node"]) == (4, 4, 1)
    assert profile["allocation"]["nodes"] == 4 and profile["allocation"]["total_cpus"] == 4
    verification = (EVIDENCE / "package-verification-781100.txt").read_text(encoding="utf-8")
    assert "SIESTAFLOW_CONTROLLER_PACKAGE_VERIFIED" in verification
    assert "NO_LOGIN_PERSISTENT_PROCESS_REQUIRED" in verification


def test_yoltla_job_781102_proves_remote_adversarial_matrix() -> None:
    evidence = FIXTURES / "yoltla_job_781102"
    matrix = json.loads((evidence / "phase3_adversarial_matrix.json").read_text(encoding="utf-8"))
    accounting = (evidence / "slurm-sacct-781102.txt").read_text(encoding="utf-8")
    stdout = (evidence / "slurm-stdout-781102.txt").read_text(encoding="utf-8")

    assert "781102|COMPLETED|0:0|00:00:03|tt[30-33]" in accounting
    assert matrix["status"] == "PASS"
    assert matrix["classification"] == "REAL_REMOTE_TECHNICAL_ADVERSARIAL_EVIDENCE"
    assert matrix["scientific_calculation_performed"] is False
    assert matrix["source_commit"] == "594e0e5"
    assert matrix["hosts"] == ["tt30", "tt31", "tt32", "tt33"]
    assert set(matrix["cases"]) == {
        "absent_dm_prevents_child",
        "altered_hash_prevents_child_launch",
        "failed_parent_blocks_child",
        "independent_tasks_use_disjoint_hosts",
        "interruption_is_recoverable",
    }
    assert all(case["status"] == "PASS" for case in matrix["cases"].values())
    assert matrix["cases"]["failed_parent_blocks_child"]["observed"]["child_attempts"] == 0
    assert matrix["cases"]["absent_dm_prevents_child"]["observed"]["child_attempts"] == 0
    assert matrix["cases"]["altered_hash_prevents_child_launch"]["observed"]["child"] == "FAILED_BEFORE_LAUNCH"
    assert matrix["cases"]["interruption_is_recoverable"]["observed"]["attempts"] == 2
    independent = matrix["cases"]["independent_tasks_use_disjoint_hosts"]["observed"]
    assert set(independent["left"]).isdisjoint(independent["right"])
    assert "PHASE3_ADVERSARIAL_MATRIX_PACKAGE_VERIFIED" in stdout
    assert "NO_SCIENTIFIC_CALCULATION_CONFIGURED" in stdout


def test_yoltla_audit_remediation_archives_are_hash_bound_and_complete() -> None:
    evidence = FIXTURES / "yoltla_audit_remediations"
    expected = {
        "phase3-adversarial-evidence-781106.zip": "e5cadf9d20efd8df31807a1ad194e5fda3a8d8daba00975edf627f89c9f9055e",
        "phase3-signal-resume-781111-781113-evidence.zip": "a094c30505783763969e4bc6f148a9a35ccb456cfc5495716687ed857556bc8e",
        "phase3-physical-placement-781115.zip": "cea352bd517b3d0e3b890f7574c265b5760dcb8023933d3ceec68778c73aa1f0",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((evidence / name).read_bytes()).hexdigest() == digest

    with zipfile.ZipFile(evidence / "phase3-adversarial-evidence-781106.zip") as archive:
        manifest = json.loads(archive.read("evidence/manifest-781106.json"))["files"]
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in manifest.items())
        report = json.loads(archive.read("results/phase3_adversarial_matrix.json"))
        assert report["job_id"] == "781106" and report["status"] == "PASS"
        assert all(case["status"] == "PASS" for case in report["cases"].values())

    with zipfile.ZipFile(evidence / "phase3-signal-resume-781111-781113-evidence.zip") as archive:
        manifest = archive.read("evidence/manifest-781111-781113.sha256").decode().splitlines()
        for line in manifest:
            expected_hash, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected_hash
        first = json.loads(archive.read("results/signal_resume_interrupt.json"))
        resumed = json.loads(archive.read("results/signal_resume_resume.json"))
        summary = json.loads(archive.read("results/campaign_summary.json"))
        accounting = archive.read("evidence/slurm-sacct-781111-781113.txt").decode()
        assert first["status"] == "INTERRUPTED" and resumed["status"] == "COMPLETED"
        assert summary["tasks"]["signal_target"]["attempts"] == 2
        assert '"event":"SHUTDOWN_SIGNAL"' in archive.read("evidence/events.jsonl").decode()
        assert "781111        COMPLETED      0:0" in accounting
        assert "781113        COMPLETED      0:0" in accounting

    with zipfile.ZipFile(evidence / "phase3-physical-placement-781115.zip") as archive:
        manifest = archive.read("evidence/manifest-781115.sha256").decode().splitlines()
        for line in manifest:
            expected_hash, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected_hash
        placement = archive.read("results/physical_placement.txt").decode()
        accounting = archive.read("evidence/slurm-sacct-781115.txt").decode()
        assert "left_observed=tt30,tt31" in placement and "right_observed=tt32,tt33" in placement
        assert "781115.0      COMPLETED      0:0" in accounting
        assert "781115.1      COMPLETED      0:0" in accounting
