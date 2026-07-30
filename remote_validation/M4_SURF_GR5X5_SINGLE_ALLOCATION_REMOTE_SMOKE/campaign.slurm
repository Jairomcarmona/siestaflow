#!/usr/bin/env bash
#SBATCH --job-name=M4_SURF_GR5X5_SMOKE
#SBATCH --partition=q1h-20p
#SBATCH --account=vini
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --signal=B:USR1@60
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err
set -euo pipefail
[[ -n "${SLURM_SUBMIT_DIR:-}" ]] || { echo SLURM_SUBMIT_DIR_NOT_SET >&2; exit 2; }
ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
[[ -f "$ROOT/manifest.json" ]] || { echo INVALID_PACKAGE_ROOT >&2; exit 2; }
cd "$ROOT"
: # no module commands configured
export PYTHONPATH="$ROOT/runtime"
export PYTHONDONTWRITEBYTECODE=1
python3 "$ROOT/verify_package.py"
# The controller runs directly in this batch allocation. Only SIESTA uses srun.
exec python3 "$ROOT/scripts/run_worker.py" "$ROOT/campaign.yaml" "$ROOT"
