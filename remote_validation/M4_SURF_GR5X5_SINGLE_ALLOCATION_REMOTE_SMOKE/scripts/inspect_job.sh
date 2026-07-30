#!/usr/bin/env bash
set -euo pipefail
: "${1:?usage: inspect_job.sh JOB_ID}"
squeue -j "$1" || true
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,MaxRSS,NodeList,Partition,Account,QOS
