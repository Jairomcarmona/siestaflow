# M10 manual Yoltla runbook

**USER MANUAL SBATCH ONLY.** Do not add SSH automation, credentials or a
background agent. No M10 submission may start before current scheduler
discovery has been reviewed by a human.

## Discovery and resolved rendering

```bash
# On the Yoltla login node, run the existing M3 environment probe first.
# It records sinfo, scontrol and sacctmgr evidence and produces review inputs.
# Human review must approve scheduler_selection.json for nodes=2, ntasks=64,
# cpus_per_task=1 and an observed scheduler-specific memory value.
```

Render the resolved bundle locally with that exact reviewed file, then transfer
and extract it to the shared submission directory. Historical `tt2d-64p`,
`vini` and `normal` are never submission defaults.

```bash
cd /path/to/qraft-m10-yoltla-bundle
cat bundle_manifest.json backend_equivalence.json
sed -n '1,220p' preflight/submit_m10_preflight.slurm
sbatch --test-only preflight/submit_m10_preflight.slurm
sbatch preflight/submit_m10_preflight.slurm
# Wait until terminal; inspect sacct and then evidence/preflight.<job-id>.txt.

cd packages/hydra/QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE
python3 verify_package.py
sed -n '1,220p' submit.slurm
sbatch --test-only submit.slurm
sbatch submit.slurm
# Wait for terminal sacct evidence before inspecting progress.
./progress.sh

cd ../../srun/QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE
python3 verify_package.py
sbatch --test-only submit.slurm
sbatch submit.slurm
# Wait for terminal sacct evidence before inspecting progress.
./progress.sh

cd ../../continuation/QRAFT_M10_ALLOCATION_CONTINUATION_TECHNICAL
python3 verify_package.py
```

## CONTINUATION JOB #1

Run `sbatch --time=00:01:00 submit.slurm` from the continuation package root.
First run `sbatch --test-only submit.slurm`; it is scheduler validation only,
not a gate pass. Capture `JOB1`, wait until it leaves `squeue`, and confirm its
terminal state using `sacct`. Then inspect QRAFT state/evidence and confirm:
runtime `INTERRUPTED`, `STAGE_A` `COMPLETED`, and no `STAGE_B` attempt. The
canonical worker exits `2` for `INTERRUPTED`, so Slurm may report this controlled
Job #1 as failed/nonzero. QRAFT persisted state plus Job #2 reuse is authority.

**HUMAN GATE:** do not submit Job #2 until every Job #1 condition above has
been inspected. Do not copy the package, delete `state/`, or alter campaign
configuration/ExecutionSpec.

## CONTINUATION JOB #2

From **exactly the same package/root**, run `sbatch --time=00:03:00 submit.slurm`.
Capture `JOB2`, assert `JOB2 != JOB1`, wait for terminal `sacct` evidence, then
confirm `STAGE_A` `REUSED` with `attempt-0001` preserved, `STAGE_B` completed,
final runtime `COMPLETED`, and `allocation_history` contains both job IDs.

Collect `results/campaign_summary.json`, `state/`, `evidence/`, job stdout and
stderr after each submission.
