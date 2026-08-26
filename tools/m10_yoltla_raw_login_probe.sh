#!/usr/bin/env bash
# Mandatory M10 raw discovery: deliberately Bash-only and read-only.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
OUT="$ROOT/evidence/login_probe"
[[ ! -e "$OUT" ]] || { echo "REFUSING_OVERWRITE:$OUT" >&2; exit 2; }
mkdir -p "$OUT/raw" "$ROOT/evidence/stdout" "$ROOT/evidence/stderr"
run_optional() {
  local out="$1"; shift
  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout "${PROBE_COMMAND_TIMEOUT_SECONDS:-20}" "$@" >"$out" 2>&1
  else
    "$@" >"$out" 2>&1
  fi
  local code=$?
  set -e
  printf '%s\n' "$code" >"${out}.exit_code"
}
capture_command() { command -v "$1" >"$OUT/raw/command_${1//./_}.txt" 2>/dev/null || true; }
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/raw/observed_at.txt"
hostname >"$OUT/raw/hostname.txt" 2>/dev/null || true
id -un >"$OUT/raw/user.txt" 2>/dev/null || true
uname -srm >"$OUT/raw/system.txt" 2>/dev/null || true
printf '%s\n' "${SHELL:-unknown}" >"$OUT/raw/shell.txt"
printf '%s\n' "${PATH:-}" >"$OUT/raw/path.txt"
pwd -P >"$OUT/raw/working_path.txt"
df -Pk "$ROOT" >"$OUT/raw/df_project.txt" 2>&1 || true
env | LC_ALL=C sort | grep -E '^(SLURM|MODULE|LMOD|I_MPI_HYDRA_BOOTSTRAP|PATH|SHELL|TMPDIR|SCRATCH|HOME|USER)=' | grep -Evi '(TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL|COOKIE)' >"$OUT/raw/environment_redacted.txt" || true
for cmd in sbatch squeue sinfo sacct scontrol sacctmgr srun python python3 conda spack siesta mpirun mpiexec mpiexec.hydra; do capture_command "$cmd"; done
for cmd in python python3 srun mpirun mpiexec mpiexec.hydra siesta; do
  command -v "$cmd" >/dev/null 2>&1 && run_optional "$OUT/raw/${cmd//./_}_version.txt" "$cmd" --version
done
command -v mpiexec.hydra >/dev/null 2>&1 && run_optional "$OUT/raw/mpiexec_hydra_help.txt" mpiexec.hydra -help
run_optional "$OUT/raw/sinfo.txt" sinfo -h -o '%P|%a|%l|%D|%c|%m'
run_optional "$OUT/raw/squeue.txt" squeue -h -u "$(id -un 2>/dev/null || true)" -o '%i|%T|%P|%a|%q|%M|%N'
run_optional "$OUT/raw/sacct.txt" sacct -n -X -S now-1days -o JobID,State,ExitCode,Elapsed,Partition,Account,QOS
run_optional "$OUT/raw/scontrol_partitions.txt" scontrol show partition -o
run_optional "$OUT/raw/sacctmgr_assoc.txt" sacctmgr -n -P show assoc user="$(id -un 2>/dev/null || true)" format=Account,Partition,QOS
if type module >/dev/null 2>&1; then
  printf 'true\n' >"$OUT/raw/module_available.txt"
  module list >"$OUT/raw/module_list.txt" 2>&1 || true
  module -t avail python 2>&1 | head -n 100 >"$OUT/raw/module_python_candidates.txt" || true
  module -t avail siesta 2>&1 | head -n 100 >"$OUT/raw/module_siesta_candidates.txt" || true
else
  printf 'false\n' >"$OUT/raw/module_available.txt"
fi
printf 'false\n' >"$OUT/raw/conda_available.txt"; command -v conda >/dev/null 2>&1 && printf 'true\n' >"$OUT/raw/conda_available.txt"
printf 'false\n' >"$OUT/raw/spack_available.txt"; command -v spack >/dev/null 2>&1 && printf 'true\n' >"$OUT/raw/spack_available.txt"
echo "LOGIN_RAW_PROBE_COMPLETE:$OUT"
