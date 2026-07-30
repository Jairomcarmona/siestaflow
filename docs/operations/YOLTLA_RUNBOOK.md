# Yoltla runbook — M3 probe V3

## Current validated operating contract (2026-07-29)

SIESTA is loaded with `module load siesta/5.4.2`. Yoltla explicitly recommends
`mpiexec.hydra -bootstrap ssh`; SIESTAFLOW schema 2.0 implements that launcher
with explicit host placement and a unique `FI_PSM3_UUID` per step.

The user remains responsible for transfer and submission:

```bash
unzip PACKAGE.zip
cd PACKAGE
module purge
module load python/3.12
python3 verify_package.py
bash -n submit.slurm
sbatch --test-only submit.slurm
sbatch submit.slurm
./progress.sh
```

Never submit two copies that write to the same package root simultaneously.
Resubmit only after the prior job is terminal. Empty `squeue` output is not
proof of success; inspect `sacct` and the package state.

The evidence-strength catalog is
`config/cluster_profiles/yoltla_runtime_catalog_20260729.json`. A profile
accepted by `sbatch --test-only` is not automatically classified as a
completed SIESTA runtime validation.

## Historical M3 probe V3

Status: `REAL_REMOTE_SCHEDULER_PROBE_PENDING`. V3 supersedes V2 and earlier revisions. Do not mix package revisions or manually copy evidence between them.

1. Wait for human approval of M3R2; do not execute V3 during this milestone.
2. When authorized, use a clean directory, transfer only `M3_YOLTLA_ENVIRONMENT_PROBE_V3_UPLOAD.zip`, and extract its complete root folder.
3. Run `python3 verify_local_package.py`. Require:

```text
M3_PACKAGE_HASHES_VERIFIED
M3_PACKAGE_RUNTIME_SYNTAX_VERIFIED
M3_PACKAGE_STRUCTURE_VERIFIED
```

4. Follow `EXACT_COMMANDS.md` exactly. Stop at `DETENERSE PARA INSPECCIÓN HUMANA`.
5. Only after human inspection, perform the documented manual `sbatch`. Codex does not transfer, connect or submit.
6. Repeat `./inspect_probe_job.sh "$JOB_ID"` after the job leaves `squeue` until the exact main `sacct` row supplies terminal State and ExitCode. Empty `squeue` is not success.
7. Collect using the audited external pseudo root and manually return the resulting tar.gz through the approved channel.

V3 ZIP SHA-256: `04f0f8713304958d3836eb3e656e2f2864055e996a438273e0ed2c92bd8953af`. This hash proves the local upload artifact, not remote execution.
# M3 package V3 scheduler resolution

Use a clean V3 extraction and run `run_login_probe.sh` again (preferred). The login summary now retains account-wide associations and records visible partitions and policies. `prepare_scheduler_probe.py` automatically proceeds only for one compatible default partition; otherwise it stops with a diagnostic. Optional `--account`, `--partition`, and `--qos` values must exactly match an evidence-derived candidate. Inspect both the generated SLURM file and `generated/scheduler_selection.json`. Do not submit during M3R2 review.

## M3B1 real SIESTA technical smoke

The original upload ZIP is superseded by M3B1R. Upload only
`M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE_V2_UPLOAD.zip` into a clean directory.
Run `python3 verify_package.py`, then `scripts/run_login_discovery.sh`, and
review `evidence/login_discovery/runtime_candidates.json`. Only then run
`prepare_smoke_job.py`; review `generated/runtime_selection.json` and the
generated SLURM file. Stop there: M3B1R does not authorize `sbatch`. The ZIP
hash recorded below after reproducible generation proves only the local
artifact, not remote execution.

M3B1 V2 ZIP SHA-256: `f031fa2c3201ced34d2da7c95a1188e687a27a9c9ae29fb8d85300b511027921`.
