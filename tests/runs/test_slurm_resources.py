from __future__ import annotations

import json
from pathlib import Path

import pytest

from siestaflow.cli import main
from siestaflow.slurm_resources import (
    build_snapshot,
    load_snapshot,
    parse_scontrol_nodes,
    parse_sinfo,
    parse_sjstat_c,
    resolve_candidates,
    write_snapshot,
)

from test_prepared_run import _profile, _sources
from siestaflow.execution_profile import SlurmExecutionProfile
from siestaflow.run_inspection import RunInspector
from siestaflow.workflows import WorkflowCompiler, load_run_lock, write_workflow_lock


SJSTAT_FIXTURE = Path(__file__).parents[1] / "fixtures" / "slurm" / "yoltla_sjstat_c.txt"


def _snapshot() -> dict:
    return build_snapshot(
        cluster_id="arbitrary-cluster",
        observed_at="2026-08-01T00:00:00Z",
        sjstat=(
            "alpha|up|4|2|2|8192|fast\n"
            "beta|up|4|0|2|8192|fast\n"
            "too-small|up|1|1|1|1024|slow\n"
        ),
        sacctmgr="vini||normal\n",
        scontrol_partitions=(
            "PartitionName=alpha AllowAccounts=ALL AllowQos=ALL State=UP MaxNodes=4 MaxTime=01:00:00\n"
            "PartitionName=beta AllowAccounts=ALL AllowQos=ALL State=UP MaxNodes=4 MaxTime=01:00:00\n"
            "PartitionName=too-small AllowAccounts=ALL AllowQos=ALL State=UP MaxNodes=1 MaxTime=00:01:00\n"
        ),
    )


def test_snapshot_is_serializable_and_names_are_data(tmp_path: Path) -> None:
    snapshot = _snapshot()
    path = tmp_path / "snapshot.json"
    digest = write_snapshot(snapshot, path)
    loaded, actual = load_snapshot(path)
    assert digest == actual and loaded == snapshot
    rows, diagnostics = parse_sjstat_c("any-name|up|2|0|64|256000|x\n")
    assert diagnostics == [] and rows[0]["partition"] == "any-name"


def test_real_yoltla_sjstat_rows_are_parsed_as_capacity_variants() -> None:
    text = SJSTAT_FIXTURE.read_text(encoding="utf-8")
    rows, diagnostics = parse_sjstat_c(text)
    assert diagnostics == []
    assert len(rows) == 40  # The supplied capture has 40 data rows and 4 headers.
    assert next(item for item in rows if item["partition"] == "tt2d-64p")["idle_nodes"] == 0
    assert [item["idle_nodes"] for item in rows if item["partition"] == "tt2d-80p"] == [11, 3]
    assert next(item for item in rows if item["partition"] == "qz2d-64p")["idle_nodes"] == 14
    default = next(item for item in rows if item["partition"] == "q1h-20p")
    assert default["default_partition"] is True and default["memory_mb"] == 64152
    assert rows == parse_sjstat_c(text)[0]


def test_sjstat_malformed_rows_still_fail_closed() -> None:
    rows, diagnostics = parse_sjstat_c("bad 128Mb twenty 1 1 1 traits\n")
    assert rows == [] and diagnostics[0]["code"] == "SJSTAT_ROW_INVALID"


def test_resolution_explains_rejection_and_preserves_zero_idle_capacity(tmp_path: Path) -> None:
    profile = SlurmExecutionProfile.load(_profile(tmp_path))
    result = resolve_candidates(profile=profile, snapshot=_snapshot(), required_features=("fast",))
    alpha = next(item for item in result["candidates"] if item["partition"] == "alpha")
    beta = next(item for item in result["candidates"] if item["partition"] == "beta")
    rejected = next(item for item in result["candidates"] if item["partition"] == "too-small")
    assert alpha["state"] == "COMPATIBLE"
    assert beta["state"] == "COMPATIBLE_NO_CURRENT_IDLE_CAPACITY"
    assert "INSUFFICIENT_CPUS_PER_NODE" in rejected["rejection_reasons"]
    assert "INSUFFICIENT_WALLTIME" in rejected["rejection_reasons"]
    assert [item["rank"] for item in result["candidates"]] == [1, 2, 3]


def test_partial_discovery_keeps_unknown_authorization_reviewable(tmp_path: Path) -> None:
    profile = SlurmExecutionProfile.load(_profile(tmp_path))
    snapshot = build_snapshot(cluster_id="x", observed_at="2026-08-01T00:00:00Z", sjstat="p|up|2|1|2|8192|\n")
    candidate = resolve_candidates(profile=profile, snapshot=snapshot)["candidates"][0]
    assert candidate["state"] == "REQUIRES_HUMAN_REVIEW"
    assert "UNKNOWN_REQUIRED_CAPABILITY" in candidate["review_codes"]
    sinfo, diagnostics = parse_sinfo("broken\npart*|up|00:10:00|2|2|8192\n")
    nodes, node_diagnostics = parse_scontrol_nodes("NodeName=n1 CPUTot=2 RealMemory=8192 State=IDLE\n")
    assert diagnostics and sinfo[0]["partition"] == "part" and not node_diagnostics and nodes[0]["node"] == "n1"


def test_candidate_requires_confirmation_and_produces_distinct_packages(tmp_path: Path) -> None:
    source = tmp_path / "source"; source.mkdir()
    definition = _sources(source)
    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    lock = tmp_path / "workflow.lock.json"; write_workflow_lock(compilation, lock)
    profile = _profile(tmp_path)
    snapshot_data = _snapshot()
    for variant in snapshot_data["partitions"]:
        variant["accounts"] = None
        variant["qos"] = None
    snapshot = tmp_path / "snapshot.json"; write_snapshot(snapshot_data, snapshot)
    common = ["run", "prepare", str(lock), "--source-root", str(source), "--profile", str(profile), "--snapshot", str(snapshot)]
    assert main([*common, "--candidate", "alpha:1", "--output", str(tmp_path / "no-confirm"), "--run-id", "no-confirm", "--json"]) == 2
    assert main([*common, "--candidate", "alpha:1", "--confirm", "--output", str(tmp_path / "out-a"), "--run-id", "resolved-a", "--json"]) == 0
    assert main([*common, "--candidate", "beta:1", "--confirm", "--output", str(tmp_path / "out-b"), "--run-id", "resolved-b", "--json"]) == 0
    package_a, package_b = tmp_path / "out-a" / "resolved-a", tmp_path / "out-b" / "resolved-b"
    _, run_a = load_run_lock(package_a / "run.lock.json")
    _, run_b = load_run_lock(package_b / "run.lock.json")
    assert run_a.workflow_lock_sha256 == run_b.workflow_lock_sha256
    assert run_a.envelope().content_sha256 != run_b.envelope().content_sha256
    assert (tmp_path / "out-a" / "resolved-a.zip").read_bytes() != (tmp_path / "out-b" / "resolved-b.zip").read_bytes()
    assert "#SBATCH --partition=alpha" in (package_a / "submit.slurm").read_text(encoding="utf-8")
    assert "#SBATCH --partition=beta" in (package_b / "submit.slurm").read_text(encoding="utf-8")
    assert (package_a / "protected" / "parent" / "fdf" / "parent.fdf").read_bytes() == (package_b / "protected" / "parent" / "fdf" / "parent.fdf").read_bytes()
    assert json.loads((package_a / "campaign.yaml").read_text()) ["tasks"][1]["transfers"] == json.loads((package_b / "campaign.yaml").read_text())["tasks"][1]["transfers"]
    assert RunInspector().inspect(package_a).status == "PREPARED_RUN_VERIFIED"
    resolution = json.loads((package_a / "run.lock.json").read_text())["payload"]["metadata"]["execution_resolution"]
    assert {"ACCOUNT_AUTHORIZATION_UNKNOWN", "QOS_AUTHORIZATION_UNKNOWN"}.issubset(resolution["pending_fields"])
