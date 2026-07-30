#!/usr/bin/env bash
set -euo pipefail
: "${1:?usage: preflight.sh PHASE_ID PROFILE_JSON}"
: "${2:?usage: preflight.sh PHASE_ID PROFILE_JSON}"
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
PHASE_ID=$1
PROFILE=$2
cd "$ROOT"
python3 verify_package.py
python3 scripts/campaignctl.py verify --with-external
command -v python3 >/dev/null
command -v srun >/dev/null
command -v sbatch >/dev/null
command -v scontrol >/dev/null
command -v siesta >/dev/null
siesta --version
python3 scripts/campaignctl.py check-run \
  --phase "$PHASE_ID" \
  --profile "$PROFILE" \
  --prepared-root "generated/$PHASE_ID"
bash -n "generated/$PHASE_ID/submit.slurm"
sbatch --test-only "generated/$PHASE_ID/submit.slurm"
echo YOLTLA_M1_PREFLIGHT_PASS

