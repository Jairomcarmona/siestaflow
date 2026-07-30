#!/usr/bin/env bash
#SBATCH --signal=B:USR1@60
set -euo pipefail
echo SCHEDULER_PROBE_NOT_PREPARED_USE_PREPARE_SCHEDULER_PROBE_PY >&2
exit 2
