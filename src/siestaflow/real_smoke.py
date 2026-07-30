"""Evidence-bound, deterministic packaging for one real SIESTA smoke.

The distributed package is deliberately inert: it contains no executable
SLURM file and no guessed SIESTA or MPI command.  A SLURM file can only be
generated on the remote host after an operator captures and reviews runtime
discovery evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .engines.siesta.adapter import SiestaEngineAdapter
from .engines.siesta.fdf_renderer import FDFRenderer
from .models import DecisionStatus
from .slurm_renderer import SlurmProfile


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _safe_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError(f"unsafe package identifier: {value}")
    return value


def _repository_path(path: Path) -> str:
    """Return a portable provenance label without leaking a host path."""
    parts = path.resolve().parts
    for anchor in ("examples", "tests"):
        if anchor in parts:
            return PurePosixPath(*parts[parts.index(anchor):]).as_posix()
    return PurePosixPath(path.name).as_posix()


@dataclass(frozen=True)
class RealSmokeSpec:
    package_id: str
    system_id: str
    geometry_path: Path
    seed_fdf_path: Path
    pseudopotential_path: Path
    element: str
    atomic_number: int
    pseudopotential_provenance: str
    pseudopotential_license: str
    redistribution_status: str
    profile: SlurmProfile


@dataclass(frozen=True)
class RealSmokePackagePlan:
    package_id: str
    destination: str
    zip_path: str
    files: tuple[str, ...]
    zip_sha256: str
    status: str = "M3B1_V2_PACKAGE_READY_FOR_HUMAN_TRANSFER"


class RealSiestaSmokePackager:
    """Create an inert upload package; remote execution stays human-operated."""

    def __init__(self, spec: RealSmokeSpec) -> None:
        self.spec = spec

    def build_files(self) -> dict[str, bytes]:
        spec = self.spec
        _safe_name(spec.package_id)
        _safe_name(spec.system_id)
        for path, label in (
            (spec.geometry_path, "geometry"),
            (spec.seed_fdf_path, "FDF seed"),
            (spec.pseudopotential_path, "pseudopotential"),
        ):
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError(f"{label} source is not a regular file: {path}")
        if not spec.redistribution_status.startswith("PERMITTED") or not spec.pseudopotential_license:
            raise PermissionError("PSEUDOPOTENTIAL_NOT_AVAILABLE_FOR_PACKAGING")

        geometry_bytes = spec.geometry_path.read_bytes()
        geometry = _parse_extxyz(geometry_bytes, spec.geometry_path)
        if geometry["elements"] != {spec.element: geometry["atoms"]}:
            raise ValueError("geometry species do not match the declared single-species smoke")
        pseudo_bytes = spec.pseudopotential_path.read_bytes()
        pseudo = _inspect_psml(pseudo_bytes)
        if pseudo["element"] != spec.element or pseudo["atomic_number"] != spec.atomic_number:
            raise ValueError("pseudopotential identity does not match the declared species")
        fdf_bytes, fdf_evidence = _single_point_fdf(spec.seed_fdf_path, geometry)

        geometry_path = f"geometry/{spec.geometry_path.name}"
        pseudo_path = f"pseudopotentials/{spec.pseudopotential_path.name}"
        fdf_path = "input/smoke.fdf"
        files: dict[str, bytes] = {
            geometry_path: geometry_bytes,
            pseudo_path: pseudo_bytes,
            fdf_path: fdf_bytes,
            "scripts/run_login_discovery.sh": _login_discovery().encode(),
            "scripts/run_siesta_smoke.sh": _run_smoke().encode(),
            "scripts/inspect_job.sh": _inspect_job().encode(),
            "scripts/parse_siesta_result.py": _parse_result_script().encode(),
            "scripts/collect_results.py": _collect_results(spec.package_id).encode(),
            "prepare_smoke_job.py": _prepare_smoke_job(spec).encode(),
            "verify_package.py": _verify_package().encode(),
            "README_RUN.md": _readme(spec.package_id).encode(),
            "EXACT_COMMANDS.md": _exact_commands(spec.package_id).encode(),
            "PSEUDOPOTENTIAL_ATTRIBUTION.md": _attribution(spec).encode(),
        }
        # Bundle the exact existing parser implementation so result parsing is
        # independent of the source checkout after clean extraction.
        source_root = Path(__file__).resolve().parent
        for package_path, source_path in {
            "scripts/runtime_parser/siestaflow/models.py": source_root / "models.py",
            "scripts/runtime_parser/siestaflow/engines/siesta/models.py": source_root / "engines/siesta/models.py",
            "scripts/runtime_parser/siestaflow/engines/siesta/output_parser.py": source_root / "engines/siesta/output_parser.py",
        }.items():
            files[package_path] = source_path.read_bytes()
        for package_path in (
            "scripts/runtime_parser/siestaflow/__init__.py",
            "scripts/runtime_parser/siestaflow/engines/__init__.py",
            "scripts/runtime_parser/siestaflow/engines/siesta/__init__.py",
        ):
            files[package_path] = b""

        profile = spec.profile.to_dict()
        # A distributed manifest never claims SIESTA verification.  Runtime
        # verification belongs to evidence generated on the remote login host.
        profile["verified_for_siesta"] = False
        profile["launcher_command"] = None
        manifest = {
            "schema_version": "2.0",
            "package_id": spec.package_id,
            "package_type": "REAL_SIESTA_TECHNICAL_SMOKE",
            "remote_execution_mode": "HUMAN_OPERATED_EVIDENCE_BOUND",
            "geometry": {
                "system_id": spec.system_id,
                "origin": "REAL_VALIDATED_PROJECT_GEOMETRY",
                "packaged_path": geometry_path,
                "source_repository_path": _repository_path(spec.geometry_path),
                "source_sha256": _sha(geometry_bytes),
                "packaged_sha256": _sha(geometry_bytes),
                "identity_status": "GEOMETRY_BYTE_IDENTICAL",
                **geometry,
            },
            "pseudopotential": {
                "filename": spec.pseudopotential_path.name,
                "format": "psml",
                "packaged_path": pseudo_path,
                "source_repository_path": _repository_path(spec.pseudopotential_path),
                "source_sha256": _sha(pseudo_bytes),
                "packaged_sha256": _sha(pseudo_bytes),
                "element": spec.element,
                "atomic_number": spec.atomic_number,
                "provenance": spec.pseudopotential_provenance,
                "license_or_redistribution_status": spec.pseudopotential_license,
                "redistribution_status": spec.redistribution_status,
                "psml_metadata": pseudo,
            },
            "fdf": {
                **fdf_evidence,
                "packaged_path": fdf_path,
                "source_repository_path": _repository_path(spec.seed_fdf_path),
                "source_sha256": _sha(spec.seed_fdf_path.read_bytes()),
                "packaged_sha256": _sha(fdf_bytes),
            },
            "calculation": {
                "system": spec.system_id,
                "calculation_type": "single_point",
                "geometry_optimization": False,
                "molecular_dynamics": False,
                "spin_polarized": False,
                "number_of_atoms": geometry["atoms"],
                "number_of_species": 1,
                "species": [spec.element],
                "charge": 0,
                "bands": False,
                "dos": False,
                "pdos": False,
                "optical_properties": False,
                "restart": False,
                "campaign": False,
                "execution_purpose": "TECHNICAL_REMOTE_SIESTA_SMOKE",
                "scientific_calculation_performed": False,
                "scientific_interpretation_allowed": False,
                "production_calculation": False,
            },
            "scheduler_profile": profile,
            "runtime_gate": {
                "state": "REMOTE_DISCOVERY_REQUIRED",
                "preselected_siesta_executable": None,
                "preselected_launcher": None,
                "generated_slurm_distributed": False,
            },
            "files": {name: _sha(content) for name, content in sorted(files.items())},
        }
        files["package_manifest.json"] = _json(manifest)
        files["package_manifest.sha256"] = f"{_sha(files['package_manifest.json'])}  package_manifest.json\n".encode()
        files["checksums.sha256"] = "".join(
            f"{_sha(content)}  {name}\n" for name, content in sorted(files.items())
        ).encode()
        return files

    def package(self, output_root: Path) -> RealSmokePackagePlan:
        files = self.build_files()
        destination = output_root / self.spec.package_id
        zip_path = output_root / f"{self.spec.package_id}_V2_UPLOAD.zip"
        if destination.exists() or zip_path.exists():
            raise FileExistsError(f"refusing to overwrite package artifact under {output_root}")
        for name, content in sorted(files.items()):
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe package path: {name}")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        with ZipFile(zip_path, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name, content in sorted(files.items()):
                info = ZipInfo(f"{self.spec.package_id}/{name}", (1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content, compress_type=ZIP_DEFLATED, compresslevel=9)
        return RealSmokePackagePlan(
            self.spec.package_id, str(destination), str(zip_path), tuple(sorted(files)), _sha(zip_path.read_bytes())
        )


def _parse_extxyz(content: bytes, source: Path) -> dict[str, Any]:
    text = content.decode("utf-8")
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError(f"invalid XYZ: {source}")
    try:
        atoms = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError(f"invalid XYZ atom count: {source}") from exc
    match = re.search(r'Lattice="([^"]+)"', lines[1])
    if not match or len(match.group(1).split()) != 9:
        raise ValueError("extended XYZ lattice metadata with nine values is required")
    lattice = match.group(1).split()
    rows: list[list[str]] = []
    elements: dict[str, int] = {}
    for line in lines[2:2 + atoms]:
        fields = line.split()
        if len(fields) < 4:
            raise ValueError("invalid XYZ coordinate row")
        rows.append(fields[:4])
        elements[fields[0]] = elements.get(fields[0], 0) + 1
    if len(rows) != atoms:
        raise ValueError("XYZ atom count differs from coordinate rows")
    return {
        "atoms": atoms,
        "elements": elements,
        "coordinate_semantic_hash": _sha(json.dumps(rows, separators=(",", ":"))),
        "lattice_semantic_hash": _sha(json.dumps(lattice, separators=(",", ":"))),
        "atom_order_hash": _sha(json.dumps([row[0] for row in rows], separators=(",", ":"))),
    }


def _inspect_psml(content: bytes) -> dict[str, Any]:
    head = content[:16384].decode("utf-8", errors="replace")
    atom = re.search(r'<pseudo-atom-spec\s+atomic-label="([^"]+)"\s+atomic-number="([0-9]+)"', head)
    provenance = re.search(r'<provenance\s+creator="([^"]+)"\s+date="([^"]+)"', head)
    if not atom or not provenance or "<psml" not in head:
        raise ValueError("pseudopotential is not an auditable PSML file")
    return {"element": atom.group(1), "atomic_number": int(atom.group(2)), "creator": provenance.group(1), "creation_date": provenance.group(2)}


def _single_point_fdf(seed_path: Path, geometry: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    adapter = SiestaEngineAdapter()
    document = adapter.inspect_input(seed_path)
    nodes = document.scalars("MD.Steps")
    if len(nodes) != 1:
        raise ValueError("approved seed must explicitly declare exactly one MD.Steps")
    node = nodes[0]
    previous_steps = node.value
    eol = "\r\n" if node.raw.endswith("\r\n") else "\n"
    indent = node.raw[: len(node.raw) - len(node.raw.lstrip())]
    node.raw = f"{indent}{node.label} 0{eol}"
    node.value = "0"
    rendered = FDFRenderer().render(document)
    parsed = adapter.fdf.parse(rendered, source="input/smoke.fdf")
    validation = adapter.validate_input(parsed, require_pseudos=False)
    if validation.status in {DecisionStatus.FAIL, DecisionStatus.BLOCKED}:
        raise ValueError(f"rendered single-point FDF failed validation: {validation.status.value}")
    if validation.atoms != geometry["atoms"]:
        raise ValueError("FDF and canonical geometry atom counts differ")
    species = tuple(validation.species)
    if len(species) != 1 or geometry["elements"] != {species[0]: geometry["atoms"]}:
        raise ValueError("FDF and canonical geometry species differ")
    return rendered.encode(), {
        "renderer": "SiestaEngineAdapter+FDFRenderer",
        "validator": "SiestaInputValidator",
        "validator_status": validation.status.value,
        "authorized_technical_change": {"MD.Steps": {"from": previous_steps, "to": "0"}},
        "numerical_parameter_origin": "APPROVED_PROJECT_FDF_SEED",
    }


def _login_discovery() -> str:
    return r'''#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ -f "$ROOT/package_manifest.json" ]] || { echo "INVALID_PACKAGE_ROOT:$ROOT" >&2; exit 2; }
OUT="$ROOT/evidence/login_discovery"
[[ ! -e "$OUT" ]] || { echo "REFUSING_OVERWRITE:$OUT" >&2; exit 2; }
mkdir -p "$OUT/versions"
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/observed_at.txt"
for command_name in siesta siesta-5.4.2 srun mpiexec.hydra mpiexec mpirun; do
  resolved=$(command -v "$command_name" 2>/dev/null || true)
  if [[ -n "$resolved" ]]; then
    readlink -f "$resolved" >"$OUT/command_${command_name//./_}.txt" 2>/dev/null || printf '%s\n' "$resolved" >"$OUT/command_${command_name//./_}.txt"
    "$resolved" --version >"$OUT/versions/${command_name//./_}.txt" 2>&1 || true
  fi
done
if type module >/dev/null 2>&1; then
  module -t avail siesta >"$OUT/module_avail_siesta.txt" 2>&1 || true
  module -t list >"$OUT/module_list.txt" 2>&1 || true
else
  : >"$OUT/module_avail_siesta.txt"; : >"$OUT/module_list.txt"
fi
python3 - "$OUT" <<'PY'
import hashlib,json,pathlib,re,sys
o=pathlib.Path(sys.argv[1])
def modules(path):
 text=path.read_text(errors='replace')
 text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',text)
 return sorted({x.strip().rstrip('*') for x in re.split(r'[\s,]+',text) if '/' in x and not x.startswith('---')})
def command(name):
 p=o/('command_'+name.replace('.','_')+'.txt')
 return p.read_text(errors='replace').strip() if p.is_file() else None
def version(name):
 p=o/'versions'/(name.replace('.','_')+'.txt')
 return p.read_text(errors='replace') if p.is_file() else ''
siesta=[]
for name in ('siesta','siesta-5.4.2'):
 path=command(name)
 if path:
  v=version(name)
  siesta.append({'name':name,'path':path,'version_output':v,'mpi_confirmed':bool(re.search(r'\bMPI\b',v,re.I))})
srun_path=command('srun')
others=[]
for name in ('mpiexec.hydra','mpiexec','mpirun'):
 path=command(name)
 if path: others.append({'name':name,'path':path,'version_output':version(name)})
d={'source':'REAL_REMOTE_LOGIN_DISCOVERY','modules_observed':modules(o/'module_avail_siesta.txt'),'modules_loaded':modules(o/'module_list.txt'),'siesta_executables':siesta,'srun':({'path':srun_path,'version_output':version('srun')} if srun_path else None),'other_launchers':others,'scientific_calculation_performed':False,'job_submitted':False}
target=o/'runtime_candidates.json'; target.write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
(o/'runtime_candidates.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  runtime_candidates.json\n')
PY
echo "LOGIN_DISCOVERY_COMPLETE:$OUT/runtime_candidates.json"
'''


def _prepare_smoke_job(spec: RealSmokeSpec) -> str:
    scheduler = {"partition": spec.profile.partition, "account": spec.profile.account, "qos": spec.profile.qos}
    resources = {
        "nodes": spec.profile.nodes,
        "ntasks": spec.profile.ntasks,
        "cpus_per_task": spec.profile.cpus_per_task,
        "walltime": spec.profile.walltime,
        "signal": spec.profile.signal,
    }
    return r'''#!/usr/bin/env python3
import argparse,hashlib,json,re,subprocess,sys,tempfile
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parent
SCHEDULER=''' + repr(scheduler) + "\nRESOURCES=" + repr(resources) + r'''
def blocked(code, detail=''):
 print(code+(':'+detail if detail else ''),file=sys.stderr)
 print('SLURM_GENERATION_BLOCKED',file=sys.stderr)
 raise SystemExit(2)
def safe_runtime_path(value):
 return isinstance(value,str) and value.startswith('/') and not re.search(r'[\r\n\x00]',value)
parser=argparse.ArgumentParser()
parser.add_argument('--runtime-candidates',type=Path,required=True)
parser.add_argument('--siesta-executable')
parser.add_argument('--launcher')
parser.add_argument('--module',action='append',default=[])
args=parser.parse_args()
evidence=args.runtime_candidates.resolve()
try: data=json.loads(evidence.read_text(encoding='utf-8'))
except Exception as exc: blocked('INVALID_RUNTIME_EVIDENCE',str(exc))
hash_record=evidence.with_name('runtime_candidates.sha256')
if not hash_record.is_file(): blocked('RUNTIME_EVIDENCE_HASH_MISSING')
parts=hash_record.read_text().strip().split(None,1)
if len(parts)!=2 or parts[1]!='runtime_candidates.json' or hashlib.sha256(evidence.read_bytes()).hexdigest()!=parts[0]: blocked('RUNTIME_EVIDENCE_HASH_MISMATCH')
if data.get('source')!='REAL_REMOTE_LOGIN_DISCOVERY' or data.get('scientific_calculation_performed') is not False or data.get('job_submitted') is not False: blocked('INVALID_RUNTIME_EVIDENCE_PROVENANCE')
observed=data.get('siesta_executables') or []
if not observed: blocked('SIESTA_RUNTIME_NOT_OBSERVED')
if any(not safe_runtime_path(item.get('path')) for item in observed): blocked('INVALID_RUNTIME_PATH')
paths={item['path']:item for item in observed}
if args.siesta_executable:
 if args.siesta_executable not in paths: blocked('USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE')
 chosen=paths[args.siesta_executable]
elif len(observed)==1: chosen=observed[0]
else: blocked('SIESTA_RUNTIME_AMBIGUOUS_SELECTION')
srun=data.get('srun')
if not srun or not safe_runtime_path(srun.get('path')): blocked('SRUN_RUNTIME_NOT_OBSERVED')
if args.launcher and args.launcher!=srun['path']: blocked('USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE')
if chosen.get('mpi_confirmed') is not True: blocked('SIESTA_MPI_RUNTIME_NOT_CONFIRMED')
available=set(data.get('modules_observed') or [])|set(data.get('modules_loaded') or [])
modules=args.module or list(data.get('modules_loaded') or [])
if any(m not in available or not re.fullmatch(r'[A-Za-z0-9_+./@:-]+',m) for m in modules): blocked('USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE')
if any(SCHEDULER.get(k) in (None,'') for k in ('partition','account')): blocked('SCHEDULER_PROFILE_INCOMPLETE')
if any(RESOURCES.get(k) in (None,'') for k in ('nodes','ntasks','cpus_per_task','walltime','signal')): blocked('RESOURCE_PROFILE_INCOMPLETE')
generated=ROOT/'generated'
if generated.exists() and any(generated.iterdir()): blocked('REFUSING_OVERWRITE_GENERATED_RUNTIME')
generated.mkdir(exist_ok=True)
selection={'schema_version':'1.0','evidence_path':'evidence/login_discovery/runtime_candidates.json','evidence_sha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),'siesta_executable':chosen['path'],'launcher':srun['path'],'mpi_confirmed':True,'modules':modules,'resources':RESOURCES,'scientific_interpretation_allowed':False}
selection_bytes=(json.dumps(selection,sort_keys=True,indent=2)+'\n').encode()
qos=(f"#SBATCH --qos={SCHEDULER['qos']}\n" if SCHEDULER.get('qos') else '')
script=f"""#!/usr/bin/env bash
# Generated only from reviewed remote runtime evidence.
#SBATCH --job-name=''' + spec.system_id + r'''
#SBATCH --partition={SCHEDULER['partition']}
#SBATCH --account={SCHEDULER['account']}
{qos}#SBATCH --nodes={RESOURCES['nodes']}
#SBATCH --ntasks={RESOURCES['ntasks']}
#SBATCH --cpus-per-task={RESOURCES['cpus_per_task']}
#SBATCH --time={RESOURCES['walltime']}
#SBATCH --signal={RESOURCES['signal']}
#SBATCH --output=evidence/slurm-%j.out
#SBATCH --error=evidence/slurm-%j.err
set -euo pipefail
[[ -n "${{SLURM_SUBMIT_DIR:-}}" ]] || {{ echo SLURM_SUBMIT_DIR_NOT_SET >&2; exit 2; }}
ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
export ROOT SIESTA_RUNTIME_SELECTION="$ROOT/generated/runtime_selection.json"
[[ -f "$ROOT/package_manifest.json" && -f "$SIESTA_RUNTIME_SELECTION" ]] || {{ echo INVALID_PACKAGE_ROOT >&2; exit 2; }}
mkdir -p "$ROOT/evidence" "$ROOT/results" "$ROOT/work"
trap 'mkdir -p "$ROOT/evidence"; printf "%s\n" "{{\\\"signal_received\\\":true,\\\"signal\\\":\\\"USR1\\\"}}" > "$ROOT/evidence/signal_summary.json"; date -u +%Y-%m-%dT%H:%M:%SZ > "$ROOT/evidence/signal_received_at.txt"' USR1
cd "$ROOT"
bash scripts/run_siesta_smoke.sh
"""
with tempfile.TemporaryDirectory(dir=ROOT) as td:
 p=Path(td)/'job.slurm'; p.write_text(script,newline='\n')
 check=subprocess.run(['bash','-n',p.relative_to(ROOT).as_posix()],cwd=ROOT,capture_output=True,text=True)
 if check.returncode: blocked('GENERATED_SLURM_SYNTAX_FAILURE',check.stderr.strip())
(generated/'runtime_selection.json').write_bytes(selection_bytes)
(generated/'runtime_selection.sha256').write_text(hashlib.sha256(selection_bytes).hexdigest()+'  runtime_selection.json\n')
(generated/'submit_real_siesta_smoke.slurm').write_text(script,newline='\n')
print('EVIDENCE_BOUND_RUNTIME_SELECTION_PASS')
print('SIESTA_MPI_RUNTIME_GATE_PASS')
print('SLURM_GENERATED_FOR_HUMAN_REVIEW')
'''


def _run_smoke() -> str:
    return r'''#!/usr/bin/env bash
set -euo pipefail
[[ -n "${ROOT:-}" && -f "$ROOT/package_manifest.json" && -f "${SIESTA_RUNTIME_SELECTION:-}" ]] || { echo INVALID_RUNTIME_SELECTION >&2; exit 2; }
python3 "$ROOT/verify_package.py"
mapfile -t RUNTIME < <(python3 - "$SIESTA_RUNTIME_SELECTION" <<'PY'
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); r=p.with_name('runtime_selection.sha256').read_text().strip().split(None,1)
if len(r)!=2 or r[1]!='runtime_selection.json' or hashlib.sha256(p.read_bytes()).hexdigest()!=r[0]: raise SystemExit('RUNTIME_SELECTION_HASH_MISMATCH')
d=json.loads(p.read_text()); assert d['mpi_confirmed'] is True
print(d['siesta_executable']); print(d['launcher'])
for m in d.get('modules',[]): print(m)
PY
)
SIESTA_EXECUTABLE=${RUNTIME[0]}; MPI_LAUNCHER=${RUNTIME[1]}
if (( ${#RUNTIME[@]} > 2 )); then
  type module >/dev/null 2>&1 || { echo MODULE_COMMAND_NOT_AVAILABLE >&2; exit 2; }
  for module_name in "${RUNTIME[@]:2}"; do module load "$module_name"; done
fi
RUN="$ROOT/work/real_siesta_smoke"
[[ ! -e "$RUN" ]] || { echo "REFUSING_OVERWRITE:$RUN" >&2; exit 2; }
mkdir -p "$RUN" "$ROOT/results" "$ROOT/evidence/execution"
python3 - "$ROOT" "$RUN" <<'PY'
import hashlib,json,pathlib,shutil,sys
r=pathlib.Path(sys.argv[1]); run=pathlib.Path(sys.argv[2]); m=json.loads((r/'package_manifest.json').read_text())
for key in ('fdf','pseudopotential'):
 item=m[key]; src=r/item['packaged_path']
 if hashlib.sha256(src.read_bytes()).hexdigest()!=item['packaged_sha256']: raise SystemExit(key.upper()+'_HASH_MISMATCH')
 shutil.copy2(src,run/src.name)
PY
printf '%s\n' "$SIESTA_EXECUTABLE" >"$ROOT/evidence/execution/siesta_executable.txt"
printf '%s\n' "$MPI_LAUNCHER" >"$ROOT/evidence/execution/mpi_launcher.txt"
cd "$RUN"
set +e
"$MPI_LAUNCHER" -n "${SLURM_NTASKS}" "$SIESTA_EXECUTABLE" <smoke.fdf >"$ROOT/results/siesta.out" 2>"$ROOT/results/siesta.err"
code=$?
set -e
printf '%s\n' "$code" >"$ROOT/evidence/execution/exit_code.txt"
python3 - "$ROOT" "$code" <<'PY'
import datetime,json,os,pathlib,sys
r=pathlib.Path(sys.argv[1]); code=int(sys.argv[2])
d={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':os.environ.get('SLURM_JOB_ID'),'exit_code':code,'scientific_calculation_performed':True,'execution_purpose':'TECHNICAL_REMOTE_SIESTA_SMOKE','scientific_interpretation_allowed':False,'production_calculation':False}
(r/'evidence/execution/summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
PY
exit "$code"
'''


def _inspect_job() -> str:
    return r'''#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || { echo 'usage: inspect_job.sh JOB_ID' >&2; exit 2; }
OUT="$ROOT/evidence/accounting"; mkdir -p "$OUT"
squeue -h -j "$1" -o '%i|%T|%P|%a|%q|%M|%N' >"$OUT/squeue.txt" 2>"$OUT/squeue.err" || true
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,NodeList,Partition,Account,QOS >"$OUT/sacct.txt" 2>"$OUT/sacct.err" || true
python3 - "$OUT" "$1" <<'PY'
import json,pathlib,sys
o=pathlib.Path(sys.argv[1]); rows=[]
for line in (o/'sacct.txt').read_text(errors='replace').splitlines():
 f=line.strip().split('|')
 if len(f)>=3 and f[0]==sys.argv[2]: rows.append(f)
d={'job_id':sys.argv[2],'state':rows[0][1] if rows else None,'exit_code':rows[0][2] if rows else None}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
PY
python3 "$ROOT/scripts/parse_siesta_result.py" --package-root "$ROOT"
echo "ACCOUNTING_CAPTURED:$OUT"
'''


def _parse_result_script() -> str:
    return r'''#!/usr/bin/env python3
import argparse,hashlib,json,re,sys
from pathlib import Path
parser=argparse.ArgumentParser(); parser.add_argument('--package-root',type=Path,required=True); args=parser.parse_args()
root=args.package_root.resolve(); sys.path.insert(0,str(root/'scripts/runtime_parser'))
from siestaflow.engines.siesta.output_parser import SiestaOutputParser
from siestaflow.engines.siesta.models import OutputClassification
manifest=json.loads((root/'package_manifest.json').read_text())
stdout=(root/'results/siesta.out').read_text(errors='replace'); stderr=(root/'results/siesta.err').read_text(errors='replace')
record=SiestaOutputParser().parse((stdout+'\n'+stderr).splitlines(True))
execution=json.loads((root/'evidence/execution/summary.json').read_text())
accounting=json.loads((root/'evidence/accounting/summary.json').read_text())
raw=stdout+'\n'+stderr; state=str(accounting.get('state') or '').upper()
if record.normal_termination and record.scf_converged: termination='NORMAL_CONVERGED_TERMINATION'
elif record.normal_termination: termination='NORMAL_NONCONVERGED_TERMINATION'
elif record.classification is OutputClassification.INPUT_ERROR: termination='INPUT_FAILURE'
elif record.classification is OutputClassification.PSEUDOPOTENTIAL_ERROR: termination='PSEUDOPOTENTIAL_FAILURE'
elif re.search(r'\b(?:MPI_ABORT|srun: error|PMI error|MPI failure)\b',raw,re.I): termination='MPI_FAILURE'
elif re.search(r'(?:no space left|read-only file system|permission denied|I/O error)',raw,re.I): termination='FILESYSTEM_FAILURE'
elif state.startswith('TIMEOUT') or record.classification is OutputClassification.TIMEOUT: termination='TIME_LIMIT'
else: termination='UNKNOWN_FAILURE'
def hash_ok(key):
 item=manifest[key]; return hashlib.sha256((root/item['packaged_path']).read_bytes()).hexdigest()==item['packaged_sha256']
summary={'job_id':execution.get('job_id') or accounting.get('job_id'),'siesta_exit_code':execution.get('exit_code'),'sacct_state':accounting.get('state'),'sacct_exit_code':accounting.get('exit_code'),'normal_termination':record.normal_termination,'termination_class':termination,'scf_started':record.scf_started,'scf_converged':record.scf_converged,'scf_iterations':record.scf_iterations,'number_of_atoms':record.atoms or manifest['calculation']['number_of_atoms'],'number_of_species':record.species or manifest['calculation']['number_of_species'],'species':manifest['calculation']['species'],'geometry_hash_verified':hash_ok('geometry'),'fdf_hash_verified':hash_ok('fdf'),'pseudo_hash_verified':hash_ok('pseudopotential'),'NaN_detected':bool(re.search(r'\bnan\b',raw,re.I)),'MPI_failure_detected':termination=='MPI_FAILURE','filesystem_failure_detected':termination=='FILESYSTEM_FAILURE','scientific_interpretation_allowed':False,'parser':'SiestaOutputParser','parser_classification':record.classification.value}
target=root/'evidence/result_summary.json'; target.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
print('REAL_SIESTA_OUTPUT_PARSER_PASS')
'''


def _collect_results(package_id: str) -> str:
    return rf'''#!/usr/bin/env python3
import tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
required=[root/'package_manifest.json',root/'evidence/execution/summary.json',root/'evidence/accounting/summary.json',root/'evidence/result_summary.json',root/'results/siesta.out',root/'results/siesta.err']
missing=[str(p.relative_to(root)) for p in required if not p.is_file()]
if missing:raise SystemExit('MISSING_RESULT_EVIDENCE:'+','.join(missing))
out=root/'{package_id}_RESULTS.tar.gz'
if out.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(out))
with tarfile.open(out,'x:gz') as archive:
 for base in ('package_manifest.json','generated/runtime_selection.json','evidence','results'):
  path=root/base
  if path.exists():archive.add(path,arcname=base,recursive=True)
print(out)
'''


def _verify_package() -> str:
    return r'''#!/usr/bin/env python3
import hashlib,json,re,subprocess
from pathlib import Path,PurePosixPath
root=Path(__file__).resolve().parent
def fail(code,detail): raise SystemExit(f'{code}:{detail}')
def packaged(value):
 if not isinstance(value,str) or '\\' in value or re.match(r'^[A-Za-z]:',value): fail('UNSAFE_PACKAGED_PATH',str(value))
 p=PurePosixPath(value)
 if p.is_absolute() or '..' in p.parts or not p.parts: fail('UNSAFE_PACKAGED_PATH',value)
 candidate=root.joinpath(*p.parts)
 if candidate.is_symlink(): fail('UNSAFE_PACKAGE_SYMLINK',value)
 target=candidate.resolve()
 try: target.relative_to(root.resolve())
 except ValueError: fail('PACKAGED_PATH_OUTSIDE_ROOT',value)
 if not target.is_file() or target.is_symlink(): fail('PACKAGED_FILE_MISSING',value)
 return target
manifest_path=root/'package_manifest.json'; manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
record=(root/'package_manifest.sha256').read_text().strip().split(None,1)
if len(record)!=2 or record[1]!='package_manifest.json' or hashlib.sha256(manifest_path.read_bytes()).hexdigest()!=record[0]: fail('MANIFEST_HASH_MISMATCH','package_manifest.json')
seen=set()
for line in (root/'checksums.sha256').read_text().splitlines():
 match=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not match: fail('INVALID_CHECKSUM_RECORD',line)
 digest,name=match.groups()
 if name in seen: fail('DUPLICATE_CHECKSUM_RECORD',name)
 seen.add(name); target=packaged(name)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=digest: fail('PACKAGE_HASH_MISMATCH',name)
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.relative_to(root).parts[0] not in {'evidence','results','work','generated'}}-{'checksums.sha256'}
if seen!=actual: fail('CHECKSUM_COVERAGE_MISMATCH',str(sorted(actual^seen)))
for key in ('geometry','fdf','pseudopotential'):
 item=manifest[key]; target=packaged(item['packaged_path'])
 if hashlib.sha256(target.read_bytes()).hexdigest()!=item['packaged_sha256']: fail(key.upper()+'_HASH_MISMATCH',item['packaged_path'])
for path in root.rglob('*'):
 if path.is_symlink(): fail('UNSAFE_PACKAGE_SYMLINK',str(path.relative_to(root)))
 if path.is_file() and path.suffix in {'.sh','.slurm'}:
  result=subprocess.run(['bash','-n',path.relative_to(root).as_posix()],cwd=root,capture_output=True,text=True)
  if result.returncode: fail('BASH_SYNTAX_FAILURE',result.stderr.strip())
print('CLEAN_LINUX_EXTRACTION_VERIFICATION_PASS')
print('PORTABLE_MANIFEST_PASS')
print('M3B1_PACKAGE_VERIFIED')
'''


def _readme(package_id: str) -> str:
    return f"""# {package_id} V2

Portable, human-operated package for one real, non-production SIESTA technical
smoke. It contains no preselected SIESTA executable, launcher, or SLURM file.
Follow `EXACT_COMMANDS.md`. Runtime discovery and both generated files require
human review. Scientific interpretation is forbidden.
"""


def _exact_commands(package_id: str) -> str:
    return f"""# Exact remote commands

```bash
cd {package_id}
python3 verify_package.py
chmod u+x scripts/*.sh scripts/*.py prepare_smoke_job.py
./scripts/run_login_discovery.sh
cat evidence/login_discovery/runtime_candidates.json
```

STOP FOR HUMAN REVIEW. Select only a SIESTA MPI executable and `srun` recorded
in that evidence. Then generate, but do not submit, the job:

```bash
python3 prepare_smoke_job.py --runtime-candidates evidence/login_discovery/runtime_candidates.json
cat generated/runtime_selection.json
sed -n '1,240p' generated/submit_real_siesta_smoke.slurm
bash -n generated/submit_real_siesta_smoke.slurm
```

STOP FOR HUMAN REVIEW. This package intentionally ends here. A later authorized
phase may submit the reviewed generated file. Do not run `sbatch` in this phase.
"""


def _attribution(spec: RealSmokeSpec) -> str:
    return f"""# Pseudopotential attribution

- File: `{spec.pseudopotential_path.name}`
- Element / atomic number: `{spec.element}` / `{spec.atomic_number}`
- Provenance: {spec.pseudopotential_provenance}
- License recorded for redistribution: `{spec.pseudopotential_license}`
- Redistribution status: `{spec.redistribution_status}`
- Source project: PseudoDojo, https://www.pseudo-dojo.org/
- Citation: van Setten et al., Computer Physics Communications 226 (2018) 39-54.
"""
