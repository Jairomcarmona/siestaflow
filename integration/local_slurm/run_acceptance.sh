#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
EVIDENCE_ROOT="$ROOT/.siestaflow-local-slurm"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_DIR="$EVIDENCE_ROOT/$RUN_ID"
mkdir -p "$RUN_DIR"

if ! sinfo -h -p local -o '%T' | grep -Eq '^(idle|mix|alloc)$'; then
    echo "LOCAL_SLURM_PARTITION_NOT_READY" >&2
    exit 2
fi

job_id="$(
    sbatch --parsable --wait \
        --chdir="$ROOT" \
        --export=ALL,SIESTAFLOW_LOCAL_RUN_DIR="$RUN_DIR" \
        "$ROOT/integration/local_slurm/submit_acceptance.slurm"
)"
job_id="${job_id%%;*}"
printf '%s\n' "$job_id" >"$RUN_DIR/job_id.txt"

scontrol show job "$job_id" >"$RUN_DIR/scontrol_job.txt" 2>&1 || true
sacct -X -n -P -j "$job_id" \
    -o JobID,State,ExitCode,Elapsed,AllocCPUS,NodeList,Partition \
    >"$RUN_DIR/sacct.txt" 2>&1 || true
sinfo -p local -N -l >"$RUN_DIR/sinfo.txt"

python3 "$ROOT/integration/local_slurm/verify_acceptance.py" \
    "$RUN_DIR" --job-id "$job_id"
echo "EVIDENCE_DIR=$RUN_DIR"
