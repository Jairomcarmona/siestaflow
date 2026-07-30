#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$ROOT/site/evidence/$STAMP"
mkdir -p "$DEST"
date -u +%Y-%m-%dT%H:%M:%SZ > "$DEST/observed_at.txt"
hostname -f > "$DEST/hostname.txt"
sinfo -o '%P|%a|%l|%D|%c|%m' > "$DEST/sinfo.txt"
scontrol show partition -o > "$DEST/scontrol_partitions.txt"
sacctmgr -n -P show assoc user="$USER" format=Cluster,Account,Partition,QOS,DefaultQOS > "$DEST/sacctmgr_assoc.txt"
command -v srun > "$DEST/command_srun.txt"
command -v sbatch > "$DEST/command_sbatch.txt"
command -v siesta > "$DEST/command_siesta.txt"
siesta --version > "$DEST/siesta_version.txt" 2>&1
echo "$DEST"
echo SITE_EVIDENCE_CAPTURED_NO_JOB_SUBMITTED

