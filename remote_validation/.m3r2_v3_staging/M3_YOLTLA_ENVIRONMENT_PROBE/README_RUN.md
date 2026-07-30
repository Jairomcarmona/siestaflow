# M3 Yoltla environment probe — package revision V3

This is a non-scientific, human-operated environment characterization package.
It contains no FDF, geometry, pseudopotential, credential, or production command.
V3 supersedes V2 by supporting account-wide associations and evidence-bound
default-partition resolution. Use a clean V3 directory and never mix files
between revisions. Follow `EXACT_COMMANDS.md` exactly. Nothing transfers files
or submits a job automatically. The placeholder SLURM file exits until the V3
preparer creates and syntax-validates an evidence-backed script under `generated/`.
