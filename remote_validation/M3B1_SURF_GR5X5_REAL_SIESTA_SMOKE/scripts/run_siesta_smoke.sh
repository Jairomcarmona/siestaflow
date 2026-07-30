#!/usr/bin/env bash
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
