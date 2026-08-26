#!/usr/bin/env python3
"""Build the manual-only M10 Yoltla HPC portability acceptance bundle.

The bundle deliberately vendors the existing ControllerPackageBuilder worker.
It does not introduce a scheduler or execution authority outside
``CanonicalController -> CompiledWorkflowRuntime``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from qraft.controller_package import ControllerPackageBuilder
from qraft.execution.allocation_controller import load_controller_config
from qraft.execution.legacy_translation import translate_controller_config


CAMPAIGN_ID = "QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE"
SYSTEM_ID = "SURF_Gr5x5_clean_v01_TECHNICAL_ACCEPTANCE"
CONTINUATION_CAMPAIGN_ID = "QRAFT_M10_ALLOCATION_CONTINUATION_TECHNICAL"
PROFILE = {
    "partition": "tt2d-64p",
    "account": "vini",
    "qos": "normal",
    "nodes": 2,
    "total_cpus": 64,
    "processes_per_node": 32,
    "memory": "256000M",
}
MODULES = [
    "module purge",
    "module load siesta/5.4.2",
    "module load python/3.12",
]
CONTINUATION_FIRST_ALLOCATION_SECONDS = 60
CONTINUATION_SECOND_ALLOCATION_SECONDS = 180
CONTINUATION_STAGE_A_ESTIMATE_SECONDS = 5
CONTINUATION_STAGE_B_ESTIMATE_SECONDS = 90
CONTINUATION_SHUTDOWN_MARGIN_SECONDS = 10


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def _siesta_campaign(repository: Path, launcher: str, source: Path) -> Path:
    """Materialize byte-identical scientific inputs under an independent root."""

    fixture = repository / "remote_validation" / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE"
    (source / "input").mkdir(parents=True)
    (source / "pseudopotentials").mkdir()
    shutil.copy2(fixture / "input" / "smoke.fdf", source / "input" / "smoke.fdf")
    shutil.copy2(fixture / "pseudopotentials" / "C.psml", source / "pseudopotentials" / "C.psml")
    hashes = {
        "input/smoke.fdf": _sha(source / "input" / "smoke.fdf"),
        "pseudopotentials/C.psml": _sha(source / "pseudopotentials" / "C.psml"),
    }
    launcher_data: dict[str, Any] = {
        "kind": launcher,
        "command": ["mpiexec.hydra"] if launcher == "hydra" else ["srun"],
        "arguments": [],
        "bootstrap": "ssh",
    }
    if launcher == "hydra":
        launcher_data["processes_per_node"] = PROFILE["processes_per_node"]
    campaign = {
        "schema_version": "2.0",
        "campaign_id": CAMPAIGN_ID,
        "system_id": SYSTEM_ID,
        "classification": [
            "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE",
            "ENERGY_INTERPRETATION_FORBIDDEN",
        ],
        "slurm": {
            "partition": PROFILE["partition"], "account": PROFILE["account"], "qos": PROFILE["qos"],
        },
        "resources": {
            "nodes": PROFILE["nodes"], "total_cpus": PROFILE["total_cpus"],
            "memory": PROFILE["memory"], "walltime": "00:20:00",
            "max_parallel_steps": 1, "shutdown_margin_seconds": 120,
            "termination_grace_seconds": 30,
        },
        "runtime": {
            "module_commands": MODULES,
            "siesta_executable": "siesta",
            "executable_arguments": [], "launcher": launcher_data,
            "exclusive": True,
            "environment": {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        },
        "tasks": [{
            "task_id": "M10_SIESTA_SMOKE", "input": "input/smoke.fdf", "input_hashes": hashes,
            "required_artifacts": [], "mpi_processes": 64, "cpus_per_process": 1,
            "nodes": 2, "estimated_runtime_seconds": 600, "max_attempts": 1,
            "require_scf_converged": True,
        }],
    }
    path = source / "campaign.json"
    _write_json(path, campaign)
    return path


def _continuation_campaign(source: Path) -> Path:
    (source / "input").mkdir(parents=True)
    input_path = source / "input" / "continuation-input.json"
    _write_json(input_path, {"classification": "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "purpose": "M10 allocation continuation"})
    digest = _sha(input_path)
    # A 60-second first allocation has ample slack for A (60 > 5 + 10), but
    # cannot launch B (remaining < 90 + 10).  The same root/config submitted
    # with an external 180-second Slurm walltime reuses A and can launch B.
    stage_a = ["python3", "-c", "from pathlib import Path; import time; time.sleep(4); Path('stage_a.complete').write_text('complete\\n', encoding='utf-8')"]
    stage_b = ["python3", "-c", "from pathlib import Path; import time; time.sleep(2); Path('stage_b.complete').write_text('complete\\n', encoding='utf-8')"]
    task_base = {
        "input": "input/continuation-input.json", "input_hashes": {"input/continuation-input.json": digest},
        "required_artifacts": [], "mpi_processes": 1, "cpus_per_process": 1,
        "nodes": 0, "max_attempts": 2, "kind": "gate",
    }
    campaign = {
        "schema_version": "2.0", "campaign_id": CONTINUATION_CAMPAIGN_ID,
        "system_id": "M10_ALLOCATION_CONTINUATION_TECHNICAL",
        "classification": ["NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "ENERGY_INTERPRETATION_FORBIDDEN"],
        "slurm": {"partition": PROFILE["partition"], "account": PROFILE["account"], "qos": PROFILE["qos"]},
        "resources": {
            "nodes": 2, "total_cpus": 64, "memory": PROFILE["memory"], "walltime": "00:03:00",
            "max_parallel_steps": 1, "shutdown_margin_seconds": CONTINUATION_SHUTDOWN_MARGIN_SECONDS, "termination_grace_seconds": 10,
        },
        "runtime": {
            "module_commands": ["module purge", "module load python/3.12"], "siesta_executable": "python3",
            "executable_arguments": [], "launcher": {"kind": "srun", "command": ["srun"], "arguments": [], "bootstrap": "ssh"},
            "exclusive": True, "environment": {},
        },
        "tasks": [
            {"task_id": "STAGE_A", "command": stage_a, "estimated_runtime_seconds": CONTINUATION_STAGE_A_ESTIMATE_SECONDS, **task_base},
            {"task_id": "STAGE_B", "command": stage_b, "depends_on": ["STAGE_A"], "estimated_runtime_seconds": CONTINUATION_STAGE_B_ESTIMATE_SECONDS, **task_base},
        ],
    }
    path = source / "campaign.json"
    _write_json(path, campaign)
    return path


def _equivalence(hydra: Path, srun: Path) -> dict[str, Any]:
    hydra_plan = translate_controller_config(load_controller_config(hydra), root=hydra.parent)
    srun_plan = translate_controller_config(load_controller_config(srun), root=srun.parent)
    task_id = "M10_SIESTA_SMOKE"
    result = {
        "workflow_id_equal": hydra_plan.workflow.workflow_id == srun_plan.workflow.workflow_id,
        "workflow_definition_sha256_equal": hydra_plan.workflow.definition_sha256 == srun_plan.workflow.definition_sha256,
        "scientific_identity_equal": hydra_plan.scientific_identities[task_id].fingerprint == srun_plan.scientific_identities[task_id].fingerprint,
        "execution_spec_different": hydra_plan.execution_specs[task_id].fingerprint != srun_plan.execution_specs[task_id].fingerprint,
        "scientific_difference_present": False,
        "execution_backend_difference_only": True,
        "workflow_id": hydra_plan.workflow.workflow_id,
        "workflow_definition_sha256": hydra_plan.workflow.definition_sha256,
        "scientific_identity_sha256": hydra_plan.scientific_identities[task_id].fingerprint,
        "hydra_execution_spec_sha256": hydra_plan.execution_specs[task_id].fingerprint,
        "srun_execution_spec_sha256": srun_plan.execution_specs[task_id].fingerprint,
    }
    if not all(result[key] for key in (
        "workflow_id_equal", "workflow_definition_sha256_equal", "scientific_identity_equal",
        "execution_spec_different", "execution_backend_difference_only",
    )):
        raise ValueError("M10 backend equivalence precheck failed")
    return result


def _preflight_script() -> str:
    return """#!/usr/bin/env bash
#SBATCH --job-name=QRAFT_M10_PREFLIGHT
#SBATCH --partition=tt2d-64p
#SBATCH --nodes=2
#SBATCH --ntasks=64
#SBATCH --ntasks-per-node=32
#SBATCH --time=00:05:00
#SBATCH --output=evidence/preflight.%j.out
#SBATCH --error=evidence/preflight.%j.err
set -euo pipefail
ROOT="$(cd "${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR required}" && pwd -P)"
cd "$ROOT"
mkdir -p evidence
MARKER="$ROOT/evidence/m10-shared-filesystem.marker"
MANIFEST="$ROOT/backend_equivalence.json"
printf 'QRAFT M10 shared filesystem marker\\n' > "$MARKER"
{
  echo "QRAFT_M10_PREFLIGHT"
  scontrol --version || scontrol version
  printf 'SLURM_JOB_ID=%s\\nSLURM_JOB_PARTITION=%s\\n' "$SLURM_JOB_ID" "${SLURM_JOB_PARTITION:-}"
  printf 'SLURM_NNODES=%s\\nSLURM_SUBMIT_DIR=%s\\n' "$SLURM_NNODES" "$ROOT"
  echo 'ALLOCATED_HOSTS'; scontrol show hostnames "${SLURM_JOB_NODELIST:?SLURM_JOB_NODELIST required}"
  echo 'MODULES_BEFORE'; module list 2>&1 || true
  module purge
  module load siesta/5.4.2
  module load python/3.12
  echo 'MODULES_AFTER'; module list 2>&1 || true
  command -v python3; python3 --version
  command -v siesta; siesta --version
  command -v mpiexec.hydra; mpiexec.hydra -version || mpiexec.hydra --version
  echo 'SLURM_ENVIRONMENT'; env | LC_ALL=C sort | grep '^SLURM_' || true
  echo 'SHARED_FILESYSTEM_TWO_NODE_CHECK'
  export M10_SHARED_MARKER="$MARKER" M10_SHARED_MANIFEST="$MANIFEST"
  srun --nodes=2 --ntasks=2 --ntasks-per-node=1 bash -c 'set -eu; printf "host=%s path=%s marker_sha256=%s manifest_sha256=%s\\n" "$(hostname -f 2>/dev/null || hostname)" "$M10_SHARED_MARKER" "$(sha256sum "$M10_SHARED_MARKER" | awk "{print \\$1}")" "$(sha256sum "$M10_SHARED_MANIFEST" | awk "{print \\$1}")"'
} | tee "evidence/preflight.${SLURM_JOB_ID}.txt"
"""


def _bundle_readme() -> str:
    return """# QRAFT M10 manual Yoltla acceptance bundle

Classification: `NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE`; `ENERGY_INTERPRETATION_FORBIDDEN`.

This bundle is **USER MANUAL SBATCH ONLY**.  It provides no SSH automation,
credentials, or background agent.  `preflight/submit_m10_preflight.slurm` is
non-scientific.  `packages/hydra` and `packages/srun` each contain a canonical
QRAFT ControllerPackageBuilder worker; `packages/continuation` is the same
canonical runtime with technical gate tasks only.
"""


def build_bundle(repository: Path, output: Path) -> dict[str, Any]:
    """Create an immutable, independently rooted M10 manual acceptance bundle."""

    repository = repository.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite M10 bundle: {output}")
    output.mkdir(parents=True)
    source_root = output / "sources"
    hydra = _siesta_campaign(repository, "hydra", source_root / "hydra")
    srun = _siesta_campaign(repository, "srun", source_root / "srun")
    continuation = _continuation_campaign(source_root / "continuation")
    packages = output / "packages"
    packages.mkdir()
    builder = ControllerPackageBuilder(repository)
    results = {
        "hydra": builder.build(hydra, packages / "hydra").__dict__,
        "srun": builder.build(srun, packages / "srun").__dict__,
        "continuation": builder.build(continuation, packages / "continuation").__dict__,
    }
    equivalence = _equivalence(hydra, srun)
    _write_json(output / "backend_equivalence.json", equivalence)
    preflight = output / "preflight"
    preflight.mkdir()
    (preflight / "submit_m10_preflight.slurm").write_text(_preflight_script(), encoding="utf-8", newline="\n")
    (output / "README.md").write_text(_bundle_readme(), encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": "1.0", "baseline_profile": {**PROFILE, "availability": "CONFIRM_BY_REMOTE_PREFLIGHT"},
        "remote_execution_status": "PENDING_REMOTE", "packages": results,
        "backend_equivalence": equivalence,
        "continuation_external_allocations": {
            "first_seconds": CONTINUATION_FIRST_ALLOCATION_SECONDS,
            "second_seconds": CONTINUATION_SECOND_ALLOCATION_SECONDS,
            "same_package_root_and_config": True,
        },
        "execution_authority": "ControllerPackageBuilder -> CanonicalController -> CompiledWorkflowRuntime",
    }
    _write_json(output / "bundle_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_bundle(Path(__file__).resolve().parents[1], args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
