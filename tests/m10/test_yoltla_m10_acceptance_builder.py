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
from tools.build_yoltla_m10_login_summary import _hydra_launcher_mechanisms, build as build_login_summary
from tools.resolve_yoltla_m10_runtime import resolve as resolve_runtime
from qraft.execution.allocation_controller import load_controller_config
from qraft.execution.hydra_launcher import HydraLauncher
from qraft.execution.legacy_translation import translate_controller_config
from qraft.execution.srun_launcher import StepLaunchSpec


def _selection(
    tmp_path: Path, *, qos: str | None = None,
    account: str | None = "observed-account",
) -> Path:
    path = tmp_path / "scheduler_selection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "account": account, "partition": "observed-partition", "qos": qos,
        "memory": "256000M", "nodes": 2, "ntasks": 64, "cpus_per_task": 1,
        "processes_per_node": 32, "walltime": "00:20:00",
        "source_files": ["sacctmgr_assoc.txt", "sinfo.txt", "scontrol_partitions.txt"],
        "evidence_status_by_field": {"account": "OMITTED_WITH_SCHEDULER_DEFAULT_EVIDENCE" if account is None else "OBSERVED", "partition": "VERIFIED_BY_CROSS_SOURCE", "qos": "MISSING" if qos is None else "OBSERVED", "memory": "OBSERVED", "resource_shape": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE"},
        "resource_shape_status": "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE",
    }, indent=2) + "\n", encoding="utf-8")
    return path


def _runtime_selection(tmp_path: Path, *, python_version: str = "3.11.9", siesta: bool = True, hydra: bool = True, module: bool = False) -> Path:
    mechanism = "MODULE" if module else "PATH"
    setup = ["module load observed-python"] if module else []
    payload = {
        "schema_version": "1.0", "status": "RESOLVED_FROM_CURRENT_CLUSTER_EVIDENCE",
        "python": {"requirement": ">=3.11", "selected_mechanism": mechanism, "selected_executable": "observed-python", "observed_version": python_version, "evidence_source": ["current-evidence"], "environment_setup": setup},
        "siesta": {"selected_mechanism": mechanism, "selected_executable": "observed-siesta" if siesta else "", "observed_version": "5.4", "evidence_source": ["current-evidence"], "environment_setup": ["module load observed-siesta"] if module else []},
        "launchers": {"srun": {"required": True, "selected_executable": "observed-srun", "arguments": ["--nodes=2", "--ntasks=64", "--ntasks-per-node=32"], "evidence_source": ["current-evidence"], "environment_setup": []}},
    }
    if hydra:
        payload["launchers"]["hydra"] = {"required": True, "selected_executable": "observed-hydra", "arguments": [], "bootstrap": "slurm", "evidence_source": ["current-evidence"], "environment_setup": []}
    path = tmp_path / "runtime_selection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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


def _raw_login_evidence(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    files = {
        "observed_at.txt": "2026-08-27T00:00:00Z\n",
        "hostname.txt": "observed-login\n",
        "user.txt": "vini\n",
        "system.txt": "Linux observed\n",
        "shell.txt": "/bin/bash\n",
        "path.txt": "/usr/bin\n",
        "working_path.txt": "/observed/path\n",
        "environment_redacted.txt": "PATH=/usr/bin\n",
        "sacctmgr_assoc.txt": "vini||normal\n",
        "squeue.txt": "1|name|q4d-20p|vini|normal\n",
        "sinfo.txt": "q4d-20p|up|01:00:00|2|20|64000\ntt2d-64p|up|01:00:00|2|32|128000\nqz2d-64p|up|01:00:00|2|64|128000\nqz2d-128p|up|01:00:00|2|64|128000\ntt1d-128p|up|01:00:00|4|32|128000\n",
        "scontrol_partitions.txt": "\n".join((
            "PartitionName=q4d-20p State=UP MinNodes=1 MaxNodes=2 MaxTime=01:00:00 AllowAccounts=ALL AllowQos=ALL",
            "PartitionName=tt2d-64p State=UP MinNodes=2 MaxNodes=2 MaxTime=01:00:00 AllowAccounts=ALL AllowQos=ALL",
            "PartitionName=qz2d-64p State=UP MinNodes=1 MaxNodes=1 MaxTime=01:00:00 AllowAccounts=ALL AllowQos=ALL",
            "PartitionName=qz2d-128p State=UP MinNodes=2 MaxNodes=2 MaxTime=01:00:00 AllowAccounts=vini AllowQos=normal",
            "PartitionName=tt1d-128p State=UP MinNodes=4 MaxNodes=4 MaxTime=01:00:00 AllowAccounts=ALL AllowQos=ALL",
        )) + "\n",
        "module_python_candidates.txt": "python/3.11.9\n",
        "module_siesta_candidates.txt": "siesta/5.4.2\n",
        "module_available.txt": "true\n",
        "conda_available.txt": "false\n",
        "spack_available.txt": "false\n",
        "command_python.txt": "/usr/bin/python\n",
        "python_version.txt": "Python 2.7.5\n",
        "command_python3.txt": "/usr/bin/python3\n",
        "python3_version.txt": "Python 3.6.8\n",
        "command_srun.txt": "/usr/bin/srun\n",
    }
    for name, value in files.items():
        (raw / name).write_text(value, encoding="utf-8")
    return raw


def _runtime_probe_evidence(tmp_path: Path, *, python_version: str = "3.11.9", siesta: bool = True, hydra: bool = False, bootstrap: str | None = None) -> Path:
    probe = tmp_path / "runtime-probe"
    probe.mkdir(parents=True)
    files = {
        "selected_python_module.txt": "python/3.11.9\n",
        "selected_siesta_module.txt": "siesta/5.4.2\n",
        "module_setup_commands.txt": "module purge\nmodule load python/3.11.9\nmodule load siesta/5.4.2\n",
        "module_mechanism.exit_code": "0\n",
        "module_purge.exit_code": "0\n",
        "module_load_python.exit_code": "0\n",
        "module_load_siesta.exit_code": "0\n",
        "command_python3.txt": "/opt/python/bin/python3\n",
        "python3_version.txt": f"Python {python_version}\n",
        "command_srun.txt": "/usr/bin/srun\n",
    }
    if siesta:
        files.update({"command_siesta.txt": "/opt/siesta/bin/siesta\n", "siesta_version.txt": "SIESTA 5.4.2\n"})
    if hydra:
        files.update({"command_mpiexec_hydra.txt": "/opt/mpi/bin/mpiexec.hydra\n", "mpiexec_hydra_help.txt": "Hydra specific options:\n\n  Launch options:\n    -launcher\n        launcher to use\n        (ssh slurm rsh ll sge pbs pbsdsh pdsh srun lsf blaunch qrsh fork)\n    -n number\n    -ppn number\n"})
    if bootstrap:
        files["environment_redacted.txt"] = f"I_MPI_HYDRA_BOOTSTRAP={bootstrap}\n"
    for name, value in files.items():
        (probe / name).write_text(value, encoding="utf-8")
    return probe


def _hydra_policy_evidence(tmp_path: Path, bootstrap: str) -> Path:
    path = tmp_path / "hydra-policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "1.0", "bootstrap": bootstrap,
        "source_type": "ADMINISTRATIVE_POLICY", "source_reference": "reviewed-policy-record",
        "decision_text": f"Use the reviewed Hydra bootstrap policy: {bootstrap}.",
    }, indent=2) + "\n", encoding="utf-8")
    return path


def _bash_path(path: Path) -> str:
    drive = path.drive.rstrip(":").lower()
    return f"/mnt/{drive}/{path.as_posix().split(':', 1)[1].lstrip('/')}" if drive else path.as_posix()


def _resolve(discovery: Path, summary: Path, output: Path, *selection: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(discovery / "resolve_m10_scheduler.py"), "--login-evidence", str(summary), "--output", str(output), *selection],
        cwd=output.parent,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
    )


def _build(tmp_path: Path, selection: Path | None = None, runtime: Path | None = None) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "m10"
    env = os.environ.copy(); env["PYTHONPATH"] = str(REPO / "src")
    command = [sys.executable, "tools/build_yoltla_m10_acceptance.py", "--output", str(output)]
    if selection is not None:
        command.extend(("--scheduler-selection", str(selection)))
        command.extend(("--runtime-selection", str(runtime or _runtime_selection(tmp_path))))
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
    assert (discovery / "run_runtime_candidate_probe.sh").is_file()
    assert (discovery / "build_login_summary.py").is_file()
    assert (discovery / "resolve_m10_scheduler.py").is_file()
    assert (discovery / "resolve_m10_runtime.py").is_file()
    run_probe = discovery / "run_login_probe.sh"
    assert run_probe.read_bytes().startswith(b"#!/usr/bin/env bash\n")
    assert b"\r" not in run_probe.read_bytes()
    assert all(b"\r" not in path.read_bytes() for path in discovery.glob("*.sh"))
    assert b"build_login_summary.py" not in run_probe.read_bytes()
    fixture = output / "scientific_fixture"
    source = REPO / "remote_validation" / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE"
    assert sha256((fixture / "input" / "smoke.fdf").read_bytes()).hexdigest() == sha256((source / "input" / "smoke.fdf").read_bytes()).hexdigest()
    assert sha256((fixture / "pseudopotentials" / "C.psml").read_bytes()).hexdigest() == sha256((source / "pseudopotentials" / "C.psml").read_bytes()).hexdigest()
    assert not list(output.rglob("submit.slurm"))


def test_summary_preserves_global_association_and_partition_policy_fields(tmp_path: Path) -> None:
    summary = build_login_summary(_raw_login_evidence(tmp_path))
    global_association = summary["eligible_associations"][0]
    assert global_association == {
        "account": "vini", "partition": None, "qos": "normal", "scope": "GLOBAL_USER_ASSOCIATION",
        "source": "sacctmgr", "source_file": "sacctmgr_assoc.txt", "source_line": 1,
    }
    queue_association = summary["eligible_associations"][1]
    assert queue_association["partition"] == "q4d-20p"
    assert queue_association["scope"] == "CURRENT_USER_QUEUE_EVIDENCE"
    policy = next(item for item in summary["partition_policies"] if item["name"] == "tt2d-64p")
    assert {field: policy[field] for field in ("state", "min_nodes", "max_nodes", "max_time")} == {"state": "UP", "min_nodes": 2, "max_nodes": 2, "max_time": "01:00:00"}
    assert policy["allow_accounts"] == {"kind": "ALL", "values": []}
    assert policy["allow_qos"] == {"kind": "ALL", "values": []}


def test_hydra_launcher_mechanisms_parse_only_the_observed_launcher_section() -> None:
    expected = ["ssh", "slurm", "rsh", "ll", "sge", "pbs", "pbsdsh", "pdsh", "srun", "lsf", "blaunch", "qrsh", "fork"]
    assert _hydra_launcher_mechanisms("-launcher launcher to use (ssh slurm rsh ll sge pbs pbsdsh pdsh srun lsf blaunch qrsh fork)\n-n ranks\n") == expected
    assert _hydra_launcher_mechanisms("-launcher\n  launcher to use\n  (ssh slurm rsh fork)\n-n ranks\n") == ["ssh", "slurm", "rsh", "fork"]
    assert _hydra_launcher_mechanisms("-n ranks\n") == []
    assert _hydra_launcher_mechanisms("general note (ssh slurm)\n-n ranks\n") == []


def test_real_shaped_hydra_summary_has_observed_mechanisms_without_bootstrap_default(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    probe = _runtime_probe_evidence(tmp_path, hydra=True)
    (probe / "mpiexec_hydra_help.txt").write_text(
        "-launcher launcher to use (ssh slurm rsh ll sge pbs pbsdsh pdsh srun lsf blaunch qrsh fork)\n-n ranks\n-ppn ranks\n",
        encoding="utf-8",
    )
    hydra = build_login_summary(raw, probe)["launcher_candidates"]["mpiexec.hydra"][0]
    assert hydra["observed_launcher_mechanisms"][:2] == ["ssh", "slurm"]
    assert hydra["bootstrap_selection_required"] is True
    assert "bootstrap" not in hydra


def test_login_summary_cli_rejects_missing_or_incomplete_evidence_without_output(tmp_path: Path) -> None:
    valid_raw = _raw_login_evidence(tmp_path / "valid")
    raw_file = tmp_path / "raw-file"
    raw_file.write_text("not a directory\n", encoding="utf-8")
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    cases = ((tmp_path / "absent", None), (raw_file, None), (incomplete, None), (valid_raw, tmp_path / "missing-probe"))
    for index, (raw, probe) in enumerate(cases):
        output = tmp_path / f"blocked-{index}.json"
        command = [sys.executable, "tools/build_yoltla_m10_login_summary.py", "--raw", str(raw), "--output", str(output)]
        if probe is not None:
            command.extend(("--runtime-probe", str(probe)))
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
        assert result.returncode != 0
        assert "M10_LOGIN_SUMMARY_UNRESOLVED" in result.stderr
        assert not output.exists()


def test_login_summary_cli_accepts_complete_current_evidence(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    probe = _runtime_probe_evidence(tmp_path)
    output = tmp_path / "login-summary.json"
    result = subprocess.run(
        [sys.executable, "tools/build_yoltla_m10_login_summary.py", "--raw", str(raw), "--runtime-probe", str(probe), "--output", str(output)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["runtime_probe"]["status"] == "VERIFIED"


def test_global_association_expands_only_to_current_policy_compatible_partitions(tmp_path: Path) -> None:
    output, _ = _build(tmp_path)
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(build_login_summary(_raw_login_evidence(tmp_path))), encoding="utf-8")
    automatic = _resolve(output / "scheduler_discovery", summary_path, tmp_path / "automatic.json")
    assert automatic.returncode != 0
    assert "SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS" in automatic.stderr
    selected = tmp_path / "tt2d.json"
    explicit = _resolve(output / "scheduler_discovery", summary_path, selected, "--account", "vini", "--partition", "tt2d-64p", "--qos", "normal")
    assert explicit.returncode == 0, explicit.stderr
    assert json.loads(selected.read_text(encoding="utf-8"))["association_scope"] == "GLOBAL_USER_ASSOCIATION"
    for partition, reason in (("q4d-20p", "CPUS_PER_NODE_INSUFFICIENT"), ("tt1d-128p", "MIN_NODES_VIOLATED"), ("qz2d-64p", "MAX_NODES_VIOLATED")):
        rejected = _resolve(output / "scheduler_discovery", summary_path, tmp_path / f"{partition}.json", "--account", "vini", "--partition", partition, "--qos", "normal")
        assert rejected.returncode != 0 and reason in rejected.stderr


def test_module_availability_requires_verified_runtime_probe(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    availability_only = build_login_summary(raw)
    assert not [item for item in availability_only["python_candidates"] if item["selected_mechanism"] == "MODULE"]
    assert not availability_only["siesta_candidates"]
    verified = build_login_summary(raw, _runtime_probe_evidence(tmp_path))
    python = next(item for item in verified["python_candidates"] if item["selected_mechanism"] == "MODULE")
    assert python["selected_executable"] == "/opt/python/bin/python3"
    assert python["environment_setup"] == ["module purge", "module load python/3.11.9", "module load siesta/5.4.2"]
    assert any(item["selected_mechanism"] == "MODULE" for item in verified["siesta_candidates"])
    assert verified["launcher_candidates"]["srun"][-1]["selected_mechanism"] == "MODULE"


def test_real_shaped_runtime_requires_explicit_module_executable_selection(tmp_path: Path) -> None:
    summary = build_login_summary(_raw_login_evidence(tmp_path), _runtime_probe_evidence(tmp_path))
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    try:
        resolve_runtime(path)
    except ValueError as error:
        assert "Python candidate is ambiguous" in str(error)
    else:
        raise AssertionError("runtime resolver selected a Python candidate automatically")
    resolved = resolve_runtime(
        path,
        python="/opt/python/bin/python3",
        siesta="/opt/siesta/bin/siesta",
        srun="/usr/bin/srun",
    )
    assert resolved["python"]["selected_mechanism"] == "MODULE"
    assert resolved["python"]["observed_version"] == "3.11.9"


def test_summary_rejects_unbound_or_forged_runtime_probe_modules(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    for name, replacement in {
        "unobserved": ("selected_python_module.txt", "python/not-observed\n"),
        "setup-mismatch": ("module_setup_commands.txt", "module purge\nmodule load python/3.11.9\nmodule load another-siesta\n"),
    }.items():
        probe = _runtime_probe_evidence(tmp_path / name)
        (probe / replacement[0]).write_text(replacement[1], encoding="utf-8")
        summary = build_login_summary(raw, probe)
        assert not [candidate for candidate in summary["python_candidates"] if candidate["selected_mechanism"] == "MODULE"]
        assert not [candidate for candidate in summary["siesta_candidates"] if candidate["selected_mechanism"] == "MODULE"]
        assert summary["runtime_probe"]["status"] == "NOT_EXECUTABLE_EVIDENCE"


def test_runtime_candidate_probe_rejects_module_not_in_raw_evidence(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    script = REPO / "tools" / "m10_yoltla_runtime_candidate_probe.sh"
    normalized = tmp_path / "runtime-probe.sh"
    _copy_linux_text(script, normalized)
    result = subprocess.run(["bash", _bash_path(normalized), "--raw", _bash_path(raw), "--python-module", "not-observed", "--siesta-module", "siesta/5.4.2"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "not exactly observed" in result.stderr
    source = script.read_text(encoding="utf-8")
    assert "sbatch" not in source and "smoke.fdf" not in source and "mpiexec.hydra -help" in source
    assert "(\n  [[ ! -e" in source


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
    assert "srun --nodes=2 --ntasks=64 --ntasks-per-node=32 hostname" in preflight
    assert "observed-python" in preflight and "observed-siesta" in preflight


def test_resolved_bundle_supports_evidence_bound_default_account(tmp_path: Path) -> None:
    output, manifest = _build(tmp_path, _selection(tmp_path, account=None))
    assert manifest["scheduler_selection"]["account"] is None
    assert "#SBATCH --account=" not in (output / "preflight" / "submit_m10_preflight.slurm").read_text(encoding="utf-8")
    for payload in manifest["packages"].values():
        submit = Path(payload["destination"]).joinpath("submit.slurm").read_text(encoding="utf-8")
        assert "#SBATCH --account=" not in submit


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
    assert first["command"][0] == "observed-python"
    assert "module load python/3.12" not in json.dumps(campaign)
    runbook = (REPO / "docs" / "validation" / "m10_hpc_portability_production_acceptance" / "RUNBOOK.md").read_text(encoding="utf-8")
    first_job = runbook.index("CONTINUATION JOB #1")
    assert first_job < runbook.index("HUMAN GATE", first_job) < runbook.index("CONTINUATION JOB #2")
    assert "sacct" in runbook and "sbatch --test-only" in runbook
    assert "--python <observed-module-python-path>" in runbook
    assert "--siesta <observed-module-siesta-path>" in runbook
    assert "--srun <observed-srun-path>" in runbook
    assert "--hydra <observed-hydra-path>" in runbook


def test_runtime_resolution_accepts_python_311_path_and_rejects_old_python(tmp_path: Path) -> None:
    summary = {"python_candidates": [{"selected_mechanism": "PATH", "selected_executable": "/bin/python", "observed_version": "3.11.0", "environment_setup": [], "evidence_source": ["raw"]}], "siesta_candidates": [{"selected_mechanism": "PATH", "selected_executable": "/bin/siesta", "observed_version": "5.4", "environment_setup": [], "evidence_source": ["raw"]}], "launcher_candidates": {"srun": [{"selected_mechanism": "PATH", "selected_executable": "/bin/srun", "arguments": [], "environment_setup": [], "evidence_source": ["raw"]}]}}
    path = tmp_path / "summary.json"; path.write_text(json.dumps(summary), encoding="utf-8")
    assert resolve_runtime(path)["python"]["observed_version"] == "3.11.0"
    summary["python_candidates"][0]["observed_version"] = "3.10.14"; path.write_text(json.dumps(summary), encoding="utf-8")
    try: resolve_runtime(path)
    except ValueError as error: assert "M10_RUNTIME_PROFILE_UNRESOLVED" in str(error)
    else: raise AssertionError("too-old Python was accepted")


def test_verified_module_probe_runtime_fails_closed_for_old_python_or_missing_siesta(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    for name, probe in {
        "old": _runtime_probe_evidence(tmp_path / "old", python_version="3.10.14"),
        "siesta": _runtime_probe_evidence(tmp_path / "siesta", siesta=False),
    }.items():
        summary = build_login_summary(raw, probe)
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(summary), encoding="utf-8")
        try:
            resolve_runtime(path)
        except ValueError as error:
            assert "M10_RUNTIME_PROFILE_UNRESOLVED" in str(error)
        else:
            raise AssertionError(f"{name} module evidence was accepted")


def test_verified_module_probe_hydra_needs_observed_bootstrap(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    no_bootstrap = build_login_summary(raw, _runtime_probe_evidence(tmp_path, hydra=True))
    path = tmp_path / "no-bootstrap.json"
    path.write_text(json.dumps(no_bootstrap), encoding="utf-8")
    assert "mpiexec.hydra" in no_bootstrap["launcher_candidates"]
    selected = {"python": "/opt/python/bin/python3", "siesta": "/opt/siesta/bin/siesta", "srun": "/usr/bin/srun", "hydra": "/opt/mpi/bin/mpiexec.hydra"}
    try:
        resolve_runtime(path, require_hydra=True, **selected)
    except ValueError as error:
        assert "M10_RUNTIME_PROFILE_UNRESOLVED" in str(error)
    else:
        raise AssertionError("Hydra bootstrap was guessed")
    resolved = build_login_summary(raw, _runtime_probe_evidence(tmp_path / "resolved", hydra=True, bootstrap="observed-bootstrap"))
    path.write_text(json.dumps(resolved), encoding="utf-8")
    runtime = resolve_runtime(path, require_hydra=True, **selected)
    assert runtime["launchers"]["hydra"]["bootstrap"] == "observed-bootstrap"
    assert runtime["launchers"]["srun"]["selected_mechanism"] == "MODULE"


def test_hydra_bootstrap_policy_is_explicit_and_evidence_bound(tmp_path: Path) -> None:
    raw = _raw_login_evidence(tmp_path)
    summary = build_login_summary(raw, _runtime_probe_evidence(tmp_path, hydra=True))
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    selected = {"python": "/opt/python/bin/python3", "siesta": "/opt/siesta/bin/siesta", "srun": "/usr/bin/srun", "hydra": "/opt/mpi/bin/mpiexec.hydra"}
    capability = summary["launcher_candidates"]["mpiexec.hydra"][0]
    assert capability["observed_launcher_mechanisms"][:2] == ["ssh", "slurm"]
    assert capability["bootstrap_selection_required"] is True
    assert "bootstrap" not in capability
    policy = _hydra_policy_evidence(tmp_path, "ssh")
    try:
        resolve_runtime(path, require_hydra=True, **selected)
    except ValueError as error:
        assert "Hydra requires reviewed bootstrap strategy" in str(error)
    else:
        raise AssertionError("Hydra bootstrap default was introduced")
    resolved = resolve_runtime(path, require_hydra=True, hydra_bootstrap="ssh", hydra_policy_evidence=policy, **selected)
    hydra = resolved["launchers"]["hydra"]
    assert hydra["bootstrap"] == "ssh"
    assert hydra["bootstrap_selection"]["kind"] == "EXPLICIT_ADMINISTRATIVE_POLICY"
    assert hydra["bootstrap_selection"]["policy_evidence_sha256"] == sha256(policy.read_bytes()).hexdigest()
    for bootstrap, evidence in (("ssh", None), ("not-in-policy", policy)):
        try:
            resolve_runtime(path, require_hydra=True, hydra_bootstrap=bootstrap, hydra_policy_evidence=evidence, **selected)
        except ValueError as error:
            assert "M10_RUNTIME_PROFILE_UNRESOLVED" in str(error)
        else:
            raise AssertionError("unsupported Hydra bootstrap selection was accepted")
    try:
        resolve_runtime(path, hydra_bootstrap="ssh", hydra_policy_evidence=policy, **{key: value for key, value in selected.items() if key != "hydra"})
    except ValueError as error:
        assert "requires --require-hydra" in str(error)
    else:
        raise AssertionError("Hydra bootstrap was accepted without --require-hydra")


def test_hydra_policy_materializes_command_and_execution_fingerprint(tmp_path: Path) -> None:
    selected = {"python": "/opt/python/bin/python3", "siesta": "/opt/siesta/bin/siesta", "srun": "/usr/bin/srun", "hydra": "/opt/mpi/bin/mpiexec.hydra"}

    def build_policy_bundle(root: Path, bootstrap: str) -> tuple[Path, dict[str, object]]:
        raw = _raw_login_evidence(root)
        summary = build_login_summary(raw, _runtime_probe_evidence(root, hydra=True))
        summary_path = root / "summary.json"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        runtime_path = root / "runtime.json"
        runtime_path.write_text(json.dumps(resolve_runtime(summary_path, require_hydra=True, hydra_bootstrap=bootstrap, hydra_policy_evidence=_hydra_policy_evidence(root, bootstrap), **selected)), encoding="utf-8")
        return _build(root, _selection(root), runtime_path)

    first_output, first_manifest = build_policy_bundle(tmp_path / "first", "ssh")
    second_output, second_manifest = build_policy_bundle(tmp_path / "second", "slurm")
    first_root = Path(first_manifest["packages"]["hydra"]["destination"])
    second_root = Path(second_manifest["packages"]["hydra"]["destination"])
    first_config = load_controller_config(first_root / "campaign.yaml")
    first_plan = translate_controller_config(first_config, root=first_root)
    second_plan = translate_controller_config(load_controller_config(second_root / "campaign.yaml"), root=second_root)
    task_id = "M10_SIESTA_SMOKE"
    assert first_plan.execution_specs[task_id].environment["I_MPI_HYDRA_BOOTSTRAP"] == "ssh"
    assert first_plan.execution_specs[task_id].fingerprint != second_plan.execution_specs[task_id].fingerprint
    assert first_plan.scientific_identities[task_id].fingerprint == second_plan.scientific_identities[task_id].fingerprint
    command = HydraLauncher(command=first_config.srun_command, arguments=first_config.srun_arguments, bootstrap=first_config.launcher_bootstrap).build_command(
        StepLaunchSpec(task_id=task_id, attempt_id="test", workdir=first_root, input_path=first_root / "input" / "smoke.fdf", stdout_path=first_root / "out", stderr_path=first_root / "err", mpi_processes=64, cpus_per_process=1, executable=first_config.siesta_executable, hosts=("node-a", "node-b"), processes_per_node=32)
    )
    assert command[command.index("-bootstrap") + 1] == "ssh"
    assert command.count("-bootstrap") == 1
    assert sum(argument in {"-n", "-np"} for argument in command) == 1
    assert command.count("-ppn") == 1
    assert (first_output / "sources" / "hydra" / "campaign.json").is_file()
    assert (second_output / "sources" / "hydra" / "campaign.json").is_file()


def test_verified_module_probe_without_hydra_is_rejected_when_required(tmp_path: Path) -> None:
    summary = build_login_summary(_raw_login_evidence(tmp_path), _runtime_probe_evidence(tmp_path))
    path = tmp_path / "no-hydra.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    try:
        resolve_runtime(path, python="/opt/python/bin/python3", siesta="/opt/siesta/bin/siesta", srun="/usr/bin/srun", require_hydra=True)
    except ValueError as error:
        assert "M10_RUNTIME_PROFILE_UNRESOLVED" in str(error)
    else:
        raise AssertionError("missing Hydra was accepted")


def test_module_runtime_and_missing_hydra_fail_closed(tmp_path: Path) -> None:
    runtime = _runtime_selection(tmp_path, module=True)
    output, manifest = _build(tmp_path / "module", _selection(tmp_path / "module"), runtime)
    assert manifest["runtime_selection"]["python_requirement"] == ">=3.11"
    assert "module load observed-python" in (output / "sources" / "srun" / "campaign.json").read_text(encoding="utf-8")
    missing = _runtime_selection(tmp_path / "missing", hydra=False)
    result = subprocess.run([sys.executable, "tools/build_yoltla_m10_acceptance.py", "--output", str(tmp_path / "blocked"), "--scheduler-selection", str(_selection(tmp_path / "missing")), "--runtime-selection", str(missing)], cwd=REPO, env={**os.environ, "PYTHONPATH": str(REPO / "src")}, capture_output=True, text=True)
    assert result.returncode != 0 and "M10_RUNTIME_PROFILE_UNRESOLVED" in result.stderr
