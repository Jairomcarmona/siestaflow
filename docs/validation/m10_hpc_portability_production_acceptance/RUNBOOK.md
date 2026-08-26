# M10 manual Yoltla runbook

**USER MANUAL SBATCH ONLY.** Do not add SSH automation, credentials or a
background agent. Copy/extract the generated bundle to the shared submission
directory before these commands.

```bash
cd /path/to/qraft-m10-yoltla-bundle
cat bundle_manifest.json backend_equivalence.json
sed -n '1,220p' preflight/submit_m10_preflight.slurm
sbatch preflight/submit_m10_preflight.slurm
cat evidence/preflight.<job-id>.txt

cd packages/hydra/QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE
python3 verify_package.py
sed -n '1,220p' submit.slurm
sbatch submit.slurm
./progress.sh

cd ../../srun/QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE
python3 verify_package.py
sbatch submit.slurm
./progress.sh

cd ../../continuation/QRAFT_M10_ALLOCATION_CONTINUATION_TECHNICAL
python3 verify_package.py
sbatch --time=00:01:00 submit.slurm
./progress.sh
sbatch --time=00:03:00 submit.slurm
./progress.sh
```

## Continuation job #1

Run `sbatch --time=00:01:00 submit.slurm` from the continuation package root.
Expected: final runtime status `INTERRUPTED`, `STAGE_A` `COMPLETED`, and no
`STAGE_B` attempt launched. Do not copy the package, delete `state/`, or alter
`campaign.yaml`.

## Continuation job #2

From **exactly the same package/root**, run `sbatch --time=00:03:00 submit.slurm`.
Expected: a different `SLURM_JOB_ID`; `STAGE_A` `REUSED` with `attempt-0001`
preserved; `STAGE_B` executes; and final runtime status `COMPLETED`.
`allocation_history` must contain both job IDs.

Collect `results/campaign_summary.json`, `state/`, `evidence/`, job stdout and
stderr after each submission.
