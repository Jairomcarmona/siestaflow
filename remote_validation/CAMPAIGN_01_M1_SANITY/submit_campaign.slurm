#!/usr/bin/env bash
# SIESTAFLOW M2 SLURM RENDER
# render_status: PREVIEW_WITH_UNVERIFIED_PROFILE
# profile: YOLTLA_UNVERIFIED_FOR_SIESTA
#SBATCH --job-name=CAMPAIGN_01_M1_SANITY
# REQUIRED_CONFIGURATION: partition=null
# REQUIRED_CONFIGURATION: account=null
# REQUIRED_CONFIGURATION: qos=null
# REQUIRED_CONFIGURATION: nodes=null
# REQUIRED_CONFIGURATION: ntasks=null
# REQUIRED_CONFIGURATION: cpus-per-task=null
# REQUIRED_CONFIGURATION: mem=null
# REQUIRED_CONFIGURATION: time=null
# REQUIRED_CONFIGURATION: signal=null
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

set -euo pipefail

# REQUIRED_CONFIGURATION: module_commands=[]
# launcher_command: null
# worker_command: siestaflow campaign worker CAMPAIGN_01_M1_SANITY
echo REMOTE_PREFLIGHT_REQUIRES_CONFIGURATION >&2
exit 2
