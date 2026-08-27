#!/usr/bin/env bash
# Capture selected module runtime candidates without launching work or altering the caller shell.
(
set -euo pipefail

usage() {
  printf '%s\n' 'usage: m10_yoltla_runtime_candidate_probe.sh --raw <raw-evidence-dir> --python-module <module> --siesta-module <module> [--output <probe-evidence-dir>]' >&2
  exit 2
}

raw=''
python_module=''
siesta_module=''
output=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --raw) raw=${2-}; shift 2 ;;
    --python-module) python_module=${2-}; shift 2 ;;
    --siesta-module) siesta_module=${2-}; shift 2 ;;
    --output) output=${2-}; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$raw" && -n "$python_module" && -n "$siesta_module" ]] || usage
[[ -d "$raw" ]] || { printf 'M10_RUNTIME_PROFILE_UNRESOLVED: raw evidence directory missing\n' >&2; exit 1; }
[[ -f "$raw/module_python_candidates.txt" && -f "$raw/module_siesta_candidates.txt" ]] || { printf 'M10_RUNTIME_PROFILE_UNRESOLVED: module availability evidence missing\n' >&2; exit 1; }
[[ "$(grep -Fxc -- "$python_module" "$raw/module_python_candidates.txt" || true)" == '1' ]] || { printf 'M10_RUNTIME_PROFILE_UNRESOLVED: requested Python module is not exactly observed in raw evidence\n' >&2; exit 1; }
[[ "$(grep -Fxc -- "$siesta_module" "$raw/module_siesta_candidates.txt" || true)" == '1' ]] || { printf 'M10_RUNTIME_PROFILE_UNRESOLVED: requested SIESTA module is not exactly observed in raw evidence\n' >&2; exit 1; }
if [[ -z "$output" ]]; then
  output="$(cd "$raw/.." && pwd -P)/runtime_candidate_probe"
fi

(
  [[ ! -e "$output" && ! -L "$output" ]] || { printf 'M10_RUNTIME_PROFILE_UNRESOLVED: refusing to overwrite runtime probe evidence: %s\n' "$output" >&2; exit 1; }
  mkdir -p "$output"
  printf '%s\n' 'module purge' "module load $python_module" "module load $siesta_module" > "$output/module_setup_commands.txt"
  printf '%s\n' "$python_module" > "$output/selected_python_module.txt"
  printf '%s\n' "$siesta_module" > "$output/selected_siesta_module.txt"
  if ! type module > "$output/module_mechanism.txt" 2>&1; then
    printf '%s\n' '127' > "$output/module_mechanism.exit_code"
    printf '%s\n' 'M10_RUNTIME_CANDIDATE_PROBE_FAILED: module mechanism unavailable' >&2
    exit 1
  fi
  printf '%s\n' '0' > "$output/module_mechanism.exit_code"
  set +e
  module purge > "$output/module_purge.txt" 2>&1
  purge_status=$?
  module load "$python_module" > "$output/module_load_python.txt" 2>&1
  python_status=$?
  if [[ "$python_status" -eq 0 ]]; then
    module load "$siesta_module" > "$output/module_load_siesta.txt" 2>&1
    siesta_status=$?
  else
    printf '%s\n' 'skipped because Python module load failed' > "$output/module_load_siesta.txt"
    siesta_status=125
  fi
  set -e
  printf '%s\n' "$purge_status" > "$output/module_purge.exit_code"
  printf '%s\n' "$python_status" > "$output/module_load_python.exit_code"
  printf '%s\n' "$siesta_status" > "$output/module_load_siesta.exit_code"
  module -t list > "$output/module_list.txt" 2>&1 || true
  if [[ "$purge_status" -ne 0 || "$python_status" -ne 0 || "$siesta_status" -ne 0 ]]; then
    printf '%s\n' 'M10_RUNTIME_CANDIDATE_PROBE_FAILED: module setup failure' >&2
    exit 1
  fi
  record_command() {
    local name=$1
    command -v "$name" > "$output/command_${name//./_}.txt" 2>/dev/null || :
  }
  record_query() {
    local name=$1 file=$2
    "$name" --version > "$output/$file" 2>&1 || true
  }
  for command_name in python python3 siesta srun mpirun mpiexec mpiexec.hydra; do
    record_command "$command_name"
  done
  record_query python python_version.txt
  record_query python3 python3_version.txt
  record_query siesta siesta_version.txt
  record_query srun srun_version.txt
  record_query mpirun mpirun_version.txt
  record_query mpiexec mpiexec_version.txt
  if [[ -s "$output/command_mpiexec_hydra.txt" ]]; then
    mpiexec.hydra -help > "$output/mpiexec_hydra_help.txt" 2>&1 || true
  fi
  env | LC_ALL=C grep -E '^(I_MPI|FI_|PATH=|MODULE|LMOD)' > "$output/environment_redacted.txt" || true
  printf 'RUNTIME_CANDIDATE_PROBE_COMPLETE:%s\n' "$output"
)
)
