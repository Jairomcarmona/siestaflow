#!/usr/bin/env python3
"""Build evidence-bound, manual-only M10 Yoltla acceptance bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
from pathlib import Path
from typing import Any, Mapping

from qraft.controller_package import ControllerPackageBuilder
from qraft.execution.allocation_controller import load_controller_config
from qraft.execution.legacy_translation import translate_controller_config


CAMPAIGN_ID = "QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE"
SYSTEM_ID = "SURF_Gr5x5_clean_v01_TECHNICAL_ACCEPTANCE"
CONTINUATION_CAMPAIGN_ID = "QRAFT_M10_ALLOCATION_CONTINUATION_TECHNICAL"
RESOURCE_SHAPE = {"nodes": 2, "mpi_ranks": 64, "processes_per_node": 32}
HISTORICAL_HINT = {
    "partition": "tt2d-64p", "account": "vini", "qos": "normal",
    "status": "HISTORICAL_ONLY_NOT_CURRENT_AUTHORITY",
}
CONTINUATION_FIRST_ALLOCATION_SECONDS = 60
CONTINUATION_SECOND_ALLOCATION_SECONDS = 180
CONTINUATION_STAGE_A_ESTIMATE_SECONDS = 5
CONTINUATION_STAGE_B_ESTIMATE_SECONDS = 90
CONTINUATION_SHUTDOWN_MARGIN_SECONDS = 10
_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _copy_linux_text(source: Path, destination: Path) -> None:
    """Materialize a Linux-targeted text file with LF line endings."""

    destination.write_bytes(source.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


def _write_linux_text(destination: Path, text: str) -> None:
    destination.write_bytes(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def _required_scheduler_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE.fullmatch(value):
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: invalid {field}")
    return value


def _load_scheduler_selection(path: Path) -> dict[str, Any]:
    """Validate the existing M3 scheduler-selection shape without a fallback."""

    if not path.is_file():
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: selection file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: selection must be an object")
    result = dict(data)
    for field in ("partition", "memory"):
        result[field] = _required_scheduler_text(result.get(field), field)
    account = result.get("account")
    if account is not None:
        result["account"] = _required_scheduler_text(account, "account")
    qos = result.get("qos")
    if qos is not None:
        result["qos"] = _required_scheduler_text(qos, "qos")
    for field, expected in (("nodes", 2), ("ntasks", 64), ("cpus_per_task", 1), ("processes_per_node", 32)):
        if result.get(field) != expected:
            raise ValueError(
                "M10_REMOTE_PROFILE_UNRESOLVED: scheduler selection does not "
                f"demonstrate M10 {field}={expected}"
            )
    evidence = result.get("evidence_status_by_field")
    if not isinstance(evidence, Mapping):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: missing evidence statuses")
    for field in ("account", "partition", "qos", "memory", "resource_shape"):
        if field not in evidence:
            raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: missing {field} evidence status")
    if result.get("walltime") != "00:20:00":
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: scheduler selection does not demonstrate M10 walltime=00:20:00")
    if result.get("resource_shape_status") != "VERIFIED_FROM_CURRENT_CLUSTER_EVIDENCE":
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: M10 resource shape is not verified from current cluster evidence")
    if not isinstance(result.get("source_files"), list) or not result["source_files"]:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: missing scheduler source files")
    return result


def _runtime_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE.fullmatch(value):
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: invalid {field}")
    return value


def _runtime_commands(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: invalid {field}")
    return list(value)


def _load_runtime_selection(path: Path) -> dict[str, Any]:
    """Load only a reviewed, evidence-bound M10 runtime selection."""

    if not path.is_file():
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: selection file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: runtime selection is not JSON") from error
    if not isinstance(data, dict) or data.get("status") != "RESOLVED_FROM_CURRENT_CLUSTER_EVIDENCE":
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: runtime selection is unresolved")
    result = dict(data)
    for component in ("python", "siesta"):
        payload = result.get(component)
        if not isinstance(payload, dict):
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: missing {component} selection")
        if payload.get("selected_mechanism") not in {"PATH", "MODULE", "OTHER_EVIDENCE_BOUND"}:
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: invalid {component} mechanism")
        _runtime_text(payload.get("selected_executable"), f"{component}.selected_executable")
        _runtime_text(payload.get("observed_version"), f"{component}.observed_version")
        _runtime_commands(payload.get("environment_setup", []), f"{component}.environment_setup")
        if not payload.get("evidence_source"):
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: missing {component} evidence")
    if result["python"].get("requirement") != ">=3.11":
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: Python requirement must be >=3.11")
    launchers = result.get("launchers")
    if not isinstance(launchers, dict) or not isinstance(launchers.get("srun"), dict):
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: srun selection missing")
    for name, payload in launchers.items():
        if name not in {"srun", "hydra"} or not isinstance(payload, dict):
            raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: invalid launcher selection")
        if payload.get("required") is False and name == "hydra":
            continue
        _runtime_text(payload.get("selected_executable"), f"launchers.{name}.selected_executable")
        _runtime_commands(payload.get("arguments", []), f"launchers.{name}.arguments")
        _runtime_commands(payload.get("environment_setup", []), f"launchers.{name}.environment_setup")
        if not payload.get("evidence_source"):
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: missing {name} evidence")
    srun_args = result["launchers"]["srun"]["arguments"]
    for required in ("--nodes=2", "--ntasks=64", "--ntasks-per-node=32"):
        if required not in srun_args:
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: srun selection lacks {required}")
    return result


def _slurm(selection: Mapping[str, Any]) -> dict[str, str]:
    result = {"partition": str(selection["partition"])}
    if selection.get("account") is not None:
        result["account"] = str(selection["account"])
    if selection.get("qos") is not None:
        result["qos"] = str(selection["qos"])
    return result


def _fixture(repository: Path, destination: Path) -> dict[str, str]:
    source = repository / "remote_validation" / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE"
    (destination / "input").mkdir(parents=True)
    (destination / "pseudopotentials").mkdir()
    shutil.copy2(source / "input" / "smoke.fdf", destination / "input" / "smoke.fdf")
    shutil.copy2(source / "pseudopotentials" / "C.psml", destination / "pseudopotentials" / "C.psml")
    return {
        "input/smoke.fdf": _sha(destination / "input" / "smoke.fdf"),
        "pseudopotentials/C.psml": _sha(destination / "pseudopotentials" / "C.psml"),
    }


def _runtime_environment(runtime: Mapping[str, Any], launcher: str | None = None) -> list[str]:
    commands = [*runtime["python"]["environment_setup"], *runtime["siesta"]["environment_setup"]]
    if launcher is not None:
        commands.extend(runtime["launchers"][launcher]["environment_setup"])
    # Controller packages invoke their embedded worker as python3.  This shell
    # function makes that invocation the reviewed executable, without assuming
    # that a cluster's login default is suitable.
    commands.append(f"python3() {{ {shlex.quote(runtime['python']['selected_executable'])} \"$@\"; }}")
    return commands


def _siesta_campaign(repository: Path, selection: Mapping[str, Any], runtime: Mapping[str, Any], launcher: str, source: Path) -> Path:
    hashes = _fixture(repository, source)
    selected_launcher = runtime["launchers"][launcher]
    launcher_data: dict[str, Any] = {
        "kind": launcher, "command": [selected_launcher["selected_executable"]],
        "arguments": selected_launcher["arguments"],
        "bootstrap": selected_launcher.get("bootstrap", "evidence-bound"),
        "processes_per_node": RESOURCE_SHAPE["processes_per_node"],
    }
    runtime_environment = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    if launcher == "hydra":
        runtime_environment["I_MPI_HYDRA_BOOTSTRAP"] = str(selected_launcher["bootstrap"])
    campaign = {
        "schema_version": "2.0", "campaign_id": CAMPAIGN_ID, "system_id": SYSTEM_ID,
        "classification": ["NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "ENERGY_INTERPRETATION_FORBIDDEN"],
        "slurm": _slurm(selection),
        "resources": {"nodes": 2, "total_cpus": 64, "memory": selection["memory"], "walltime": "00:20:00", "max_parallel_steps": 1, "shutdown_margin_seconds": 120, "termination_grace_seconds": 30},
        "runtime": {"module_commands": _runtime_environment(runtime, launcher), "siesta_executable": runtime["siesta"]["selected_executable"], "executable_arguments": [], "launcher": launcher_data, "exclusive": True, "environment": runtime_environment},
        "tasks": [{"task_id": "M10_SIESTA_SMOKE", "input": "input/smoke.fdf", "input_hashes": hashes, "required_artifacts": [], "mpi_processes": 64, "cpus_per_process": 1, "nodes": 2, "estimated_runtime_seconds": 600, "max_attempts": 1, "require_scf_converged": True}],
    }
    path = source / "campaign.json"
    _write_json(path, campaign)
    return path


def _continuation_campaign(selection: Mapping[str, Any], runtime: Mapping[str, Any], source: Path) -> Path:
    (source / "input").mkdir(parents=True)
    input_path = source / "input" / "continuation-input.json"
    _write_json(input_path, {"classification": "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "purpose": "M10 allocation continuation"})
    digest = _sha(input_path)
    task_base = {"input": "input/continuation-input.json", "input_hashes": {"input/continuation-input.json": digest}, "required_artifacts": [], "mpi_processes": 1, "cpus_per_process": 1, "nodes": 0, "max_attempts": 2, "kind": "gate"}
    campaign = {
        "schema_version": "2.0", "campaign_id": CONTINUATION_CAMPAIGN_ID, "system_id": "M10_ALLOCATION_CONTINUATION_TECHNICAL",
        "classification": ["NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "ENERGY_INTERPRETATION_FORBIDDEN"], "slurm": _slurm(selection),
        "resources": {"nodes": 2, "total_cpus": 64, "memory": selection["memory"], "walltime": "00:03:00", "max_parallel_steps": 1, "shutdown_margin_seconds": CONTINUATION_SHUTDOWN_MARGIN_SECONDS, "termination_grace_seconds": 10},
        "runtime": {"module_commands": _runtime_environment(runtime, "srun"), "siesta_executable": runtime["python"]["selected_executable"], "executable_arguments": [], "launcher": {"kind": "srun", "command": [runtime["launchers"]["srun"]["selected_executable"]], "arguments": runtime["launchers"]["srun"]["arguments"], "bootstrap": "evidence-bound", "processes_per_node": 32}, "exclusive": True, "environment": {}},
        "tasks": [
            {"task_id": "STAGE_A", "command": [runtime["python"]["selected_executable"], "-c", "from pathlib import Path; import time; time.sleep(4); Path('stage_a.complete').write_text('complete\\n', encoding='utf-8')"], "estimated_runtime_seconds": CONTINUATION_STAGE_A_ESTIMATE_SECONDS, **task_base},
            {"task_id": "STAGE_B", "command": [runtime["python"]["selected_executable"], "-c", "from pathlib import Path; import time; time.sleep(2); Path('stage_b.complete').write_text('complete\\n', encoding='utf-8')"], "depends_on": ["STAGE_A"], "estimated_runtime_seconds": CONTINUATION_STAGE_B_ESTIMATE_SECONDS, **task_base},
        ],
    }
    path = source / "campaign.json"
    _write_json(path, campaign)
    return path


def _equivalence(hydra: Path, srun: Path) -> dict[str, Any]:
    first = translate_controller_config(load_controller_config(hydra), root=hydra.parent)
    second = translate_controller_config(load_controller_config(srun), root=srun.parent)
    task = "M10_SIESTA_SMOKE"
    payload = {
        "workflow_id_equal": first.workflow.workflow_id == second.workflow.workflow_id,
        "workflow_definition_sha256_equal": first.workflow.definition_sha256 == second.workflow.definition_sha256,
        "scientific_identity_equal": first.scientific_identities[task].fingerprint == second.scientific_identities[task].fingerprint,
        "execution_spec_different": first.execution_specs[task].fingerprint != second.execution_specs[task].fingerprint,
        "workflow_id": first.workflow.workflow_id, "workflow_definition_sha256": first.workflow.definition_sha256,
        "scientific_identity_sha256": first.scientific_identities[task].fingerprint,
        "hydra_execution_spec_sha256": first.execution_specs[task].fingerprint,
        "srun_execution_spec_sha256": second.execution_specs[task].fingerprint,
    }
    if not all(payload[key] for key in ("workflow_id_equal", "workflow_definition_sha256_equal", "scientific_identity_equal", "execution_spec_different")):
        raise ValueError("M10 backend equivalence precheck failed")
    return payload


def _preflight_script(selection: Mapping[str, Any], runtime: Mapping[str, Any]) -> str:
    qos = f"#SBATCH --qos={selection['qos']}\n" if selection.get("qos") is not None else ""
    account = f"#SBATCH --account={selection['account']}\n" if selection.get("account") is not None else ""
    setup = "\n".join(_runtime_environment(runtime, "srun"))
    hydra = runtime["launchers"].get("hydra")
    hydra_check = ""
    if isinstance(hydra, Mapping) and hydra.get("required") is not False:
        hydra_setup = "\n".join(_runtime_environment(runtime, "hydra"))
        hydra_command = " ".join(shlex.quote(str(item)) for item in [hydra["selected_executable"], *hydra["arguments"], "hostname"])
        hydra_check = f"\n  {hydra_setup}\n  {hydra_command}\n"
    return f"""#!/usr/bin/env bash
#SBATCH --job-name=QRAFT_M10_PREFLIGHT
#SBATCH --partition={selection['partition']}
{account}{qos}#SBATCH --nodes=2
#SBATCH --ntasks=64
#SBATCH --ntasks-per-node=32
#SBATCH --time=00:05:00
#SBATCH --output=preflight/preflight.%j.out
#SBATCH --error=preflight/preflight.%j.err
set -euo pipefail
ROOT="$(cd "${{SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR required}}" && pwd -P)"
cd "$ROOT"; mkdir -p evidence
MARKER="$ROOT/evidence/m10-shared-filesystem.marker"; MANIFEST="$ROOT/bundle_manifest.json"
printf 'QRAFT M10 shared filesystem marker\\n' > "$MARKER"
{{
  scontrol --version || scontrol version || true
  printf 'SLURM_JOB_ID=%s\\nSLURM_JOB_PARTITION=%s\\nSLURM_NNODES=%s\\nSLURM_SUBMIT_DIR=%s\\n' "$SLURM_JOB_ID" "${{SLURM_JOB_PARTITION:-}}" "$SLURM_NNODES" "$ROOT"
  mapfile -t M10_HOSTS < <(scontrol show hostnames "${{SLURM_JOB_NODELIST:?SLURM_JOB_NODELIST required}}")
  [[ "${{#M10_HOSTS[@]}}" -eq 2 ]] || {{ echo "M10_PREFLIGHT_ALLOCATION_HOST_COUNT_INVALID:${{#M10_HOSTS[@]}}" >&2; exit 1; }}
  {setup}
  command -v {shlex.quote(runtime['python']['selected_executable'])}
  {shlex.quote(runtime['python']['selected_executable'])} -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
  command -v {shlex.quote(runtime['siesta']['selected_executable'])}
  env | LC_ALL=C sort | grep '^SLURM_' || true
  export M10_SHARED_MARKER="$MARKER" M10_SHARED_MANIFEST="$MANIFEST"
  srun --nodes=2 --ntasks=2 --ntasks-per-node=1 bash -c 'set -eu; printf "host=%s path=%s marker_sha256=%s manifest_sha256=%s\\n" "$(hostname -f 2>/dev/null || hostname)" "$M10_SHARED_MARKER" "$(sha256sum "$M10_SHARED_MARKER" | awk "{{print \\$1}}")" "$(sha256sum "$M10_SHARED_MANIFEST" | awk "{{print \\$1}}")"'
  srun --nodes=2 --ntasks=64 --ntasks-per-node=32 hostname | LC_ALL=C sort | uniq -c | tee "evidence/srun-placement.${{SLURM_JOB_ID}}.txt"
  [[ "$(awk 'NR==1 {{a=$1}} NR==2 {{b=$1}} END {{print NR ":" a ":" b}}' "evidence/srun-placement.${{SLURM_JOB_ID}}.txt")" =~ ^2:32:32$ ]] || {{ echo "M10_PREFLIGHT_SRUN_PLACEMENT_INVALID" >&2; exit 1; }}{hydra_check}
}} | tee "evidence/preflight.${{SLURM_JOB_ID}}.txt"
"""


def _discovery_readme() -> str:
    return """# M10 scheduler discovery (manual)

`HISTORICAL_ONLY_NOT_CURRENT_AUTHORITY`: prior observations were partition
`tt2d-64p`, account `vini`, QoS `normal`. They are hints only and are not used
by this bundle. This directory is self-contained for login-node discovery:
`run_login_probe.sh` captures Bash-only, read-only raw evidence and never calls
Python. Review its available module names before explicitly running
`run_runtime_candidate_probe.sh`; that isolated Bash probe verifies selected
module environments without launching ranks. On a machine with Python >=3.11,
`build_login_summary.py --runtime-probe ...`, `resolve_m10_scheduler.py`, and
`resolve_m10_runtime.py` produce reviewed selections. They never submit a job.
Both selections need human approval.
"""


def _unresolved(repository: Path, output: Path) -> dict[str, Any]:
    fixture = output / "scientific_fixture"
    hashes = _fixture(repository, fixture)
    discovery = output / "scheduler_discovery"
    discovery.mkdir()
    raw_probe = repository / "tools" / "m10_yoltla_raw_login_probe.sh"
    runtime_probe = repository / "tools" / "m10_yoltla_runtime_candidate_probe.sh"
    summary_builder = repository / "tools" / "build_yoltla_m10_login_summary.py"
    scheduler_resolver = repository / "tools" / "resolve_yoltla_m10_scheduler.py"
    runtime_resolver = repository / "tools" / "resolve_yoltla_m10_runtime.py"
    _copy_linux_text(raw_probe, discovery / "run_login_probe.sh")
    _copy_linux_text(runtime_probe, discovery / "run_runtime_candidate_probe.sh")
    _copy_linux_text(summary_builder, discovery / "build_login_summary.py")
    _copy_linux_text(scheduler_resolver, discovery / "resolve_m10_scheduler.py")
    _copy_linux_text(runtime_resolver, discovery / "resolve_m10_runtime.py")
    (discovery / "README.md").write_text(_discovery_readme(), encoding="utf-8", newline="\n")
    _write_json(discovery / "resource_requirements.json", {"nodes": 2, "ntasks": 64, "cpus_per_task": 1, "processes_per_node": 32, "walltime": "00:20:00"})
    manifest = {"schema_version": "1.0", "scheduler_profile_status": "UNRESOLVED", "runtime_profile_status": "UNRESOLVED", "resource_shape": RESOURCE_SHAPE, "historical_hint": HISTORICAL_HINT, "scientific_fixture_hashes": hashes, "raw_login_probe": {"source": "tools/m10_yoltla_raw_login_probe.sh", "sha256": _sha(raw_probe), "python_required": False, "module_required": False}, "runtime_candidate_probe": {"source": "tools/m10_yoltla_runtime_candidate_probe.sh", "sha256": _sha(runtime_probe), "python_required": False, "requires_explicit_modules": True, "launches_work": False}, "m10_scheduler_resolver": {"source": "tools/resolve_yoltla_m10_scheduler.py", "sha256": _sha(scheduler_resolver)}, "m10_runtime_resolver": {"source": "tools/resolve_yoltla_m10_runtime.py", "sha256": _sha(runtime_resolver)}, "remote_execution_status": "PENDING_REMOTE", "scientific_submit_scripts_generated": False}
    _write_json(output / "bundle_manifest.json", manifest)
    (output / "README.md").write_text("# QRAFT M10 unresolved discovery bundle\n\nNo scientific submit scripts are generated until a current, human-reviewed scheduler selection is supplied.\n", encoding="utf-8", newline="\n")
    return manifest


def _resolved(repository: Path, output: Path, selection_path: Path, runtime_path: Path) -> dict[str, Any]:
    selection = _load_scheduler_selection(selection_path)
    runtime = _load_runtime_selection(runtime_path)
    if not isinstance(runtime["launchers"].get("hydra"), Mapping) or runtime["launchers"]["hydra"].get("required") is False:
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: resolved M10 bundle requires reviewed Hydra acceptance")
    provenance = output / "provenance"; provenance.mkdir()
    copied_selection = provenance / "scheduler_selection.json"; shutil.copy2(selection_path, copied_selection)
    copied_runtime = provenance / "runtime_selection.json"; shutil.copy2(runtime_path, copied_runtime)
    sources = output / "sources"
    hydra = _siesta_campaign(repository, selection, runtime, "hydra", sources / "hydra")
    srun = _siesta_campaign(repository, selection, runtime, "srun", sources / "srun")
    continuation = _continuation_campaign(selection, runtime, sources / "continuation")
    packages = output / "packages"; packages.mkdir()
    builder = ControllerPackageBuilder(repository)
    provenance_files = {"provenance/scheduler_selection.json": copied_selection, "provenance/runtime_selection.json": copied_runtime}
    results = {"hydra": builder.build(hydra, packages / "hydra", provenance_files=provenance_files).__dict__, "srun": builder.build(srun, packages / "srun", provenance_files=provenance_files).__dict__, "continuation": builder.build(continuation, packages / "continuation", provenance_files=provenance_files).__dict__}
    equivalence = _equivalence(hydra, srun)
    _write_json(output / "backend_equivalence.json", equivalence)
    preflight = output / "preflight"; preflight.mkdir()
    _write_linux_text(preflight / "submit_m10_preflight.slurm", _preflight_script(selection, runtime))
    manifest = {"schema_version": "1.0", "scheduler_profile_status": "RESOLVED_FROM_CLUSTER_EVIDENCE", "runtime_profile_status": "RESOLVED_FROM_CLUSTER_EVIDENCE", "resource_shape": RESOURCE_SHAPE, "scheduler_selection": {"relative_path": "provenance/scheduler_selection.json", "sha256": _sha(copied_selection), "account": selection.get("account"), "partition": selection["partition"], "qos": selection.get("qos"), "source_files": selection["source_files"], "evidence_status_by_field": selection["evidence_status_by_field"]}, "runtime_selection": {"relative_path": "provenance/runtime_selection.json", "sha256": _sha(copied_runtime), "python_requirement": runtime["python"]["requirement"], "environment_setup": [*runtime["python"]["environment_setup"], *runtime["siesta"]["environment_setup"]]}, "packages": results, "backend_equivalence": equivalence, "continuation_external_allocations": {"first_seconds": 60, "second_seconds": 180, "same_package_root_and_config": True}, "execution_authority": "ControllerPackageBuilder -> CanonicalController -> CompiledWorkflowRuntime", "remote_execution_status": "PENDING_REMOTE"}
    _write_json(output / "bundle_manifest.json", manifest)
    return manifest


def build_bundle(repository: Path, output: Path, *, scheduler_selection: Path | None = None, runtime_selection: Path | None = None) -> dict[str, Any]:
    repository, output = repository.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite M10 bundle: {output}")
    output.mkdir(parents=True)
    if scheduler_selection is None and runtime_selection is None:
        return _unresolved(repository, output)
    if scheduler_selection is None or runtime_selection is None:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: resolved bundle requires scheduler_selection.json and runtime_selection.json")
    return _resolved(repository, output, scheduler_selection.resolve(), runtime_selection.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scheduler-selection", type=Path)
    parser.add_argument("--runtime-selection", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_bundle(Path(__file__).resolve().parents[1], args.output, scheduler_selection=args.scheduler_selection, runtime_selection=args.runtime_selection), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
