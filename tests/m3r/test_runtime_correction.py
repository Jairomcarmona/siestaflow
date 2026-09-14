from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from qraft.engines.siesta.pseudopotentials import PseudopotentialManifest
from qraft.project_packages import load_structured
from qraft.remote_environment import EnvironmentProbePackager, PROBE_ID
from qraft.validation.embedded_code import extract_python_heredocs, validate_files
from qraft.validation.slurm_evidence import TERMINAL_STATES, parse_sacct_main_row


REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "examples" / "reference_projects" / "birnessite_mn_o"
REFERENCE_MANIFEST = PseudopotentialManifest.load(REFERENCE / "pseudopotentials" / "manifest.yaml")
REFERENCE_REQUIREMENTS = {item.filename: item.sha256 for item in REFERENCE_MANIFEST.entries if item.sha256}
REFERENCE_LABELS = load_structured(REFERENCE / "policies" / "remote_probe_statuses.yaml")["status_labels"]


def _write_package(root: Path, *, requirements=None, labels=None) -> Path:
    package = root / PROBE_ID
    files = EnvironmentProbePackager(requirements or {}, labels).build_files()
    for name, content in files.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return package


def _rebuild_checksums(package: Path) -> None:
    lines = []
    for path in sorted(item for item in package.rglob("*") if item.is_file() and item.name != "checksums.sha256"):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(package).as_posix()}\n")
    (package / "checksums.sha256").write_text("".join(lines), encoding="utf-8", newline="\n")


def _stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _bash(package: Path, command: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    exports = "".join(f"export {key}={shlex.quote(value)}; " for key, value in (env or {}).items())
    return subprocess.run(
        ["bash", "-c", f'export PATH="$PWD/stubs:/usr/bin:/bin"; {exports}{command}'],
        cwd=package, capture_output=True, text=True, timeout=30,
    )


def _scheduler_login(account="acct", partition="part", qos="test-qos") -> dict:
    return {
        "eligible_associations": [{"account": account, "partition": partition, "qos": qos, "scope": "EXPLICIT_PARTITION_ASSOCIATION", "source_file": "sacctmgr_assoc.txt", "source_line": 1, "evidence_status": "OBSERVED", "observed_at": None}],
        "visible_partitions": [{"name": partition, "availability": "up", "time_limit": "01:00:00", "nodes": 1, "cpus_per_node": 1, "memory": 1024, "default": True, "source_file": "sinfo.txt", "source_line": 1}],
        "partition_policies": [{"name": partition, "allow_accounts": {"kind": "ALL", "values": []}, "allow_qos": {"kind": "ALL", "values": []}, "default": True, "state": "UP", "min_nodes": 1, "max_nodes": 1, "max_time": "01:00:00", "source_file": "scontrol_partitions.txt", "source_line": 1}],
    }


def test_embedded_validator_handles_quotes_multiple_blocks_and_failure(tmp_path: Path):
    valid = tmp_path / "valid.sh"
    valid.write_text("python3 - <<'PY'\nprint('one')\nPY\npython3 - <<\"PY\"\nprint('two')\nPY\n", encoding="utf-8")
    assert len(extract_python_heredocs(valid)) == 2
    assert validate_files((valid,)) == ()
    invalid = tmp_path / "invalid.slurm"
    invalid.write_text("python3 - <<PY\nvalue = 'broken\nPY\n", encoding="utf-8")
    diagnostics = validate_files((invalid,))
    assert len(diagnostics) == 1
    assert diagnostics[0].start_line == 2 and diagnostics[0].error_line == 2


def test_all_v2_direct_and_embedded_sources_compile_and_shells_parse(tmp_path: Path):
    package = _write_package(tmp_path, requirements=REFERENCE_REQUIREMENTS, labels=REFERENCE_LABELS)
    direct = sorted(package.rglob("*.py"))
    for path in direct:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    shell = sorted(path for path in package.rglob("*") if path.suffix in {".sh", ".slurm"})
    assert validate_files(shell) == ()
    for path in shell:
        result = _bash(package, f"bash -n {path.relative_to(package).as_posix()}")
        assert result.returncode == 0, result.stderr


def test_package_verifier_checks_hashes_runtime_and_structure(tmp_path: Path):
    package = _write_package(tmp_path, requirements=REFERENCE_REQUIREMENTS, labels=REFERENCE_LABELS)
    result = subprocess.run([sys.executable, str(package / "verify_local_package.py")], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "M3_PACKAGE_HASHES_VERIFIED", "M3_PACKAGE_RUNTIME_SYNTAX_VERIFIED", "M3_PACKAGE_STRUCTURE_VERIFIED",
    ]


def test_package_verifier_detects_secret_and_traversal(tmp_path: Path):
    secret_package = _write_package(tmp_path / "secret")
    (secret_package / "unexpected.txt").write_text("TOKEN=not-a-real-token\n", encoding="utf-8")
    _rebuild_checksums(secret_package)
    secret = subprocess.run([sys.executable, str(secret_package / "verify_local_package.py")], capture_output=True, text=True)
    assert secret.returncode != 0 and "PACKAGE_SECRET_FAILURE" in secret.stderr

    traversal_package = _write_package(tmp_path / "traversal")
    with (traversal_package / "checksums.sha256").open("a", encoding="utf-8") as handle:
        handle.write("0" * 64 + "  ../escape\n")
    traversal = subprocess.run([sys.executable, str(traversal_package / "verify_local_package.py")], capture_output=True, text=True)
    assert traversal.returncode != 0 and "PACKAGE_PATH_FAILURE" in traversal.stderr


def test_package_verifier_detects_new_invalid_python(tmp_path: Path):
    package = _write_package(tmp_path)
    (package / "scripts" / "invalid_added.py").write_text("value = 'broken\n", encoding="utf-8")
    _rebuild_checksums(package)
    result = subprocess.run([sys.executable, str(package / "verify_local_package.py")], capture_output=True, text=True)
    assert result.returncode != 0 and "DIRECT_PYTHON_SYNTAX_FAILURE" in result.stderr


def test_prepare_generated_slurm_executes_with_stubs(tmp_path: Path):
    package = _write_package(tmp_path)
    login = package / "evidence" / "login_probe" / "summary.json"
    login.parent.mkdir(parents=True)
    login.write_text(json.dumps(_scheduler_login()), encoding="utf-8")
    output = package / "generated" / "submit_environment_probe.slurm"
    prepared = subprocess.run(
        [sys.executable, str(package / "prepare_scheduler_probe.py"), "--login-evidence", str(login), "--output", str(output)],
        capture_output=True, text=True, timeout=30,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert validate_files((output,)) == ()
    _stub(package / "stubs" / "module", "echo 'module stub' >&2")
    for name in ("srun", "mpirun", "mpiexec", "mpiexec.hydra"):
        _stub(package / "stubs" / name, f"echo '{name} synthetic version'")
    _stub(package / "stubs" / "hostname", "echo synthetic-node")
    _stub(package / "stubs" / "df", "echo 'Filesystem 1024-blocks Used Available Capacity Mounted'; echo '/stub 1 0 1 0% /'")
    environment = {
        "SLURM_JOB_ID": "12345", "SLURM_JOB_PARTITION": "part", "SLURM_JOB_ACCOUNT": "acct",
        "SLURM_JOB_QOS": "test-qos", "SLURM_NNODES": "1", "SLURM_NTASKS": "1",
        "SLURM_CPUS_PER_TASK": "1", "SLURM_JOB_END_TIME": "9999999999",
    }
    executed = _bash(package, 'export SLURM_SUBMIT_DIR="$PWD"; bash generated/submit_environment_probe.slurm', env=environment)
    assert executed.returncode == 0, executed.stderr
    summary = json.loads((package / "evidence" / "scheduler_probe" / "summary.json").read_text(encoding="utf-8"))
    assert summary["scientific_calculation_performed"] is False
    assert summary["signal_received"] is True
    assert summary["job_id"] == "12345"
    assert summary["partition"] == "part" and summary["account"] == "acct"


def test_prepare_removes_invalid_generated_candidate(tmp_path: Path):
    package = _write_package(tmp_path)
    login = package / "evidence" / "login_probe" / "summary.json"; login.parent.mkdir(parents=True)
    login.write_text(json.dumps(_scheduler_login(qos=None)), encoding="utf-8")
    validator = package / "scripts" / "validate_embedded_python.py"
    validator.write_text("raise SystemExit(2)\n", encoding="utf-8")
    output = package / "generated" / "submit_environment_probe.slurm"
    result = subprocess.run([sys.executable, str(package / "prepare_scheduler_probe.py"), "--login-evidence", str(login), "--output", str(output)], capture_output=True, text=True)
    assert result.returncode != 0 and "GENERATED_SCHEDULER_SCRIPT_INVALID" in result.stderr
    assert not output.exists() and not output.with_name(output.name + ".tmp").exists()


@pytest.mark.parametrize(
    "state,exit_code,squeue,terminal,review",
    [
        ("RUNNING", "0:0", "12345|RUNNING|part|acct|test-qos|00:01|node\n", False, False),
        ("COMPLETED", "0:0", "", True, False),
        ("FAILED", "1:0", "", True, False),
        (None, None, "", False, False),
        ("TIMEOUT", "0:0", "", True, False),
        ("NODE_FAIL", "1:0", "", True, False),
        ("FUTURE_STATE", "0:0", "", False, True),
    ],
)
def test_inspect_job_runtime_cases(tmp_path: Path, state: str | None, exit_code: str | None, squeue: str, terminal: bool, review: bool):
    package = _write_package(tmp_path)
    _stub(package / "stubs" / "squeue", "printf '%s' \"${STUB_SQUEUE:-}\"")
    _stub(package / "stubs" / "sacct", "printf '%s' \"${STUB_SACCT:-}\"")
    if state:
        main = f"12345|{state}+|{exit_code}|00:01:00|cpu=1,mem=1G,node=1|1M|node1|part|acct|test-qos\n"
        sacct = "12345.batch|FAILED|1:0|||||||\n" + main + "12345.extern|COMPLETED|0:0|||||||\n"
    else:
        sacct = ""
    result = _bash(package, "bash inspect_probe_job.sh 12345", env={"STUB_SQUEUE": squeue, "STUB_SACCT": sacct})
    assert result.returncode == 0, result.stderr
    summary = json.loads((package / "evidence" / "slurm_accounting" / "summary.json").read_text(encoding="utf-8"))
    assert summary["state"] == state
    assert summary["terminal_evidence"] is terminal
    assert summary["review_required"] is review
    if not squeue and not sacct:
        assert summary["terminal_evidence"] is False


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
def test_sacct_parser_selects_main_row_and_all_terminal_states(state: str):
    lines = [
        "77.batch|FAILED|1:0|||||||",
        f" 77 | {state}+ | 0:0 | 00:00:01 | cpu=1 | 1M | node | part | acct | test-qos ",
        "77.extern|COMPLETED|0:0|||||||",
    ]
    parsed = parse_sacct_main_row(lines, "77")
    assert parsed["main_job_row_found"] is True
    assert parsed["state"] == state and parsed["terminal_evidence"] is True


def _complete_evidence(package: Path) -> None:
    evidence = package / "evidence"
    values = {
        "login_probe/summary.json": {"observed_at": "2026-07-21T00:00:00Z", "commands": {}, "environment": {}, "siesta_version_candidates": []},
        "scheduler_probe/summary.json": {"observed_at": "2026-07-21T00:00:00Z", "scientific_calculation_performed": False},
        "slurm_accounting/summary.json": {"observed_at": "2026-07-21T00:00:00Z", "state": "COMPLETED", "exit_code": "0:0", "terminal_evidence": True},
        "pseudo_verification/summary.json": {"observed_at": "2026-07-21T00:00:00Z", "status": "SYNTHETIC_VERIFIED", "entries": {}},
    }
    for name, data in values.items():
        path = evidence / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    text = {"stdout/login_probe.log": "synthetic\n", "stderr/login_probe.err": "", "stdout/scheduler-1.out": "synthetic\n", "stderr/scheduler-1.err": ""}
    for name, content in text.items():
        path = evidence / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")


def test_bundle_collector_runtime_normalizes_archive(tmp_path: Path):
    package = _write_package(tmp_path); _complete_evidence(package)
    script = package / "scripts" / "collect_bundle.py"
    result = subprocess.run([sys.executable, str(script), "--package-root", str(package), "--timestamp", "20260721T010203Z"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    bundle = package / "M3_YOLTLA_ENVIRONMENT_RESULTS_20260721T010203Z.tar.gz"
    with tarfile.open(bundle, "r:gz") as archive:
        names = {member.name for member in archive.getmembers() if member.isfile()}
        assert {"results_manifest.json", "results_manifest.sha256", "checksums.sha256", "stdout/scheduler.out", "stderr/scheduler.err"} <= names
        assert all(member.uid == 0 and member.gid == 0 and member.mtime == 0 for member in archive.getmembers())
        assert not any(name.startswith("/") or ".." in Path(name).parts for name in names)


@pytest.mark.parametrize("missing", ["stdout/login_probe.log", "stderr/login_probe.err", "scheduler_probe/summary.json", "pseudo_verification/summary.json"])
def test_bundle_collector_blocks_incomplete_evidence(tmp_path: Path, missing: str):
    package = _write_package(tmp_path); _complete_evidence(package); (package / "evidence" / missing).unlink()
    result = subprocess.run([sys.executable, str(package / "scripts" / "collect_bundle.py"), "--package-root", str(package), "--timestamp", "20260721T010203Z"], capture_output=True, text=True)
    assert result.returncode != 0 and "MISSING_EVIDENCE" in result.stderr


def test_bundle_collector_refuses_existing_bundle(tmp_path: Path):
    package = _write_package(tmp_path); _complete_evidence(package)
    bundle = package / "M3_YOLTLA_ENVIRONMENT_RESULTS_20260721T010203Z.tar.gz"; bundle.write_bytes(b"existing")
    result = subprocess.run([sys.executable, str(package / "scripts" / "collect_bundle.py"), "--package-root", str(package), "--timestamp", "20260721T010203Z"], capture_output=True, text=True)
    assert result.returncode != 0 and "REFUSING_OVERWRITE" in result.stderr


def test_pseudopotential_verifier_controlled_states_and_no_mutation(tmp_path: Path):
    mn_content = b"<psml>synthetic Mn fixture</psml>\n"
    o_content = b"<psml>synthetic O fixture</psml>\n"
    requirements = {"Mn.psml": hashlib.sha256(mn_content).hexdigest(), "O.psml": hashlib.sha256(o_content).hexdigest()}
    package = _write_package(tmp_path, requirements=requirements, labels=REFERENCE_LABELS)
    script = package / "scripts" / "verify_pseudos.py"

    def run(root: Path, name: str) -> dict:
        output = package / "evidence" / f"{name}.json"
        result = subprocess.run([sys.executable, str(script), "--root", str(root), "--output", str(output)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(output.read_text(encoding="utf-8"))

    correct = tmp_path / "correct"; correct.mkdir(); (correct / "Mn.psml").write_bytes(mn_content); (correct / "O.psml").write_bytes(o_content)
    before = {path.name: path.read_bytes() for path in correct.iterdir()}
    assert run(correct, "correct")["status"] == "PSEUDOS_MN_O_HASH_VERIFIED"
    assert {path.name: path.read_bytes() for path in correct.iterdir()} == before

    missing_mn = tmp_path / "missing_mn"; missing_mn.mkdir(); (missing_mn / "O.psml").write_bytes(o_content)
    assert run(missing_mn, "missing_mn")["status"] == "PSEUDOS_MN_O_MISSING"
    missing_o = tmp_path / "missing_o"; missing_o.mkdir(); (missing_o / "Mn.psml").write_bytes(mn_content)
    assert run(missing_o, "missing_o")["status"] == "PSEUDOS_MN_O_MISSING"
    assert run(tmp_path / "does_not_exist", "missing_root")["status"] == "PSEUDOS_MN_O_MISSING"

    bad_hash = tmp_path / "bad_hash"; bad_hash.mkdir(); (bad_hash / "Mn.psml").write_bytes(b"<psml>different</psml>\n"); (bad_hash / "O.psml").write_bytes(o_content)
    assert run(bad_hash, "bad_hash")["status"] == "PSEUDOS_MN_O_HASH_MISMATCH"
    bad_format = tmp_path / "bad_format"; bad_format.mkdir(); (bad_format / "Mn.psml").write_bytes(mn_content); (bad_format / "O.psml").write_bytes(b"not psml")
    assert run(bad_format, "bad_format")["status"] == "PSEUDOS_MN_O_HASH_MISMATCH"

    duplicate = tmp_path / "duplicate"; (duplicate / "one").mkdir(parents=True); (duplicate / "two").mkdir()
    (duplicate / "one" / "Mn.psml").write_bytes(mn_content); (duplicate / "two" / "Mn.psml").write_bytes(mn_content); (duplicate / "O.psml").write_bytes(o_content)
    assert run(duplicate, "duplicate")["status"] == "PSEUDOS_MN_O_REVIEW"

    command = """rm -rf /tmp/siestaflow_m3r_unreadable_fixture
mkdir /tmp/siestaflow_m3r_unreadable_fixture
printf '<psml>synthetic Mn fixture</psml>\\n' >/tmp/siestaflow_m3r_unreadable_fixture/Mn.psml
printf '<psml>synthetic O fixture</psml>\\n' >/tmp/siestaflow_m3r_unreadable_fixture/O.psml
chmod 000 /tmp/siestaflow_m3r_unreadable_fixture/Mn.psml
python3 scripts/verify_pseudos.py --root /tmp/siestaflow_m3r_unreadable_fixture --output evidence/unreadable_posix.json
chmod 600 /tmp/siestaflow_m3r_unreadable_fixture/Mn.psml
rm -rf /tmp/siestaflow_m3r_unreadable_fixture"""
    unreadable_result = _bash(package, command)
    assert unreadable_result.returncode == 0, unreadable_result.stderr
    unreadable_data = json.loads((package / "evidence" / "unreadable_posix.json").read_text(encoding="utf-8"))
    assert unreadable_data["status"] == "PSEUDOS_MN_O_REVIEW"


def test_v3_package_is_reproducible_and_declares_revision(tmp_path: Path):
    packager = EnvironmentProbePackager(REFERENCE_REQUIREMENTS, REFERENCE_LABELS)
    assert packager.build_files() == packager.build_files()
    first = packager.package(tmp_path / "one"); second = packager.package(tmp_path / "two")
    first_root, second_root = Path(first.destination), Path(second.destination)
    assert {p.relative_to(first_root).as_posix(): p.read_bytes() for p in first_root.rglob("*") if p.is_file()} == {p.relative_to(second_root).as_posix(): p.read_bytes() for p in second_root.rglob("*") if p.is_file()}
    manifest = json.loads((first_root / "probe_manifest.json").read_text(encoding="utf-8"))
    assert manifest["reproducibility_epoch"] == "M3_STATIC_V3"
    assert manifest["package_revision"] == 3 and manifest["supersedes"] == "M3_STATIC_V2"


def test_full_local_runtime_demonstration_with_stubs(tmp_path: Path):
    mn = b"<psml>synthetic Mn demo</psml>\n"; oxygen = b"<psml>synthetic O demo</psml>\n"
    requirements = {"Mn.psml": hashlib.sha256(mn).hexdigest(), "O.psml": hashlib.sha256(oxygen).hexdigest()}
    package = _write_package(tmp_path, requirements=requirements, labels=REFERENCE_LABELS)
    _stub(package / "stubs" / "module", "echo 'siesta/test'")
    _stub(package / "stubs" / "hostname", "echo synthetic-login")
    _stub(package / "stubs" / "df", "echo 'Filesystem 1024-blocks Used Available Capacity Mounted'; echo '/stub 1 0 1 0% /'")
    _stub(package / "stubs" / "quota", "echo 'synthetic quota'")
    _stub(package / "stubs" / "sbatch", "echo 'stub: submission forbidden' >&2; exit 2")
    _stub(package / "stubs" / "squeue", "printf '%s' \"${STUB_SQUEUE:-}\"")
    _stub(package / "stubs" / "sinfo", "echo 'part*|up|01:00:00|1|1|1024'")
    _stub(package / "stubs" / "sacct", "printf '%s' \"${STUB_SACCT:-}\"")
    _stub(package / "stubs" / "scontrol", "echo 'PartitionName=part AllowAccounts=ALL AllowQos=ALL Default=YES State=UP MinNodes=1 MaxNodes=1 MaxTime=01:00:00'")
    _stub(package / "stubs" / "sacctmgr", "echo 'acct|part|test-qos'")
    for name in ("srun", "mpirun", "mpiexec", "mpiexec.hydra"):
        _stub(package / "stubs" / name, f"echo '{name} synthetic version'")

    login = _bash(package, "bash run_login_probe.sh")
    assert login.returncode == 0, login.stderr
    login_summary = json.loads((package / "evidence" / "login_probe" / "summary.json").read_text(encoding="utf-8"))
    assert login_summary["scientific_calculation_performed"] is False
    assert login_summary["eligible_associations"][0]["scope"] == "EXPLICIT_PARTITION_ASSOCIATION"
    assert login_summary["eligible_associations"][0]["account"] == "acct"

    generated = package / "generated" / "submit_environment_probe.slurm"
    prepared = subprocess.run([sys.executable, str(package / "prepare_scheduler_probe.py"), "--login-evidence", str(package / "evidence/login_probe/summary.json"), "--output", str(generated)], capture_output=True, text=True)
    assert prepared.returncode == 0 and validate_files((generated,)) == ()
    slurm_env = {"SLURM_JOB_ID": "54321", "SLURM_JOB_PARTITION": "part", "SLURM_JOB_ACCOUNT": "acct", "SLURM_JOB_QOS": "test-qos", "SLURM_NNODES": "1", "SLURM_NTASKS": "1", "SLURM_CPUS_PER_TASK": "1", "SLURM_JOB_END_TIME": "9999999999"}
    scheduler = _bash(package, 'export SLURM_SUBMIT_DIR="$PWD"; bash generated/submit_environment_probe.slurm', env=slurm_env)
    assert scheduler.returncode == 0
    (package / "evidence/stdout/scheduler-54321.out").write_text(scheduler.stdout, encoding="utf-8")
    (package / "evidence/stderr/scheduler-54321.err").write_text(scheduler.stderr, encoding="utf-8")

    sacct = "54321|COMPLETED|0:0|00:00:10|cpu=1,mem=1G,node=1|1M|node1|part|acct|test-qos\n54321.batch|COMPLETED|0:0|||||||\n"
    inspected = _bash(package, "bash inspect_probe_job.sh 54321", env={"STUB_SQUEUE": "", "STUB_SACCT": sacct})
    assert inspected.returncode == 0
    accounting = json.loads((package / "evidence/slurm_accounting/summary.json").read_text(encoding="utf-8"))
    assert accounting["terminal_evidence"] is True and accounting["state"] == "COMPLETED"

    pseudo_root = tmp_path / "synthetic_pseudos"; pseudo_root.mkdir(); (pseudo_root / "Mn.psml").write_bytes(mn); (pseudo_root / "O.psml").write_bytes(oxygen)
    verified = subprocess.run([sys.executable, str(package / "scripts/verify_pseudos.py"), "--root", str(pseudo_root), "--output", str(package / "evidence/pseudo_verification/summary.json")], capture_output=True, text=True)
    assert verified.returncode == 0 and "PSEUDOS_MN_O_HASH_VERIFIED" in verified.stdout
    collected = subprocess.run([sys.executable, str(package / "scripts/collect_bundle.py"), "--package-root", str(package), "--timestamp", "20260721T020304Z"], capture_output=True, text=True)
    assert collected.returncode == 0, collected.stderr
    bundle = package / "M3_YOLTLA_ENVIRONMENT_RESULTS_20260721T020304Z.tar.gz"
    with tarfile.open(bundle, "r:gz") as archive:
        assert archive.extractfile("results_manifest.json") is not None
