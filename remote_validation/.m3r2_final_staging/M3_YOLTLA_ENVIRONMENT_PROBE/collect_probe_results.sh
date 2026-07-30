#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
[[ $# -eq 2 && "$1" == '--pseudo-root' ]] || { echo 'usage: collect_probe_results.sh --pseudo-root ABSOLUTE_PATH' >&2; exit 2; }
[[ "$2" = /* && "$2" != *'/../'* && "$2" != */.. && "$2" != *'/./'* ]] || { echo PSEUDO_ROOT_MUST_BE_SAFE_ABSOLUTE_PATH >&2; exit 2; }
python3 "$ROOT/scripts/verify_pseudos.py" --root "$2" --output "$ROOT/evidence/pseudo_verification/summary.json"
python3 "$ROOT/scripts/collect_bundle.py" --package-root "$ROOT"
