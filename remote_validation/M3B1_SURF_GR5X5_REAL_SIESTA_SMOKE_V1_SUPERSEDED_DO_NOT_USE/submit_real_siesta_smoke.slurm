#!/usr/bin/env bash
# SIESTAFLOW M2 SLURM RENDER
# render_status: EXECUTABLE_AFTER_PROFILE_VERIFICATION
# profile: yoltla-m3b1-observed-profile
#SBATCH --job-name=SURF_Gr5x5_clean_v01
#SBATCH --partition=q1h-20p
#SBATCH --account=vini
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
# OPTIONAL_CONFIGURATION: mem=null
#SBATCH --time=00:02:00
#SBATCH --signal=B:USR1@60
#SBATCH --output=evidence/slurm-%j.out
#SBATCH --error=evidence/slurm-%j.err

set -euo pipefail

[[ -n "${SLURM_SUBMIT_DIR:-}" ]] || {
  echo "SLURM_SUBMIT_DIR_NOT_SET" >&2
  exit 2
}
[[ -d "$SLURM_SUBMIT_DIR" ]] || {
  echo "INVALID_SLURM_SUBMIT_DIR:$SLURM_SUBMIT_DIR" >&2
  exit 2
}
ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
export ROOT
[[ -f "$ROOT/package_manifest.json" ]] || {
  echo "INVALID_SLURM_SUBMIT_DIR:$ROOT" >&2
  exit 2
}
mkdir -p "$ROOT/evidence" "$ROOT/results" "$ROOT/work"
cd "$ROOT"
# SIESTAFLOW_PACKAGE_ROOT_END

# module_commands: none declared
bash scripts/run_siesta_smoke.sh
