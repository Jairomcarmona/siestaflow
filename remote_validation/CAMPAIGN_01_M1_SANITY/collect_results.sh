#!/usr/bin/env bash
set -euo pipefail
: "${RESULT_DIR:?RESULT_DIR must be configured}"
tar -czf remote-results.tar.gz "$RESULT_DIR"
echo RESULTS_COLLECTED_FOR_MANUAL_TRANSFER
