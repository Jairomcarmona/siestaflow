#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
cd "$ROOT"
: # no module commands configured
export PYTHONDONTWRITEBYTECODE=1
python3 verify_package.py
command -v python3 >/dev/null
command -v srun >/dev/null
command -v siesta >/dev/null
siesta --version >/dev/null 2>&1
echo M4_REMOTE_PREFLIGHT_PASS
