#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUN_ROOT="$PACKAGE_ROOT/runs/autoconvergence"

if [[ -f "$RUN_ROOT/final_summary.json" ]]; then
  python3 -m json.tool "$RUN_ROOT/final_summary.json"
elif [[ -f "$RUN_ROOT/failure.json" ]]; then
  python3 -m json.tool "$RUN_ROOT/failure.json"
elif [[ -f "$RUN_ROOT/interrupted.json" ]]; then
  python3 -m json.tool "$RUN_ROOT/interrupted.json"
else
  printf '%s\n' "No final campaign state yet."
fi

if [[ -f "$RUN_ROOT/traceability.csv" ]]; then
  printf '\n%s\n' "Traceability:"
  column -s, -t <"$RUN_ROOT/traceability.csv" 2>/dev/null \
    || sed -n '1,200p' "$RUN_ROOT/traceability.csv"
fi
