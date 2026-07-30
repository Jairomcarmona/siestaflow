#!/usr/bin/env python3
import argparse,hashlib,json,re,subprocess,sys,tempfile
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parent
SCHEDULER={'partition': 'q1h-20p', 'account': 'vini', 'qos': 'normal'}
RESOURCES={'nodes': 1, 'ntasks': 20, 'cpus_per_task': 1, 'walltime': '00:10:00', 'signal': 'B:USR1@60'}
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
#SBATCH --job-name=SURF_Gr5x5_clean_v01
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
