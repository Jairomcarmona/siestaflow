#!/usr/bin/env bash
set -euo pipefail
: "${JOB_ID:?JOB_ID must be configured}"
squeue -j "$JOB_ID"
sacct -j "$JOB_ID" --format=JobID,State,ExitCode,Elapsed
