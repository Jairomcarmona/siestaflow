#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
source "$ROOT/scripts/probe_common.sh"
OUT="$ROOT/evidence/login_probe"
refuse_existing "$OUT"
mkdir -p "$OUT/raw" "$ROOT/evidence/stdout" "$ROOT/evidence/stderr"
LOG="$ROOT/evidence/stdout/login_probe.log"
ERR="$ROOT/evidence/stderr/login_probe.err"
exec > >(tee "$LOG") 2> >(tee "$ERR" >&2)
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/raw/observed_at.txt"
hostname >"$OUT/raw/hostname.txt"
id -un >"$OUT/raw/user.txt"
uname -srm >"$OUT/raw/system.txt"
printf '%s
' "${SHELL:-unknown}" >"$OUT/raw/shell.txt"
ulimit -a >"$OUT/raw/ulimit.txt"
df -Pk "$ROOT" >"$OUT/raw/df_project.txt"
run_optional "$OUT/raw/quota.txt" quota -s
if type module >/dev/null 2>&1; then
  printf 'true
' >"$OUT/raw/module_available.txt"
  module list >"$OUT/raw/module_list.txt" 2>&1 || true
  module spider siesta >"$OUT/raw/module_spider_siesta.txt" 2>&1 || true
  module avail siesta >"$OUT/raw/module_avail_siesta.txt" 2>&1 || true
  module -t avail siesta 2>&1 | grep -i 'siesta' | head -n 10 >"$OUT/raw/module_siesta_candidates.txt" || true
  while IFS= read -r candidate; do
    [[ "$candidate" =~ ^[A-Za-z0-9._/+:-]+$ ]] || continue
    module show "$candidate" >>"$OUT/raw/module_show_siesta.txt" 2>&1 || true
  done <"$OUT/raw/module_siesta_candidates.txt"
else
  printf 'false
' >"$OUT/raw/module_available.txt"
fi
for cmd in sbatch squeue sinfo sacct scontrol sacctmgr srun mpirun mpiexec mpiexec.hydra siesta siesta-5.4.2; do
  command -v "$cmd" >"$OUT/raw/command_${cmd//./_}.txt" 2>/dev/null || true
done
run_optional "$OUT/raw/sinfo.txt" sinfo -h -o '%P|%a|%l|%D|%c|%m'
run_optional "$OUT/raw/squeue.txt" squeue -h -u "$(id -un)" -o '%i|%T|%P|%a|%q|%M|%N'
run_optional "$OUT/raw/sacct.txt" sacct -n -X -S now-1days -o JobID,State,ExitCode,Elapsed,Partition,Account,QOS
run_optional "$OUT/raw/scontrol_partitions.txt" scontrol show partition -o
run_optional "$OUT/raw/sacctmgr_assoc.txt" sacctmgr -n -P show assoc user="$(id -un)" format=Account,Partition,QOS
for cmd in srun mpirun mpiexec mpiexec.hydra; do
  if command -v "$cmd" >/dev/null 2>&1; then run_optional "$OUT/raw/${cmd//./_}_version.txt" "$cmd" --version; fi
done
env | grep -E '^(SLURM|MODULE|LMOD|PATH|SHELL|TMPDIR|SCRATCH|HOME|USER)=' | grep -Evi '(TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL|COOKIE)' | head -n 200 >"$OUT/raw/environment_redacted.txt" || true
python3 "$ROOT/scripts/build_login_summary.py" --raw "$OUT/raw" --output "$OUT/summary.json"
echo "LOGIN_PROBE_COMPLETE:$OUT"
