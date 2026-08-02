#!/usr/bin/env bash
#SBATCH --job-name=siestaflow_local_acceptance
#SBATCH --partition=local
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --cpus-per-task=1
#SBATCH --time=00:05:00
#SBATCH --output=.siestaflow-local-slurm/slurm-%j.out
#SBATCH --error=.siestaflow-local-slurm/slurm-%j.err
set -euo pipefail

ROOT="$(cd "${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR required}" && pwd -P)"
RUN_DIR="${SIESTAFLOW_LOCAL_RUN_DIR:?SIESTAFLOW_LOCAL_RUN_DIR required}"
mkdir -p "$RUN_DIR"

srun --exclusive --ntasks=2 --cpus-per-task=1 \
    python3 "$ROOT/integration/local_slurm/workload.py" parent "$RUN_DIR"
srun --exclusive --ntasks=2 --cpus-per-task=1 \
    python3 "$ROOT/integration/local_slurm/workload.py" restart "$RUN_DIR"

printf '%s\n' "LOCAL_SLURM_BATCH_COMPLETED" >"$RUN_DIR/batch.completed"
