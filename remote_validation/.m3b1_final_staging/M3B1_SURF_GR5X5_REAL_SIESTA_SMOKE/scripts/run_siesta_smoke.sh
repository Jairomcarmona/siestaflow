#!/usr/bin/env bash
set -euo pipefail
[[ -n "${ROOT:-}" && -f "$ROOT/package_manifest.json" ]] || { echo INVALID_PACKAGE_ROOT >&2; exit 2; }
python3 "$ROOT/verify_package.py"
actual=$(sha256sum "$ROOT/pseudopotentials/C.psml" | awk '{print $1}')
[[ "$actual" == "ce0f6a7fd43e70d44018e94286d934e9caadc005e95da87500d85fbe501d4c41" ]] || { echo PSEUDOPOTENTIAL_HASH_MISMATCH >&2; exit 2; }
SIESTA_EXECUTABLE=""
for candidate in siesta siesta-5.4.2; do command -v "$candidate" >/dev/null 2>&1 && { SIESTA_EXECUTABLE=$(command -v "$candidate"); break; }; done
[[ -n "$SIESTA_EXECUTABLE" ]] || { echo SIESTA_EXECUTABLE_NOT_DISCOVERED >&2; exit 2; }
MPI_LAUNCHER=""
for candidate in srun mpiexec.hydra mpiexec mpirun; do command -v "$candidate" >/dev/null 2>&1 && { MPI_LAUNCHER=$(command -v "$candidate"); break; }; done
[[ -n "$MPI_LAUNCHER" ]] || { echo MPI_LAUNCHER_NOT_DISCOVERED >&2; exit 2; }
RUN="$ROOT/work/real_siesta_smoke"
[[ ! -e "$RUN" ]] || { echo REFUSING_OVERWRITE:$RUN >&2; exit 2; }
mkdir -p "$RUN" "$ROOT/results" "$ROOT/evidence/execution"
cp "$ROOT/input/smoke.fdf" "$RUN/smoke.fdf"
cp "$ROOT/pseudopotentials/C.psml" "$RUN/C.psml"
printf '%s\n' "$SIESTA_EXECUTABLE" >"$ROOT/evidence/execution/siesta_executable.txt"
printf '%s\n' "$MPI_LAUNCHER" >"$ROOT/evidence/execution/mpi_launcher.txt"
printf '%s\n' "${PWD:-}" >"$ROOT/evidence/execution/initial_pwd_observed_only.txt"
cd "$RUN"
set +e
if [[ "$(basename "$MPI_LAUNCHER")" == "srun" ]]; then
  "$MPI_LAUNCHER" -n "${SLURM_NTASKS:-1}" "$SIESTA_EXECUTABLE" <smoke.fdf >"$ROOT/results/siesta.out" 2>"$ROOT/results/siesta.err"
else
  "$MPI_LAUNCHER" -n "${SLURM_NTASKS:-1}" "$SIESTA_EXECUTABLE" <smoke.fdf >"$ROOT/results/siesta.out" 2>"$ROOT/results/siesta.err"
fi
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
