#!/usr/bin/env bash
# Yoltla M1 MnO2: numerical, basis and U/spin tests only.
# Every SIESTA step consumes the complete 2-node/128-task allocation.
#SBATCH --partition=qz2d-128p
#SBATCH --account=vini
#SBATCH --qos=normal
#SBATCH --job-name=M1_MnO2_AutoConv
#SBATCH --time=2-00:00:00
#SBATCH --nodes=2
#SBATCH --ntasks=128
#SBATCH --ntasks-per-node=64
#SBATCH --cpus-per-task=1
#SBATCH --signal=B:USR1@1800
#SBATCH --output=OUT.%x.%j
#SBATCH --error=ERROR.%x.%j

set -euo pipefail

module purge
module load siesta/5.4.2
module load python/3.12

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1

PACKAGE_ROOT="$(cd "${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR is required}" && pwd -P)"
cd "$PACKAGE_ROOT"

python3 --version
python3 verify_package.py
python3 scripts/automatic_campaign.py --validate-only
exec python3 scripts/automatic_campaign.py \
  --run-root "$PACKAGE_ROOT/runs/autoconvergence"
