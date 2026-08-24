"""Build the self-contained M4 single-allocation remote smoke package."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .execution.allocation_controller import load_controller_config
from .project_packages import load_structured


PACKAGE_ID = "M4_SURF_GR5X5_SINGLE_ALLOCATION_REMOTE_SMOKE"
SYSTEM_ID = "SURF_Gr5x5_clean_v01"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe package path: {value}")
    return path


@dataclass(frozen=True)
class M4PackageResult:
    package_id: str
    destination: str
    zip_path: str
    zip_sha256: str
    files: tuple[str, ...]
    status: str = "SURF_GR5X5_REMOTE_SMOKE_PACKAGE_READY"


class M4RemoteSmokePackager:
    """Create a package with vendored stdlib-only runtime and protected inputs."""

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()

    def build(self, profile_path: Path, output_root: Path) -> M4PackageResult:
        profile = load_structured(profile_path)
        campaign = self._campaign(profile)
        destination = output_root.resolve() / PACKAGE_ID
        zip_path = output_root.resolve() / f"{PACKAGE_ID}.zip"
        if destination.exists() or zip_path.exists():
            raise FileExistsError(f"refusing to overwrite M4 package: {destination} or {zip_path}")
        files = self._files(profile, campaign)
        immutable = {name: _sha(content) for name, content in sorted(files.items())}
        manifest = {
            "schema_version": "1.0", "package_id": PACKAGE_ID, "system_id": SYSTEM_ID,
            "purpose": "TECHNICAL_REMOTE_SIESTA_SMOKE",
            "scientific_interpretation_allowed": False,
            "production_calculation": False,
            "login_node_persistent_process_required": False,
            "execution_authority": "CompiledWorkflowRuntime",
            "legacy_scheduler_default": False,
            "immutable_files": immutable,
        }
        files["manifest.json"] = _json(manifest)
        files["checksums.sha256"] = "".join(
            f"{_sha(content)}  {name}\n" for name, content in sorted(files.items())
        ).encode("utf-8")
        for name, content in files.items():
            target = destination.joinpath(*_safe_relative(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        # Validate through the exact runtime loader before producing the archive.
        load_controller_config(destination / "campaign.yaml")
        self._zip(destination, zip_path)
        return M4PackageResult(
            PACKAGE_ID, str(destination), str(zip_path), _sha(zip_path.read_bytes()), tuple(sorted(files)),
        )

    def _campaign(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        if str(profile.get("schema_version")) != "1.0":
            raise ValueError("unsupported M4 profile schema")
        slurm = profile.get("slurm")
        resources = profile.get("resources")
        runtime = profile.get("runtime")
        task = profile.get("task")
        if not all(isinstance(item, Mapping) for item in (slurm, resources, runtime, task)):
            raise ValueError("M4 profile requires slurm, resources, runtime and task mappings")
        source_fdf = self.repository_root / "remote_validation" / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE" / "input" / "smoke.fdf"
        source_pseudo = self.repository_root / "examples" / "reference_projects" / "graphene_surf_gr5x5" / "pseudopotentials" / "C.psml"
        source_geometry = self.repository_root / "examples" / "reference_projects" / "graphene_surf_gr5x5" / "systems" / "SURF_Gr5x5_clean_v01.xyz"
        for path in (source_fdf, source_pseudo, source_geometry):
            if not path.is_file():
                raise ValueError(f"missing protected M4 source: {path}")
        input_hashes = {
            "input/smoke.fdf": _sha(source_fdf.read_bytes()),
            "pseudopotentials/C.psml": _sha(source_pseudo.read_bytes()),
            "geometry/SURF_Gr5x5_clean_v01.xyz": _sha(source_geometry.read_bytes()),
        }
        campaign = {
            "schema_version": "1.0", "campaign_id": PACKAGE_ID, "system_id": SYSTEM_ID,
            "classification": ["TECHNICAL_REMOTE_SIESTA_SMOKE", "SCIENTIFIC_INTERPRETATION_FORBIDDEN"],
            "slurm": dict(slurm), "resources": dict(resources), "runtime": dict(runtime),
            "tasks": [{
                "task_id": "surf-gr5x5-remote-smoke", "input": "input/smoke.fdf",
                "input_hashes": input_hashes,
                "required_artifacts": list(task.get("required_artifacts", [])),
                "mpi_processes": task.get("mpi_processes"),
                "cpus_per_process": task.get("cpus_per_process", 1),
                "estimated_runtime_seconds": task.get("estimated_runtime_seconds"),
                "max_attempts": task.get("max_attempts"),
                "require_scf_converged": bool(task.get("require_scf_converged", True)),
            }],
        }
        # Validate with a temporary JSON-compatible YAML before materialization.
        with tempfile.TemporaryDirectory(prefix="qraft-m4-") as directory:
            temporary = Path(directory) / "campaign.json"
            temporary.write_bytes(_json(campaign))
            load_controller_config(temporary)
        return campaign

    def _files(self, profile: Mapping[str, Any], campaign: Mapping[str, Any]) -> dict[str, bytes]:
        base = self.repository_root
        source_files = {
            "runtime/qraft/version.py": base / "src/qraft/version.py",
            "runtime/qraft/magnetism.py": base / "src/qraft/magnetism.py",
            "input/smoke.fdf": base / "remote_validation/M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE/input/smoke.fdf",
            "pseudopotentials/C.psml": base / "examples/reference_projects/graphene_surf_gr5x5/pseudopotentials/C.psml",
            "geometry/SURF_Gr5x5_clean_v01.xyz": base / "examples/reference_projects/graphene_surf_gr5x5/systems/SURF_Gr5x5_clean_v01.xyz",
            "runtime/qraft/models.py": base / "src/qraft/models.py",
            "runtime/qraft/project_packages.py": base / "src/qraft/project_packages.py",
            "runtime/qraft/execution/allocation_controller.py": base / "src/qraft/execution/allocation_controller.py",
            "runtime/qraft/execution/allocation_controller_compat.py": base / "src/qraft/execution/allocation_controller_compat.py",
            "runtime/qraft/execution/canonical_controller.py": base / "src/qraft/execution/canonical_controller.py",
            "runtime/qraft/execution/capability_plugins.py": base / "src/qraft/execution/capability_plugins.py",
            "runtime/qraft/execution/capability_runtime.py": base / "src/qraft/execution/capability_runtime.py",
            "runtime/qraft/execution/command_capability.py": base / "src/qraft/execution/command_capability.py",
            "runtime/qraft/execution/legacy_translation.py": base / "src/qraft/execution/legacy_translation.py",
            "runtime/qraft/execution/resource_coordinator.py": base / "src/qraft/execution/resource_coordinator.py",
            "runtime/qraft/execution/adapters.py": base / "src/qraft/execution/adapters.py",
            "runtime/qraft/execution/direct_launcher.py": base / "src/qraft/execution/direct_launcher.py",
            "runtime/qraft/execution/hydra_launcher.py": base / "src/qraft/execution/hydra_launcher.py",
            "runtime/qraft/execution/openmpi_launcher.py": base / "src/qraft/execution/openmpi_launcher.py",
            "runtime/qraft/execution/slurm_environment.py": base / "src/qraft/execution/slurm_environment.py",
            "runtime/qraft/execution/srun_launcher.py": base / "src/qraft/execution/srun_launcher.py",
            "runtime/qraft/engines/siesta/models.py": base / "src/qraft/engines/siesta/models.py",
            "runtime/qraft/engines/siesta/output_parser.py": base / "src/qraft/engines/siesta/output_parser.py",
            "runtime/qraft/output/__init__.py": base / "src/qraft/output/__init__.py",
            "runtime/qraft/output/contributor.py": base / "src/qraft/output/contributor.py",
            "runtime/qraft/output/csv_exporter.py": base / "src/qraft/output/csv_exporter.py",
            "runtime/qraft/output/model.py": base / "src/qraft/output/model.py",
            "runtime/qraft/output/text_writer.py": base / "src/qraft/output/text_writer.py",
        }
        for source in sorted((base / "src/qraft/contracts").glob("*.py")):
            source_files[
                f"runtime/qraft/contracts/{source.name}"
            ] = source
        for directory in (base / "src/qraft/core", base / "src/qraft/engines/siesta"):
            for source in sorted(item for item in directory.rglob("*") if item.is_file()):
                source_files[
                    f"runtime/{source.relative_to(base / 'src').as_posix()}"
                ] = source
        source_files.update({
            "runtime/qraft/engines/base.py": base / "src/qraft/engines/base.py",
            "runtime/qraft/errors.py": base / "src/qraft/errors.py",
            "runtime/qraft/filesystem.py": base / "src/qraft/filesystem.py",
            "runtime/qraft/hpc.py": base / "src/qraft/hpc.py",
        })
        files = {name: path.read_bytes() for name, path in source_files.items()}
        files.update({
            "runtime/qraft/__init__.py": (base / "src/qraft/__init__.py").read_bytes(),
            "runtime/qraft/execution/__init__.py": b'"""Allocation-local execution runtime."""\n',
            "runtime/qraft/engines/__init__.py": b'"""Engine namespace."""\n',
            "runtime/qraft/engines/siesta/__init__.py": b'"""Minimal SIESTA parser runtime."""\n',
            "campaign.yaml": _json(campaign),
            "campaign.slurm": self._slurm(campaign).encode("utf-8"),
            "scripts/run_worker.py": _worker().encode("utf-8"),
            "scripts/preflight.sh": self._preflight(campaign).encode("utf-8"),
            "scripts/inspect_job.sh": _inspect_job().encode("utf-8"),
            "verify_package.py": _verifier().encode("utf-8"),
            "README.md": _readme().encode("utf-8"),
            "EXACT_COMMANDS.md": _commands().encode("utf-8"),
            "PSEUDOPOTENTIAL_ATTRIBUTION.md": (
                "# Pseudopotential attribution\n\nC.psml: PseudoDojo; CC-BY-4.0; redistribution permitted with attribution.\n"
            ).encode("utf-8"),
        })
        return files

    def _slurm(self, campaign: Mapping[str, Any]) -> str:
        slurm = campaign["slurm"]
        resources = campaign["resources"]
        def directive(value: Any, name: str) -> str:
            text = str(value)
            if not text or not re.fullmatch(r"[A-Za-z0-9_.:+-]+", text):
                raise ValueError(f"unsafe SLURM directive value: {name}")
            return text
        modules = campaign["runtime"].get("module_commands", [])
        if not isinstance(modules, list):
            raise ValueError("runtime.module_commands must be a list")
        module_lines = "\n".join(str(item) for item in modules) or ": # no module commands configured"
        return f'''#!/usr/bin/env bash
#SBATCH --job-name=M4_SURF_GR5X5_SMOKE
#SBATCH --partition={directive(slurm["partition"], "partition")}
#SBATCH --account={directive(slurm["account"], "account")}
#SBATCH --qos={directive(slurm["qos"], "qos")}
#SBATCH --nodes={directive(resources["nodes"], "nodes")}
#SBATCH --ntasks={directive(resources["total_cpus"], "total_cpus")}
#SBATCH --cpus-per-task=1
#SBATCH --mem={directive(resources["memory"], "memory")}
#SBATCH --time={directive(resources["walltime"], "walltime")}
#SBATCH --signal=B:USR1@{int(resources["shutdown_margin_seconds"])}
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err
set -euo pipefail
[[ -n "${{SLURM_SUBMIT_DIR:-}}" ]] || {{ echo SLURM_SUBMIT_DIR_NOT_SET >&2; exit 2; }}
ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
[[ -f "$ROOT/manifest.json" ]] || {{ echo INVALID_PACKAGE_ROOT >&2; exit 2; }}
cd "$ROOT"
{module_lines}
export PYTHONPATH="$ROOT/runtime"
export PYTHONDONTWRITEBYTECODE=1
python3 "$ROOT/verify_package.py"
# The controller runs directly in this batch allocation. Only SIESTA uses srun.
exec python3 "$ROOT/scripts/run_worker.py" "$ROOT/campaign.yaml" "$ROOT"
'''

    def _preflight(self, campaign: Mapping[str, Any]) -> str:
        modules = campaign["runtime"].get("module_commands", [])
        module_lines = "\n".join(str(item) for item in modules) or ": # no module commands configured"
        srun_program = shlex.quote(str(campaign["runtime"]["srun_command"][0]))
        siesta_program = shlex.quote(str(campaign["runtime"]["siesta_executable"]))
        return f'''#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
cd "$ROOT"
{module_lines}
export PYTHONDONTWRITEBYTECODE=1
python3 verify_package.py
command -v python3 >/dev/null
command -v {srun_program} >/dev/null
command -v {siesta_program} >/dev/null
{siesta_program} --version >/dev/null 2>&1
echo M4_REMOTE_PREFLIGHT_PASS
'''

    @staticmethod
    def _zip(root: Path, destination: Path) -> None:
        with ZipFile(destination, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = PurePosixPath(PACKAGE_ID) / PurePosixPath(path.relative_to(root).as_posix())
                info = ZipInfo(relative.as_posix(), (1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = (0o755 if path.suffix in {".sh", ".py", ".slurm"} else 0o644) << 16
                archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)


def _worker() -> str:
    return '''#!/usr/bin/env python3
import json,sys
from pathlib import Path
from qraft.execution.allocation_controller import ExecutionStatus
from qraft.execution.canonical_controller import CanonicalController
campaign=Path(sys.argv[1]); root=Path(sys.argv[2])
controller=CanonicalController.from_file(campaign,root=root)
status=controller.run()
print(json.dumps({'campaign_id':controller.config.campaign_id,'job_id':controller.slurm.job_id,'status':status.value,'summary':str(controller.summary_path),'login_node_persistent_process_required':False},sort_keys=True))
raise SystemExit(0 if status is ExecutionStatus.COMPLETED else 2)
'''


def _inspect_job() -> str:
    return '''#!/usr/bin/env bash
set -euo pipefail
: "${1:?usage: inspect_job.sh JOB_ID}"
squeue -j "$1" || true
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,MaxRSS,NodeList,Partition,Account,QOS
'''


def _verifier() -> str:
    return r'''#!/usr/bin/env python3
import hashlib,json,re,subprocess,sys
from pathlib import Path,PurePosixPath
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parent
def fail(code,detail=''): raise SystemExit(code+(':'+detail if detail else ''))
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
if manifest.get('package_id')!='M4_SURF_GR5X5_SINGLE_ALLOCATION_REMOTE_SMOKE': fail('PACKAGE_ID_MISMATCH')
for name,expected in manifest.get('immutable_files',{}).items():
 p=PurePosixPath(name)
 if p.is_absolute() or '..' in p.parts or '\\' in name: fail('UNSAFE_PATH',name)
 target=root.joinpath(*p.parts)
 if not target.is_file() or target.is_symlink(): fail('MISSING_IMMUTABLE_FILE',name)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=expected: fail('IMMUTABLE_HASH_MISMATCH',name)
seen=set()
for line in (root/'checksums.sha256').read_text(encoding='utf-8').splitlines():
 m=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not m: fail('INVALID_CHECKSUM_LINE',line)
 expected,name=m.groups()
 if name in seen: fail('DUPLICATE_CHECKSUM',name)
 seen.add(name); target=root.joinpath(*PurePosixPath(name).parts)
 if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected: fail('CHECKSUM_MISMATCH',name)
mutable={'state','work','results','evidence'}
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='qraft.out' and p.relative_to(root).parts[0] not in mutable and not p.name.startswith('slurm-')}
if actual != seen|{'checksums.sha256'}: fail('CHECKSUM_COVERAGE_MISMATCH',str(sorted(actual^(seen|{'checksums.sha256'}))))
if any(p.is_symlink() for p in root.rglob('*')): fail('PACKAGE_SYMLINK_FORBIDDEN')
sys.path.insert(0,str(root/'runtime'))
from qraft.execution.allocation_controller import load_controller_config
load_controller_config(root/'campaign.yaml')
worker=(root/'scripts/run_worker.py').read_text(encoding='utf-8')
if 'CanonicalController' not in worker or 'AllocationController.from_file' in worker: fail('CANONICAL_RUNTIME_ENTRY_REQUIRED')
script=(root/'campaign.slurm').read_text(encoding='utf-8')
if re.search(r'^\s*srun\b.*run_worker',script,re.M): fail('CONTROLLER_MUST_NOT_USE_SRUN')
if 'exec python3 "$ROOT/scripts/run_worker.py"' not in script: fail('DIRECT_BATCH_CONTROLLER_MISSING')
for path in (root/'campaign.slurm',root/'scripts/preflight.sh',root/'scripts/inspect_job.sh'):
 result=subprocess.run(['bash','-n',path.relative_to(root).as_posix()],cwd=root,capture_output=True,text=True)
 if result.returncode: fail('BASH_SYNTAX_FAILURE',result.stderr.strip())
print('M4_PACKAGE_VERIFIED')
print('NO_LOGIN_PERSISTENT_PROCESS_REQUIRED')
'''


def _readme() -> str:
    return f'''# {PACKAGE_ID}

Self-contained technical acceptance package for `{SYSTEM_ID}`. One `sbatch`
runs the canonical compiled-workflow runtime directly in its allocation; every
SIESTA calculation is a bounded `srun --exclusive` job step. State under
`state/`, attempts under `work/`, and summaries under `results/` survive a later
`sbatch` with a new job ID. No scientific interpretation is allowed.

The package profile is external data, not a core default. Run the preflight on
Yoltla before submission. A failed preflight must not be bypassed.
'''


def _commands() -> str:
    return f'''# Exact commands

## Package locally

```bash
python -m qraft.cli remote m4-package --profile config/remote_smokes/m4_surf_gr5x5_yoltla.yaml --output remote_validation --json
```

## Transfer manually

```bash
scp remote_validation/{PACKAGE_ID}.zip USER@YOLTLA_HOST:~/
```

## Verify on Yoltla

```bash
unzip {PACKAGE_ID}.zip
cd {PACKAGE_ID}
python3 verify_package.py
chmod u+x scripts/*.sh scripts/*.py
./scripts/preflight.sh
```

## Submit and inspect

```bash
JOB_ID=$(sbatch --parsable campaign.slurm)
echo "$JOB_ID"
squeue -j "$JOB_ID"
./scripts/inspect_job.sh "$JOB_ID"
```

## Resume in a new allocation

Only after the previous job is terminal:

```bash
NEW_JOB_ID=$(sbatch --parsable campaign.slurm)
echo "$NEW_JOB_ID"
squeue -j "$NEW_JOB_ID"
./scripts/inspect_job.sh "$NEW_JOB_ID"
```

Do not delete `state/`, `work/`, `evidence/`, or `results/` between submissions.
'''
