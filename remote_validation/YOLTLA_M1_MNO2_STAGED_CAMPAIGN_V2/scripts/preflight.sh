#!/usr/bin/env bash
# Login-node validation and sbatch --test-only only. Runtime preflight runs in submit.slurm.
set -euo pipefail
: "${1:?usage: preflight.sh PHASE_OR_BUNDLE PROFILE_JSON}"
: "${2:?usage: preflight.sh PHASE_OR_BUNDLE PROFILE_JSON}"
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
IDENTIFIER=$1
PROFILE=$2
cd "$ROOT"
[[ -f "generated/$IDENTIFIER/login_preflight.sh" ]] || {
  echo "PREPARED_LOGIN_PREFLIGHT_MISSING:generated/$IDENTIFIER/login_preflight.sh" >&2
  exit 2
}
bash "generated/$IDENTIFIER/login_preflight.sh"
