"""Build a self-contained schema-2 allocation-controller package."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
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
        "src/siestaflow/models.py",
        "src/siestaflow/project_packages.py",
        "src/siestaflow/execution/allocation_controller.py",
        "src/siestaflow/execution/campaign_progress.py",
        "src/siestaflow/execution/direct_launcher.py",
        "src/siestaflow/execution/hydra_launcher.py",
        "src/siestaflow/execution/slurm_environment.py",
        "src/siestaflow/execution/srun_launcher.py",
        "src/siestaflow/engines/siesta/models.py",
        "src/siestaflow/engines/siesta/output_parser.py",
    )

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()

    def _runtime_files(self) -> tuple[str, ...]:
        contracts = tuple(
            path.relative_to(self.repository_root).as_posix()
            for path in sorted(
                (self.repository_root / "src/siestaflow/contracts").glob("*.py")
            )
        )
        if not contracts:
            raise ValueError("core contract runtime sources are missing")
        return (*self.RUNTIME_FILES, *contracts)

    def build(
        self,
        campaign_path: Path,
        output_root: Path,
        *,
        dry_run: bool = False,
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
        if destination.exists() or zip_path.exists():
            raise FileExistsError(
                f"refusing to overwrite controller package: {destination} or {zip_path}"
            )
        if dry_run:
            return ControllerPackageResult(
                package_id, str(destination), str(zip_path), "", len(protected),
                "DRY_RUN_NO_SIDE_EFFECTS",
            )
        files: dict[str, bytes] = {}
        files["campaign.yaml"] = campaign_path.read_bytes()
        for relative in protected:
            files[relative] = source_root.joinpath(*_safe(relative).parts).read_bytes()
        for relative in self._runtime_files():
            source = self.repository_root / relative
            if not source.is_file():
                raise ValueError(f"runtime source is missing: {relative}")
            target = relative.removeprefix("src/")
            files[f"runtime/{target}"] = source.read_bytes()
        files.update({
            "runtime/siestaflow/__init__.py": b'"""Vendored SIESTAFLOW runtime."""\n',
            "runtime/siestaflow/execution/__init__.py": b"",
            "runtime/siestaflow/engines/__init__.py": b"",
            "runtime/siestaflow/engines/siesta/__init__.py": b"",
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

    def _slurm(self, campaign: dict[str, Any]) -> str:
        slurm = campaign["slurm"]
        resources = campaign["resources"]
        runtime = campaign["runtime"]
        modules = runtime.get("module_commands", [])
        if not isinstance(modules, list):
            raise ValueError("runtime.module_commands must be a list")
        module_lines = "\n".join(map(str, modules)) or ": # no modules configured"
        launcher = runtime.get("launcher", {})
        ppn = launcher.get("processes_per_node") if isinstance(launcher, dict) else None
        placement = (
            f"#SBATCH --ntasks-per-node={_directive(ppn, 'processes_per_node')}\n"
            if ppn is not None else ""
        )
        environment = runtime.get("environment", {})
        if not isinstance(environment, dict):
            raise ValueError("runtime.environment must be a mapping")
        environment_lines: list[str] = []
        for name, value in environment.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
                raise ValueError(f"unsafe environment variable name: {name}")
            environment_lines.append(f"export {name}={shlex.quote(str(value))}")
        if isinstance(launcher, dict) and launcher.get("kind") == "hydra":
            environment_lines.append(
                f"export I_MPI_HYDRA_BOOTSTRAP={shlex.quote(str(launcher.get('bootstrap', 'ssh')))}"
            )
        environment_text = "\n".join(environment_lines) or ": # no environment overrides"
        signal_seconds = int(resources["shutdown_margin_seconds"])
        return f"""#!/usr/bin/env bash
#SBATCH --job-name={_directive(campaign["campaign_id"], "campaign_id")[:64]}
#SBATCH --partition={_directive(slurm["partition"], "partition")}
#SBATCH --account={_directive(slurm["account"], "account")}
#SBATCH --qos={_directive(slurm["qos"], "qos")}
#SBATCH --nodes={_directive(resources["nodes"], "nodes")}
#SBATCH --ntasks={_directive(resources["total_cpus"], "total_cpus")}
{placement}#SBATCH --cpus-per-task=1
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
export PYTHONPATH="$ROOT/runtime"
export PYTHONDONTWRITEBYTECODE=1
python3 verify_package.py
exec python3 scripts/run_worker.py campaign.yaml "$ROOT"
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
from siestaflow.execution.allocation_controller import AllocationController,ExecutionStatus
campaign=Path(sys.argv[1]); root=Path(sys.argv[2])
controller=AllocationController.from_file(campaign,root=root)
status=controller.run()
print(json.dumps({"campaign_id":controller.config.campaign_id,"job_id":controller.slurm.job_id,"status":status.value,"summary":str(controller.summary_path),"login_node_persistent_process_required":False},sort_keys=True))
raise SystemExit(0 if status is ExecutionStatus.COMPLETED else 2)
"""


def _progress() -> str:
    return """#!/usr/bin/env python3
from pathlib import Path
from siestaflow.execution.campaign_progress import read_campaign_progress,render_campaign_progress
print(render_campaign_progress(read_campaign_progress(Path("."))))
"""


def _progress_sh() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$ROOT"
export PYTHONPATH="$ROOT/runtime"
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
actual={{p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.relative_to(root).parts[0] not in mutable and not p.name.startswith(("OUT.","ERROR."))}}
if actual != seen|{{"checksums.sha256"}}: fail("CHECKSUM_COVERAGE_MISMATCH",str(sorted(actual^(seen|{{"checksums.sha256"}}))))
sys.path.insert(0,str(root/"runtime"))
from siestaflow.execution.allocation_controller import load_controller_config
load_controller_config(root/"campaign.yaml")
for path in ("submit.slurm","progress.sh"):
 result=subprocess.run(["bash","-n",path],cwd=root,capture_output=True,text=True)
 if result.returncode: fail("BASH_SYNTAX_FAILURE",result.stderr.strip())
print("SIESTAFLOW_CONTROLLER_PACKAGE_VERIFIED")
print("NO_LOGIN_PERSISTENT_PROCESS_REQUIRED")
"""


def _readme(package_id: str) -> str:
    return f"""# {package_id}

Self-contained SIESTAFLOW 0.2 allocation-controller package. The Python
controller lives only inside the SLURM allocation. Scientific tasks use the
launcher declared in `campaign.yaml`; state, attempts and evidence survive
resubmission.

```bash
python3 verify_package.py
chmod +x progress.sh
sbatch --test-only submit.slurm
sbatch submit.slurm
./progress.sh
```
"""
