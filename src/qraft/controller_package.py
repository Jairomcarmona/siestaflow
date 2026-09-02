"""Build a self-contained schema-2 allocation-controller package."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .execution.allocation_controller import load_controller_config
from .project_packages import load_structured


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _safe(value: str) -> PurePosixPath:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe package path: {value}")
    return path


def _directive(value: Any, field: str) -> str:
    text = str(value)
    if not text or not re.fullmatch(r"[A-Za-z0-9_.:+-]+", text):
        raise ValueError(f"unsafe SLURM directive value: {field}")
    return text


@dataclass(frozen=True)
class ControllerPackageResult:
    package_id: str
    destination: str
    zip_path: str
    zip_sha256: str
    file_count: int
    status: str = "CONTROLLER_PACKAGE_READY_FOR_MANUAL_TRANSFER"


class ControllerPackageBuilder:
    """Vendor the tested runtime around an already materialized campaign."""

    RUNTIME_FILES = (
        "src/qraft/version.py",
        "src/qraft/magnetism.py",
        "src/qraft/models.py",
        "src/qraft/project_packages.py",
        "src/qraft/runtime_compatibility.py",
        "src/qraft/runtime_evidence.py",
        "src/qraft/execution/allocation_controller.py",
        "src/qraft/execution/allocation_controller_compat.py",
        "src/qraft/execution/canonical_controller.py",
        "src/qraft/execution/capability_plugins.py",
        "src/qraft/execution/capability_runtime.py",
        "src/qraft/execution/command_capability.py",
        "src/qraft/execution/legacy_translation.py",
        "src/qraft/execution/resource_coordinator.py",
        "src/qraft/execution/campaign_progress.py",
        "src/qraft/execution/adapters.py",
        "src/qraft/execution/direct_launcher.py",
        "src/qraft/execution/hydra_launcher.py",
        "src/qraft/execution/openmpi_launcher.py",
        "src/qraft/execution/placement_validation.py",
        "src/qraft/execution/slurm_environment.py",
        "src/qraft/execution/srun_launcher.py",
        "src/qraft/engines/siesta/models.py",
        "src/qraft/engines/siesta/output_parser.py",
        "src/qraft/output/__init__.py",
        "src/qraft/output/contributor.py",
        "src/qraft/output/csv_exporter.py",
        "src/qraft/output/model.py",
        "src/qraft/output/text_writer.py",
    )

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()

    def _runtime_files(self) -> tuple[str, ...]:
        contracts = tuple(
            path.relative_to(self.repository_root).as_posix()
            for path in sorted(
                (self.repository_root / "src/qraft/contracts").glob("*.py")
            )
        )
        if not contracts:
            raise ValueError("core contract runtime sources are missing")
        support = tuple(
            path.relative_to(self.repository_root).as_posix()
            for directory in (
                self.repository_root / "src/qraft/core",
                self.repository_root / "src/qraft/engines/siesta",
            )
            for path in sorted(
                item
                for item in directory.rglob("*")
                if item.is_file()
                and "__pycache__" not in item.parts
                and item.suffix != ".pyc"
            )
        )
        standalone = (
            "src/qraft/engines/base.py",
            "src/qraft/errors.py",
            "src/qraft/filesystem.py",
            "src/qraft/hpc.py",
        )
        return tuple(dict.fromkeys((*self.RUNTIME_FILES, *contracts, *support, *standalone)))

    def build(
        self,
        campaign_path: Path,
        output_root: Path,
        *,
        dry_run: bool = False,
        provenance_files: Mapping[str, Path] | None = None,
    ) -> ControllerPackageResult:
        campaign_path = campaign_path.resolve()
        source_root = campaign_path.parent
        config = load_controller_config(campaign_path)
        package_id = config.campaign_id
        destination = output_root.resolve() / package_id
        zip_path = output_root.resolve() / f"{package_id}.zip"
        protected = sorted({
            relative
            for task in config.tasks
            for relative in task.input_hashes
        })
        for relative in protected:
            source = source_root.joinpath(*_safe(relative).parts)
            if not source.is_file():
                raise ValueError(f"protected campaign input is missing: {relative}")
            expected = next(
                task.input_hashes[relative]
                for task in config.tasks if relative in task.input_hashes
            )
            if _sha(source.read_bytes()) != expected:
                raise ValueError(f"protected campaign input hash mismatch: {relative}")
        provenance: dict[str, bytes] = {}
        reserved = {
            "campaign.yaml",
            "manifest.json",
            "checksums.sha256",
            "submit.slurm",
            "verify_package.py",
            "progress.sh",
            "README.md",
        }
        for target_name, source_path in sorted(
            (provenance_files or {}).items()
        ):
            target = _safe(target_name).as_posix()
            source = source_path.expanduser().resolve()
            if (
                target in reserved
                or target.startswith(("runtime/", "scripts/"))
                or target in protected
            ):
                raise ValueError(
                    f"provenance file collides with package content: {target}"
                )
            if not source.is_file():
                raise ValueError(f"provenance file is missing: {source}")
            provenance[target] = source.read_bytes()
        if "run.lock.json" in provenance:
            self._validate_resolution_coherence(
                load_structured(campaign_path),
                json.loads(provenance["run.lock.json"].decode("utf-8")),
            )
        if destination.exists() or zip_path.exists():
            raise FileExistsError(
                f"refusing to overwrite controller package: {destination} or {zip_path}"
            )
        if dry_run:
            generated_targets = (
                "runtime/qraft/__init__.py",
                "runtime/qraft/execution/__init__.py",
                "runtime/qraft/engines/__init__.py",
                "runtime/qraft/engines/siesta/__init__.py",
                "scripts/run_worker.py",
                "scripts/progress.py",
                "submit.slurm",
                "progress.sh",
                "verify_package.py",
                "README.md",
            )
            planned_file_count = (
                1
                + len(protected)
                + len(provenance)
                + len(self._runtime_files())
                + len(generated_targets)
                + 2
            )
            return ControllerPackageResult(
                package_id,
                str(destination),
                str(zip_path),
                "",
                planned_file_count,
                "DRY_RUN_NO_SIDE_EFFECTS",
            )
        files: dict[str, bytes] = {}
        files["campaign.yaml"] = campaign_path.read_bytes()
        for relative in protected:
            files[relative] = source_root.joinpath(*_safe(relative).parts).read_bytes()
        files.update(provenance)
        for relative in self._runtime_files():
            source = self.repository_root / relative
            if not source.is_file():
                raise ValueError(f"runtime source is missing: {relative}")
            target = relative.removeprefix("src/")
            files[f"runtime/{target}"] = source.read_bytes()
        files.update({
            "runtime/qraft/__init__.py": (
                self.repository_root / "src/qraft/__init__.py"
            ).read_bytes(),
            "runtime/qraft/execution/__init__.py": b"",
            "runtime/qraft/engines/__init__.py": b"",
            "runtime/qraft/engines/siesta/__init__.py": b"",
            "scripts/run_worker.py": _worker().encode("utf-8"),
            "scripts/progress.py": _progress().encode("utf-8"),
            "submit.slurm": self._slurm(load_structured(campaign_path)).encode("utf-8"),
            "progress.sh": _progress_sh().encode("utf-8"),
            "verify_package.py": _verifier(package_id).encode("utf-8"),
            "README.md": _readme(package_id).encode("utf-8"),
        })
        immutable = {name: _sha(content) for name, content in sorted(files.items())}
        files["manifest.json"] = _json({
            "schema_version": "1.0",
            "package_id": package_id,
            "system_id": config.system_id,
            "launcher_kind": config.launcher_kind,
            "execution_authority": "CompiledWorkflowRuntime",
            "legacy_scheduler_default": False,
            "login_node_persistent_process_required": False,
            "immutable_files": immutable,
        })
        files["checksums.sha256"] = "".join(
            f"{_sha(content)}  {name}\n"
            for name, content in sorted(files.items())
        ).encode("utf-8")
        for name, content in files.items():
            target = destination.joinpath(*_safe(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        load_controller_config(destination / "campaign.yaml")
        self._zip(destination, zip_path, package_id)
        return ControllerPackageResult(
            package_id,
            str(destination),
            str(zip_path),
            _sha(zip_path.read_bytes()),
            len(files),
        )

    @staticmethod
    def _validate_resolution_coherence(
        campaign: Mapping[str, Any], run_lock: Mapping[str, Any],
    ) -> None:
        payload = run_lock.get("payload", {})
        metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
        resolution = metadata.get("execution_resolution") if isinstance(metadata, Mapping) else None
        if not isinstance(resolution, Mapping):
            return  # compatibility with run locks created before resolution.
        mode = resolution.get("resolution_mode")
        if mode == "PROFILE_ALREADY_RESOLVED":
            return
        if resolution.get("human_confirmed") is not True:
            raise ValueError("resolved run package requires explicit human confirmation")
        qos = campaign["slurm"].get("qos")
        expected = {
            "selected_partition": campaign["slurm"]["partition"],
            "selected_account": campaign["slurm"].get("account"),
            "selected_qos": qos,
            "selected_nodes": campaign["resources"]["nodes"],
            "selected_total_ranks": campaign["resources"].get(
                "ntasks", campaign["resources"]["total_cpus"]
            ),
            "selected_walltime": campaign["resources"]["walltime"],
        }
        if any(resolution.get(key) != value for key, value in expected.items()):
            raise ValueError("resolved execution and generated Slurm campaign disagree")

    def _slurm(self, campaign: dict[str, Any]) -> str:
        slurm = campaign["slurm"]
        resources = campaign["resources"]
        runtime = campaign["runtime"]
        modules = runtime.get("module_commands", [])
        if not isinstance(modules, list):
            raise ValueError("runtime.module_commands must be a list")
        rendered_modules: list[str] = []
        for command in map(str, modules):
            if re.fullmatch(r"\s*module\s+load\s+siesta(?:/[^\s]+)?\s*", command):
                rendered_modules.append(
                    f'if ! {command}; then\n'
                    '  echo "QRAFT_SIESTA_MODULE_LOAD_WARNING: continuing to executable verification" >&2\n'
                    'fi'
                )
            else:
                rendered_modules.append(command)
        module_lines = "\n".join(rendered_modules) or ": # no modules configured"
        siesta_executable = _directive(runtime["siesta_executable"], "siesta_executable")
        launcher = runtime.get("launcher", {})
        ppn = launcher.get("processes_per_node") if isinstance(launcher, dict) else None
        ntasks = resources.get("ntasks", resources["total_cpus"])
        cpus_per_task = resources.get("cpus_per_task", 1)
        total_cpus = resources["total_cpus"]
        for value, field in (
            (ntasks, "resources.ntasks"),
            (cpus_per_task, "resources.cpus_per_task"),
            (total_cpus, "resources.total_cpus"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if ntasks * cpus_per_task > total_cpus:
            raise ValueError("task placement exceeds allocated CPU capacity")
        if ppn is not None and resources["nodes"] * ppn != ntasks:
            raise ValueError("nodes * processes_per_node must equal ntasks")
        placement = (
            f"#SBATCH --ntasks-per-node={_directive(ppn, 'processes_per_node')}\n"
            if ppn is not None else ""
        )
        environment = runtime.get("environment", {})
        if not isinstance(environment, dict):
            raise ValueError("runtime.environment must be a mapping")
        python_executable = str(environment.get("QRAFT_PYTHON", "python3")).strip()
        if (
            not python_executable
            or "\x00" in python_executable
            or "\n" in python_executable
            or "\r" in python_executable
        ):
            raise ValueError("runtime QRAFT_PYTHON must be a non-empty executable path")
        environment_lines: list[str] = []
        for name, value in environment.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
                raise ValueError(f"unsafe environment variable name: {name}")
            if name == "QRAFT_PYTHON":
                continue
            environment_lines.append(f"export {name}={shlex.quote(str(value))}")
        environment_text = "\n".join(environment_lines) or ": # no environment overrides"
        signal_seconds = int(resources["shutdown_margin_seconds"])
        qos = slurm.get("qos")
        qos_directive = (
            f"#SBATCH --qos={_directive(qos, 'qos')}\n" if qos is not None else ""
        )
        account = slurm.get("account")
        account_directive = (
            f"#SBATCH --account={_directive(account, 'account')}\n"
            if account is not None else ""
        )
        return f"""#!/usr/bin/env bash
#SBATCH --job-name={_directive(campaign["campaign_id"], "campaign_id")[:64]}
#SBATCH --partition={_directive(slurm["partition"], "partition")}
{account_directive}{qos_directive}#SBATCH --nodes={_directive(resources["nodes"], "nodes")}
#SBATCH --ntasks={_directive(ntasks, "ntasks")}
{placement}#SBATCH --cpus-per-task={_directive(cpus_per_task, "cpus_per_task")}
#SBATCH --hint=nomultithread
#SBATCH --mem={_directive(resources["memory"], "memory")}
#SBATCH --time={_directive(resources["walltime"], "walltime")}
#SBATCH --signal=B:USR1@{signal_seconds}
#SBATCH --output=OUT.%x.%j
#SBATCH --error=ERROR.%x.%j
set -euo pipefail
ROOT="$(cd "${{SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR required}}" && pwd -P)"
cd "$ROOT"
{module_lines}
{environment_text}
export QRAFT_PYTHON={shlex.quote(python_executable)}
if ! command -v {siesta_executable} >/dev/null 2>&1; then
  echo "QRAFT_SIESTA_EXECUTABLE_UNAVAILABLE: {siesta_executable}" >&2
  exit 127
fi
export PYTHONPATH="$ROOT/runtime"
export PYTHONDONTWRITEBYTECODE=1
if ! command -v "$QRAFT_PYTHON" >/dev/null 2>&1; then
  echo "QRAFT_SELECTED_PYTHON_UNAVAILABLE: $QRAFT_PYTHON" >&2
  exit 127
fi
"$QRAFT_PYTHON" verify_package.py
exec "$QRAFT_PYTHON" scripts/run_worker.py campaign.yaml "$ROOT"
"""

    @staticmethod
    def _zip(root: Path, destination: Path, package_id: str) -> None:
        with ZipFile(
            destination, "x", compression=ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = PurePosixPath(package_id) / PurePosixPath(
                    path.relative_to(root).as_posix()
                )
                info = ZipInfo(relative.as_posix(), (1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = (
                    0o755 if path.suffix in {".sh", ".py", ".slurm"} else 0o644
                ) << 16
                archive.writestr(
                    info, path.read_bytes(), compress_type=ZIP_DEFLATED,
                    compresslevel=9,
                )


def _worker() -> str:
    return """#!/usr/bin/env python3
import json,sys
from pathlib import Path
from qraft.execution.allocation_controller import ExecutionStatus
from qraft.execution.canonical_controller import CanonicalController
campaign=Path(sys.argv[1]); root=Path(sys.argv[2])
controller=CanonicalController.from_file(campaign,root=root)
status=controller.run()
print(json.dumps({"campaign_id":controller.config.campaign_id,"job_id":controller.slurm.job_id,"status":status.value,"summary":str(controller.summary_path),"login_node_persistent_process_required":False},sort_keys=True))
raise SystemExit(0 if status is ExecutionStatus.COMPLETED else 2)
"""


def _progress() -> str:
    return """#!/usr/bin/env python3
from pathlib import Path
from qraft.execution.campaign_progress import read_campaign_progress,render_campaign_progress
print(render_campaign_progress(read_campaign_progress(Path("."))))
"""


def _progress_sh() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$ROOT"
export PYTHONPATH="$ROOT/runtime"
export PYTHONDONTWRITEBYTECODE=1
python3 scripts/progress.py
echo
echo "=== SLURM DEL USUARIO ==="
squeue -u "$USER" || true
"""


def _verifier(package_id: str) -> str:
    return f"""#!/usr/bin/env python3
import hashlib,json,re,subprocess,sys
from pathlib import Path,PurePosixPath
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parent
def fail(code,detail=""): raise SystemExit(code+(":"+detail if detail else ""))
manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
if manifest.get("package_id")!={package_id!r}: fail("PACKAGE_ID_MISMATCH")
for name,expected in manifest.get("immutable_files",{{}}).items():
 p=PurePosixPath(name)
 if p.is_absolute() or ".." in p.parts or "\\\\" in name: fail("UNSAFE_PATH",name)
 target=root.joinpath(*p.parts)
 if not target.is_file() or target.is_symlink(): fail("MISSING_IMMUTABLE_FILE",name)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=expected: fail("IMMUTABLE_HASH_MISMATCH",name)
seen=set()
for line in (root/"checksums.sha256").read_text(encoding="utf-8").splitlines():
 m=re.fullmatch(r"([0-9a-f]{{64}})\\s+(.+)",line)
 if not m: fail("INVALID_CHECKSUM_LINE",line)
 expected,name=m.groups()
 if name in seen: fail("DUPLICATE_CHECKSUM",name)
 seen.add(name); target=root.joinpath(*PurePosixPath(name).parts)
 if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected: fail("CHECKSUM_MISMATCH",name)
mutable={{"state","work","results","evidence"}}
actual={{p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name!="qraft.out" and p.relative_to(root).parts[0] not in mutable and not p.name.startswith(("OUT.","ERROR."))}}
if actual != seen|{{"checksums.sha256"}}: fail("CHECKSUM_COVERAGE_MISMATCH",str(sorted(actual^(seen|{{"checksums.sha256"}}))))
sys.path.insert(0,str(root/"runtime"))
from qraft.execution.allocation_controller import load_controller_config
load_controller_config(root/"campaign.yaml")
worker=(root/"scripts/run_worker.py").read_text(encoding="utf-8")
if "CanonicalController" not in worker or "AllocationController.from_file" in worker: fail("CANONICAL_RUNTIME_ENTRY_REQUIRED")
if (root/"run.lock.json").is_file():
 run=json.loads((root/"run.lock.json").read_text(encoding="utf-8"))
 resolution=run.get("payload",{{}}).get("metadata",{{}}).get("execution_resolution")
 if isinstance(resolution,dict) and resolution.get("resolution_mode")!="PROFILE_ALREADY_RESOLVED":
  if resolution.get("human_confirmed") is not True: fail("HUMAN_CONFIRMATION_REQUIRED")
  campaign=json.loads((root/"campaign.yaml").read_text(encoding="utf-8"))
  expected={{"selected_partition":campaign["slurm"]["partition"],"selected_account":campaign["slurm"].get("account"),"selected_qos":campaign["slurm"].get("qos"),"selected_nodes":campaign["resources"]["nodes"],"selected_total_ranks":campaign["resources"].get("ntasks",campaign["resources"]["total_cpus"]),"selected_walltime":campaign["resources"]["walltime"]}}
  if any(resolution.get(key)!=value for key,value in expected.items()): fail("RUN_LOCK_SUBMIT_COHERENCE_MISMATCH")
  directives={{}}
  for line in (root/"submit.slurm").read_text(encoding="utf-8").splitlines():
   match=re.fullmatch(r"#SBATCH --([^=]+)=(.+)",line)
   if match: directives[match.group(1)]=match.group(2)
  if directives.get("partition")!=expected["selected_partition"] or directives.get("account")!=expected["selected_account"] or directives.get("qos")!=expected["selected_qos"] or directives.get("nodes")!=str(expected["selected_nodes"]) or directives.get("ntasks")!=str(expected["selected_total_ranks"]) or directives.get("time")!=expected["selected_walltime"]: fail("RUN_LOCK_SUBMIT_COHERENCE_MISMATCH")
for path in ("submit.slurm","progress.sh"):
 result=subprocess.run(["bash","-n",path],cwd=root,capture_output=True,text=True)
 if result.returncode: fail("BASH_SYNTAX_FAILURE",result.stderr.strip())
print("QRAFT_CONTROLLER_PACKAGE_VERIFIED")
print("NO_LOGIN_PERSISTENT_PROCESS_REQUIRED")
"""


def _readme(package_id: str) -> str:
    return f"""# {package_id}

Self-contained QRAFT 0.2 canonical-runtime package. Compatibility translation
loads `campaign.yaml`, then `CompiledWorkflowRuntime` owns DAG state, resources,
attempts and recovery inside the allocation. Historical controller state is
handled only through the explicit compatibility API.

```bash
python3 verify_package.py
chmod +x progress.sh
sbatch --test-only submit.slurm
sbatch submit.slurm
./progress.sh
```
"""
