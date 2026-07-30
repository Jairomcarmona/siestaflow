#!/usr/bin/env bash
set -euo pipefail
missing=0
for command in bash squeue sacct sbatch sha256sum df; do
  command -v "$command" >/dev/null 2>&1 || { echo "MISSING_COMMAND:$command" >&2; missing=1; }
done
: "${SIESTA_EXECUTABLE:=}"
: "${MPI_LAUNCHER:=}"
: "${PSEUDO_DIR:=}"
for variable in SIESTA_EXECUTABLE MPI_LAUNCHER PSEUDO_DIR; do
  [[ -n "${!variable}" ]] || { echo "MISSING_CONFIGURATION:$variable" >&2; missing=1; }
done
[[ -x "$SIESTA_EXECUTABLE" ]] || missing=1
[[ -d "$PSEUDO_DIR" ]] || missing=1
[[ -r validation_manifest.json ]] || missing=1
[[ -w . ]] || missing=1
df -Pk . >/dev/null
if [[ -n "$MPI_LAUNCHER" ]]; then
  command -v "${MPI_LAUNCHER%% *}" >/dev/null 2>&1 || missing=1
fi
if [[ -x "$SIESTA_EXECUTABLE" ]]; then
  "$SIESTA_EXECUTABLE" --version >/dev/null 2>&1 || missing=1
fi
if [[ -d "$PSEUDO_DIR" ]]; then
  echo "0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6  $PSEUDO_DIR/Mn.psml" | sha256sum -c - || missing=1
  echo "224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e  $PSEUDO_DIR/O.psml" | sha256sum -c - || missing=1
fi
sha256sum -c checksums.sha256 >/dev/null || missing=1
echo "VERSION_MPI_PSEUDO_HASH_AND_PATH_CHECKS_REQUIRE_CLUSTER_CONFIGURATION" >&2
echo REMOTE_PREFLIGHT_REQUIRES_CONFIGURATION >&2
exit 2
