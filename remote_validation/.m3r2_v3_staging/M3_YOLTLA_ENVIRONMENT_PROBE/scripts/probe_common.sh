#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
safe_head() { head -n "${2:-200}" "$1"; }
run_optional() {
  local out="$1"; shift
  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout "${PROBE_COMMAND_TIMEOUT_SECONDS:-20}" "$@" >"$out" 2>&1
  else
    "$@" >"$out" 2>&1
  fi
  local code=$?
  set -e
  printf '%s
' "$code" >"${out}.exit_code"
  return 0
}
refuse_existing() { [[ ! -e "$1" ]] || { echo "REFUSING_OVERWRITE:$1" >&2; exit 2; }; }
