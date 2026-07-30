# Recovery and resume

Local campaign state is revisioned under the selected workspace. Re-running `campaign simulate ID` loads completed task state, restores a simulated allocation identity, and does not create second attempts for passed tasks.

Before resuming, run:

```powershell
python -m siestaflow.cli --workspace .work campaign status cutoff_sweep --json
python -m siestaflow.cli --workspace .work campaign simulate cutoff_sweep --dry-run --json
```

Do not edit `state.json`. A review/fail decision stops the worker. An existing import/package destination is never overwritten; select a clean destination and preserve the original evidence.

For a real controller package:

```bash
./progress.sh
sbatch submit.slurm
```

Resubmit only after the previous job is terminal. The new allocation verifies
the checksum-wrapped state, completed result manifests, parent artifacts and
transferred inputs. Completed valid tasks are skipped. A tampered result is
demoted and rerun only when its configured attempt budget permits it.

For a package produced by `run prepare`, inspect it locally or on the cluster
without submitting:

```bash
siestaflow run inspect RUN_PACKAGE --json
siestaflow run status RUN_PACKAGE --json
siestaflow run resume RUN_PACKAGE
siestaflow run resume RUN_PACKAGE --previous-job-terminal
```

The last command emits one of `INITIAL_SUBMISSION_REQUIRED`,
`RESUBMISSION_REQUIRED`, `NO_RESUBMISSION_REQUIRED`,
`PREVIOUS_JOB_TERMINAL_CONFIRMATION_REQUIRED`, or
`BLOCKED_REVIEW_REQUIRED`. Even when it prints `sbatch submit.slurm`, it does
not execute that command. Before a resubmission, the researcher must
independently confirm in Slurm that the previous job is terminal and pass
`--previous-job-terminal`.
