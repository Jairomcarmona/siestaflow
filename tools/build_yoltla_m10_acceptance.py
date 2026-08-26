#!/usr/bin/env python3
"""Build evidence-bound, manual-only M10 Yoltla acceptance bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
MODULES = ["module purge", "module load siesta/5.4.2", "module load python/3.12"]
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


def _load_selection(path: Path) -> dict[str, Any]:
    """Validate the existing M3 scheduler-selection shape without a fallback."""

    if not path.is_file():
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: selection file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: selection must be an object")
    result = dict(data)
    for field in ("account", "partition", "memory"):
        result[field] = _required_scheduler_text(result.get(field), field)
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


def _slurm(selection: Mapping[str, Any]) -> dict[str, str]:
    result = {"partition": str(selection["partition"]), "account": str(selection["account"])}
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


def _siesta_campaign(repository: Path, selection: Mapping[str, Any], launcher: str, source: Path) -> Path:
    hashes = _fixture(repository, source)
    launcher_data: dict[str, Any] = {
        "kind": launcher, "command": ["mpiexec.hydra"] if launcher == "hydra" else ["srun"],
        "arguments": [], "bootstrap": "ssh",
    }
    if launcher == "hydra":
        launcher_data["processes_per_node"] = RESOURCE_SHAPE["processes_per_node"]
    campaign = {
        "schema_version": "2.0", "campaign_id": CAMPAIGN_ID, "system_id": SYSTEM_ID,
        "classification": ["NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "ENERGY_INTERPRETATION_FORBIDDEN"],
        "slurm": _slurm(selection),
        "resources": {"nodes": 2, "total_cpus": 64, "memory": selection["memory"], "walltime": "00:20:00", "max_parallel_steps": 1, "shutdown_margin_seconds": 120, "termination_grace_seconds": 30},
        "runtime": {"module_commands": MODULES, "siesta_executable": "siesta", "executable_arguments": [], "launcher": launcher_data, "exclusive": True, "environment": {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}},
        "tasks": [{"task_id": "M10_SIESTA_SMOKE", "input": "input/smoke.fdf", "input_hashes": hashes, "required_artifacts": [], "mpi_processes": 64, "cpus_per_process": 1, "nodes": 2, "estimated_runtime_seconds": 600, "max_attempts": 1, "require_scf_converged": True}],
    }
    path = source / "campaign.json"
    _write_json(path, campaign)
    return path


def _continuation_campaign(selection: Mapping[str, Any], source: Path) -> Path:
    (source / "input").mkdir(parents=True)
    input_path = source / "input" / "continuation-input.json"
    _write_json(input_path, {"classification": "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "purpose": "M10 allocation continuation"})
    digest = _sha(input_path)
    task_base = {"input": "input/continuation-input.json", "input_hashes": {"input/continuation-input.json": digest}, "required_artifacts": [], "mpi_processes": 1, "cpus_per_process": 1, "nodes": 0, "max_attempts": 2, "kind": "gate"}
    campaign = {
        "schema_version": "2.0", "campaign_id": CONTINUATION_CAMPAIGN_ID, "system_id": "M10_ALLOCATION_CONTINUATION_TECHNICAL",
        "classification": ["NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "ENERGY_INTERPRETATION_FORBIDDEN"], "slurm": _slurm(selection),
        "resources": {"nodes": 2, "total_cpus": 64, "memory": selection["memory"], "walltime": "00:03:00", "max_parallel_steps": 1, "shutdown_margin_seconds": CONTINUATION_SHUTDOWN_MARGIN_SECONDS, "termination_grace_seconds": 10},
        "runtime": {"module_commands": ["module purge", "module load python/3.12"], "siesta_executable": "python3", "executable_arguments": [], "launcher": {"kind": "srun", "command": ["srun"], "arguments": [], "bootstrap": "ssh"}, "exclusive": True, "environment": {}},
        "tasks": [
            {"task_id": "STAGE_A", "command": ["python3", "-c", "from pathlib import Path; import time; time.sleep(4); Path('stage_a.complete').write_text('complete\\n', encoding='utf-8')"], "estimated_runtime_seconds": CONTINUATION_STAGE_A_ESTIMATE_SECONDS, **task_base},
            {"task_id": "STAGE_B", "command": ["python3", "-c", "from pathlib import Path; import time; time.sleep(2); Path('stage_b.complete').write_text('complete\\n', encoding='utf-8')"], "depends_on": ["STAGE_A"], "estimated_runtime_seconds": CONTINUATION_STAGE_B_ESTIMATE_SECONDS, **task_base},
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


def _preflight_script(selection: Mapping[str, Any]) -> str:
    qos = f"#SBATCH --qos={selection['qos']}\n" if selection.get("qos") is not None else ""
    return f"""#!/usr/bin/env bash
#SBATCH --job-name=QRAFT_M10_PREFLIGHT
#SBATCH --partition={selection['partition']}
#SBATCH --account={selection['account']}
{qos}#SBATCH --nodes=2
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
  scontrol show hostnames "${{SLURM_JOB_NODELIST:?SLURM_JOB_NODELIST required}}"
  module list 2>&1 || true; module purge; module load siesta/5.4.2; module load python/3.12
  command -v python3; python3 --version || true
  command -v siesta; siesta --version || true
  command -v mpiexec.hydra; mpiexec.hydra -version || mpiexec.hydra --version || true
  env | LC_ALL=C sort | grep '^SLURM_' || true
  export M10_SHARED_MARKER="$MARKER" M10_SHARED_MANIFEST="$MANIFEST"
  srun --nodes=2 --ntasks=2 --ntasks-per-node=1 bash -c 'set -eu; printf "host=%s path=%s marker_sha256=%s manifest_sha256=%s\\n" "$(hostname -f 2>/dev/null || hostname)" "$M10_SHARED_MARKER" "$(sha256sum "$M10_SHARED_MARKER" | awk "{{print \\$1}}")" "$(sha256sum "$M10_SHARED_MANIFEST" | awk "{{print \\$1}}")"'
}} | tee "evidence/preflight.${{SLURM_JOB_ID}}.txt"
"""


def _discovery_readme() -> str:
    return """# M10 scheduler discovery (manual)

`HISTORICAL_ONLY_NOT_CURRENT_AUTHORITY`: prior observations were partition
`tt2d-64p`, account `vini`, QoS `normal`. They are hints only and are not used
by this bundle. This directory is self-contained for login-node discovery:
`run_login_probe.sh` captures current read-only scheduler evidence, then
`resolve_m10_scheduler.py` applies the M10 2-node / 64-rank request using the
copied M3 resolver authority. It never submits a job. Human review must approve
the resulting `scheduler_selection.json` before a resolved M10 bundle is built.
"""


def _unresolved(repository: Path, output: Path) -> dict[str, Any]:
    fixture = output / "scientific_fixture"
    hashes = _fixture(repository, fixture)
    discovery = output / "scheduler_discovery"
    discovery.mkdir()
    historical = repository / "remote_validation" / "M3_YOLTLA_ENVIRONMENT_PROBE"
    scripts = discovery / "scripts"
    scripts.mkdir()
    for name in ("probe_common.sh", "build_login_summary.py", "scheduler_resolution.py"):
        _copy_linux_text(historical / "scripts" / name, scripts / name)
    _copy_linux_text(historical / "run_login_probe.sh", discovery / "run_login_probe.sh")
    m10_resolver = repository / "tools" / "resolve_yoltla_m10_scheduler.py"
    _copy_linux_text(m10_resolver, discovery / "resolve_m10_scheduler.py")
    (discovery / "README.md").write_text(_discovery_readme(), encoding="utf-8", newline="\n")
    _write_json(discovery / "resource_requirements.json", {"nodes": 2, "ntasks": 64, "cpus_per_task": 1, "processes_per_node": 32, "walltime": "00:20:00"})
    resolver = scripts / "scheduler_resolution.py"
    manifest = {"schema_version": "1.0", "scheduler_profile_status": "UNRESOLVED", "resource_shape": RESOURCE_SHAPE, "historical_hint": HISTORICAL_HINT, "scientific_fixture_hashes": hashes, "scheduler_resolver": {"source": "remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE/scripts/scheduler_resolution.py", "sha256": _sha(resolver)}, "m10_scheduler_adapter": {"source": "tools/resolve_yoltla_m10_scheduler.py", "sha256": _sha(m10_resolver)}, "remote_execution_status": "PENDING_REMOTE", "scientific_submit_scripts_generated": False}
    _write_json(output / "bundle_manifest.json", manifest)
    (output / "README.md").write_text("# QRAFT M10 unresolved discovery bundle\n\nNo scientific submit scripts are generated until a current, human-reviewed scheduler selection is supplied.\n", encoding="utf-8", newline="\n")
    return manifest


def _resolved(repository: Path, output: Path, selection_path: Path) -> dict[str, Any]:
    selection = _load_selection(selection_path)
    provenance = output / "provenance"; provenance.mkdir()
    copied_selection = provenance / "scheduler_selection.json"; shutil.copy2(selection_path, copied_selection)
    sources = output / "sources"
    hydra = _siesta_campaign(repository, selection, "hydra", sources / "hydra")
    srun = _siesta_campaign(repository, selection, "srun", sources / "srun")
    continuation = _continuation_campaign(selection, sources / "continuation")
    packages = output / "packages"; packages.mkdir()
    builder = ControllerPackageBuilder(repository)
    provenance_files = {"provenance/scheduler_selection.json": copied_selection}
    results = {"hydra": builder.build(hydra, packages / "hydra", provenance_files=provenance_files).__dict__, "srun": builder.build(srun, packages / "srun", provenance_files=provenance_files).__dict__, "continuation": builder.build(continuation, packages / "continuation", provenance_files=provenance_files).__dict__}
    equivalence = _equivalence(hydra, srun)
    _write_json(output / "backend_equivalence.json", equivalence)
    preflight = output / "preflight"; preflight.mkdir()
    _write_linux_text(preflight / "submit_m10_preflight.slurm", _preflight_script(selection))
    manifest = {"schema_version": "1.0", "scheduler_profile_status": "RESOLVED_FROM_CLUSTER_EVIDENCE", "resource_shape": RESOURCE_SHAPE, "scheduler_selection": {"relative_path": "provenance/scheduler_selection.json", "sha256": _sha(copied_selection), "account": selection["account"], "partition": selection["partition"], "qos": selection.get("qos"), "source_files": selection["source_files"], "evidence_status_by_field": selection["evidence_status_by_field"]}, "packages": results, "backend_equivalence": equivalence, "continuation_external_allocations": {"first_seconds": 60, "second_seconds": 180, "same_package_root_and_config": True}, "execution_authority": "ControllerPackageBuilder -> CanonicalController -> CompiledWorkflowRuntime", "remote_execution_status": "PENDING_REMOTE"}
    _write_json(output / "bundle_manifest.json", manifest)
    return manifest


def build_bundle(repository: Path, output: Path, *, scheduler_selection: Path | None = None) -> dict[str, Any]:
    repository, output = repository.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite M10 bundle: {output}")
    output.mkdir(parents=True)
    return _unresolved(repository, output) if scheduler_selection is None else _resolved(repository, output, scheduler_selection.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scheduler-selection", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_bundle(Path(__file__).resolve().parents[1], args.output, scheduler_selection=args.scheduler_selection), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
