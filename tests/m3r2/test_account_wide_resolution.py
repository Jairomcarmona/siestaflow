from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qraft.remote_environment import EnvironmentProbePackager
from qraft.validation.scheduler_resolution import (
    AssociationScope,
    ResourceRequest,
    apply_human_selection,
    parse_sacctmgr_associations,
    parse_scontrol_partitions,
    parse_sinfo_partitions,
    resolve_scheduler_candidates,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "m3r2" / "yoltla_account_wide_association"


def parse_fixture():
    associations, ad = parse_sacctmgr_associations((FIXTURE / "sacctmgr_assoc.txt").read_text(), observed_at="2026-07-21T00:00:00Z")
    visible, vd = parse_sinfo_partitions((FIXTURE / "sinfo.txt").read_text())
    policies, pd = parse_scontrol_partitions((FIXTURE / "scontrol_partitions.txt").read_text())
    return associations, visible, policies, ad + vd + pd


@pytest.mark.parametrize(
    "row,scope,partition,qos",
    [
        ("acct|part|qos", AssociationScope.EXPLICIT_PARTITION_ASSOCIATION.value, "part", "qos"),
        ("acct||qos", AssociationScope.ACCOUNT_WIDE_ASSOCIATION.value, None, "qos"),
        ("acct|part|", AssociationScope.EXPLICIT_PARTITION_ASSOCIATION.value, "part", None),
        ("acct||", AssociationScope.ACCOUNT_WIDE_ASSOCIATION.value, None, None),
    ],
)
def test_association_forms(row, scope, partition, qos):
    values, diagnostics = parse_sacctmgr_associations(row)
    assert diagnostics == []
    assert values[0].scope == scope and values[0].partition == partition and values[0].qos == qos


def test_missing_account_is_preserved_as_diagnostic():
    values, diagnostics = parse_sacctmgr_associations("||qos")
    assert values[0].scope == AssociationScope.QOS_ONLY_ASSOCIATION.value
    assert values[0].evidence_status == "MISSING"
    assert diagnostics[0]["code"] == "SACCTMGR_ASSOCIATION_ACCOUNT_REQUIRED"


def test_real_sanitized_fixture_resolves_unique_default():
    associations, visible, policies, diagnostics = parse_fixture()
    assert diagnostics == []
    assert associations[0].partition is None and associations[0].scope == AssociationScope.ACCOUNT_WIDE_ASSOCIATION.value
    assert visible[0].default is True and "*" not in visible[0].name
    assert policies[0].allow_accounts["kind"] == policies[0].allow_qos["kind"] == "ALL"
    result = resolve_scheduler_candidates(associations, visible, policies, ResourceRequest())
    expected = json.loads((FIXTURE / "expected_selection.json").read_text())
    assert result["status"] == "DEFAULT_PARTITION_RESOLVED_FROM_REAL_EVIDENCE"
    assert result["selection_policy"] == expected["selection_policy"]
    assert {k: result["selected"][k] for k in ("account", "partition", "qos", "association_scope")} == {k: expected[k] for k in ("account", "partition", "qos", "association_scope")}


def synthetic(policy="PartitionName=p AllowAccounts=ALL AllowQos=ALL Default=YES State=UP MinNodes=1 MaxNodes=2 MaxTime=00:10:00", sinfo="p*|up|00:10:00|1|1|1024", assoc="a||q"):
    aa, _ = parse_sacctmgr_associations(assoc); vv, _ = parse_sinfo_partitions(sinfo); pp, _ = parse_scontrol_partitions(policy)
    return resolve_scheduler_candidates(aa, vv, pp)


@pytest.mark.parametrize(
    "policy,reason",
    [
        ("PartitionName=p AllowAccounts=other AllowQos=ALL Default=YES State=UP MinNodes=1 MaxNodes=2 MaxTime=00:10:00", "ACCOUNT_NOT_ALLOWED"),
        ("PartitionName=p AllowAccounts=ALL AllowQos=other Default=YES State=UP MinNodes=1 MaxNodes=2 MaxTime=00:10:00", "QOS_NOT_ALLOWED"),
        ("PartitionName=p AllowAccounts=ALL AllowQos=ALL Default=YES State=DOWN MinNodes=1 MaxNodes=2 MaxTime=00:10:00", "PARTITION_NOT_UP"),
        ("PartitionName=p AllowAccounts=ALL AllowQos=ALL Default=YES State=UP MinNodes=2 MaxNodes=2 MaxTime=00:10:00", "MIN_NODES_INCOMPATIBLE"),
        ("PartitionName=p AllowAccounts=ALL AllowQos=ALL Default=YES State=UP MinNodes=1 MaxNodes=0 MaxTime=00:10:00", "MAX_NODES_INCOMPATIBLE"),
        ("PartitionName=p AllowAccounts=ALL AllowQos=ALL Default=YES State=UP MinNodes=1 MaxNodes=2 MaxTime=00:01:00", "WALLTIME_INCOMPATIBLE"),
    ],
)
def test_incompatible_policies_block(policy, reason):
    result = synthetic(policy=policy)
    assert result["status"] == "SCHEDULER_PROBE_BLOCKED_NO_COMPATIBLE_PARTITION"
    assert reason in result["rejected"][0]["rejection_reasons"]


def test_down_visibility_blocks():
    result = synthetic(sinfo="p*|down|00:10:00|1|1|1024")
    assert "PARTITION_NOT_AVAILABLE" in result["rejected"][0]["rejection_reasons"]


def test_multiple_defaults_and_no_default_never_choose_first():
    aa, _ = parse_sacctmgr_associations("a||q")
    vv, _ = parse_sinfo_partitions("p1*|up|01:00:00|1|1|1\np2*|up|01:00:00|1|1|1")
    pp, _ = parse_scontrol_partitions("PartitionName=p1 AllowAccounts=ALL AllowQos=ALL Default=YES State=UP MinNodes=1 MaxNodes=1 MaxTime=01:00:00\nPartitionName=p2 AllowAccounts=ALL AllowQos=ALL Default=YES State=UP MinNodes=1 MaxNodes=1 MaxTime=01:00:00")
    result = resolve_scheduler_candidates(aa, vv, pp)
    assert result["status"] == "SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS" and result["selected"] is None
    vv, _ = parse_sinfo_partitions("p1|up|01:00:00|1|1|1\np2|up|01:00:00|1|1|1")
    pp, _ = parse_scontrol_partitions("PartitionName=p1 AllowAccounts=ALL AllowQos=ALL Default=NO State=UP MinNodes=1 MaxNodes=1 MaxTime=01:00:00\nPartitionName=p2 AllowAccounts=ALL AllowQos=ALL Default=NO State=UP MinNodes=1 MaxNodes=1 MaxTime=01:00:00")
    result = resolve_scheduler_candidates(aa, vv, pp)
    assert result["status"] == "SCHEDULER_PROBE_REQUIRES_HUMAN_SELECTION" and result["selected"] is None


def test_default_requires_cross_source_agreement():
    result = synthetic(policy="PartitionName=p AllowAccounts=ALL AllowQos=ALL Default=NO State=UP MinNodes=1 MaxNodes=2 MaxTime=00:10:00")
    assert result["status"] == "SCHEDULER_PROBE_REQUIRES_HUMAN_SELECTION"
    assert result["selected"] is None


def test_evidence_bound_human_selection():
    result = synthetic(policy="PartitionName=p AllowAccounts=ALL AllowQos=ALL Default=NO State=UP MinNodes=1 MaxNodes=2 MaxTime=00:10:00", sinfo="p|up|00:10:00|1|1|1024")
    chosen = apply_human_selection(result, "a", "p", "q")
    assert chosen["selection_policy"] == "HUMAN_SELECTION_EVIDENCE_BOUND"
    with pytest.raises(ValueError, match="USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE"):
        apply_human_selection(result, "a", "unobserved", "q")


def test_generated_slurm_runtime_from_real_sanitized_fixture(tmp_path: Path):
    root = Path(EnvironmentProbePackager().package(tmp_path).destination)
    raw = root / "evidence/login_probe/raw"; raw.mkdir(parents=True)
    for name in ("sacctmgr_assoc.txt", "sinfo.txt", "scontrol_partitions.txt"):
        (raw / name).write_bytes((FIXTURE / name).read_bytes())
    (raw / "observed_at.txt").write_text("2026-07-21T00:00:00Z\n")
    summary = root / "evidence/login_probe/summary.json"
    subprocess.run([sys.executable, str(root / "scripts/build_login_summary.py"), "--raw", str(raw), "--output", str(summary)], check=True)
    output = root / "generated/submit_environment_probe.slurm"
    prepared = subprocess.run([sys.executable, str(root / "prepare_scheduler_probe.py"), "--login-evidence", str(summary), "--output", str(output)], text=True, capture_output=True)
    assert prepared.returncode == 0, prepared.stderr
    selection = json.loads((root / "generated/scheduler_selection.json").read_text())
    assert selection["selection_policy"] == "UNIQUE_COMPATIBLE_DEFAULT_PARTITION"
    env = dict(os.environ, SLURM_JOB_ID="1", SLURM_JOB_PARTITION=selection["partition"], SLURM_JOB_ACCOUNT=selection["account"], SLURM_JOB_QOS=selection["qos"], SLURM_NNODES="1", SLURM_NTASKS="1", SLURM_CPUS_PER_TASK="1")
    executed = subprocess.run(["bash", "-c", 'export SLURM_SUBMIT_DIR="$PWD"; bash generated/submit_environment_probe.slurm'], cwd=root, env=env, text=True, capture_output=True)
    assert executed.returncode == 0, executed.stderr
    scheduler = json.loads((root / "evidence/scheduler_probe/summary.json").read_text())
    assert scheduler["scientific_calculation_performed"] is False
    print("ACCOUNT_WIDE_ASSOCIATION_RUNTIME_PASS")
    print("DEFAULT_PARTITION_RESOLUTION_RUNTIME_PASS")
    print("GENERATED_SLURM_RUNTIME_PASS")


def test_v3_manifest_and_standalone_resolver_are_packaged(tmp_path: Path):
    root = Path(EnvironmentProbePackager().package(tmp_path).destination)
    manifest = json.loads((root / "probe_manifest.json").read_text())
    assert (manifest["package_revision"], manifest["reproducibility_epoch"], manifest["supersedes"]) == (3, "M3_STATIC_V3", "M3_STATIC_V2")
    assert (root / "scripts/scheduler_resolution.py").is_file()
