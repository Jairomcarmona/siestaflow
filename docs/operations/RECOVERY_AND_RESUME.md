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
