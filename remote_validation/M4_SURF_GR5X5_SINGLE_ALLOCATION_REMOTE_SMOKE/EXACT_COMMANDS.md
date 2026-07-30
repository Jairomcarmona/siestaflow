# Exact commands

## Package locally

```bash
python -m siestaflow.cli remote m4-package --profile config/remote_smokes/m4_surf_gr5x5_yoltla.yaml --output remote_validation --json
```

## Transfer manually

```bash
scp remote_validation/M4_SURF_GR5X5_SINGLE_ALLOCATION_REMOTE_SMOKE.zip USER@YOLTLA_HOST:~/
```

## Verify on Yoltla

```bash
unzip M4_SURF_GR5X5_SINGLE_ALLOCATION_REMOTE_SMOKE.zip
cd M4_SURF_GR5X5_SINGLE_ALLOCATION_REMOTE_SMOKE
python3 verify_package.py
chmod u+x scripts/*.sh scripts/*.py
./scripts/preflight.sh
```

## Submit and inspect

```bash
JOB_ID=$(sbatch --parsable campaign.slurm)
echo "$JOB_ID"
squeue -j "$JOB_ID"
./scripts/inspect_job.sh "$JOB_ID"
```

## Resume in a new allocation

Only after the previous job is terminal:

```bash
NEW_JOB_ID=$(sbatch --parsable campaign.slurm)
echo "$NEW_JOB_ID"
squeue -j "$NEW_JOB_ID"
./scripts/inspect_job.sh "$NEW_JOB_ID"
```

Do not delete `state/`, `work/`, `evidence/`, or `results/` between submissions.
