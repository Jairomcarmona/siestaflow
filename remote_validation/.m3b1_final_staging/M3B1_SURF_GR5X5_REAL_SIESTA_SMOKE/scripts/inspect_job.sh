#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || { echo 'usage: inspect_job.sh JOB_ID' >&2; exit 2; }
OUT="$ROOT/evidence/accounting"; mkdir -p "$OUT"
squeue -h -j "$1" -o '%i|%T|%P|%a|%q|%M|%N' >"$OUT/squeue.txt" 2>"$OUT/squeue.err" || true
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,NodeList,Partition,Account,QOS >"$OUT/sacct.txt" 2>"$OUT/sacct.err" || true
echo "ACCOUNTING_CAPTURED:$OUT"
