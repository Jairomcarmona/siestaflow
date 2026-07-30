# M3R local runtime demonstration

Classification: `EXECUTED_LOCALLY`, `SYNTHETIC`; remote evidence remains `MISSING`. No real SIESTA, MPI, SLURM, SSH, `sbatch`, `srun`, `mpiexec` or `mpirun` was executed.

The pytest integration sandbox performed the required chain:

1. Generated an M3_STATIC_V2 package from source with synthetic pseudo requirements.
2. Ran `verify_local_package.py`; hashes, direct Python, Bash, SLURM, embedded Python, structure, secrets and paths passed.
3. Executed `run_login_probe.sh` with stubs for module, scheduler, MPI-discovery, hostname, filesystem and quota commands.
4. Parsed one synthetic account/partition/QoS association into `login_probe/summary.json`.
5. Executed `prepare_scheduler_probe.py`; its temporary candidate passed `bash -n` and the embedded validator before atomic publication.
6. Executed the generated SLURM script with synthetic `SLURM_*` variables and command stubs. `scheduler_probe/summary.json` recorded job ID, matching account/partition, signal receipt and `scientific_calculation_performed=false`.
7. Executed `inspect_probe_job.sh` against stubbed empty `squeue` and a main-job `sacct COMPLETED|0:0` row plus a `.batch` row. The exact main row produced terminal evidence.
8. Verified synthetic Mn/O PSML fixtures with synthetic hashes; no audited pseudopotential or scientific hash was modified.
9. Executed `scripts/collect_bundle.py`; the resulting tar.gz contained manifest/hash/checksums and normalized uid/gid/mtime.

Executed test:

```powershell
python -m pytest tests/m3r/test_runtime_correction.py::test_full_local_runtime_demonstration_with_stubs -q
```

Result: `1 passed`. Separate parametrized runtime tests covered RUNNING, COMPLETED, FAILED, no evidence, TIMEOUT, NODE_FAIL, unknown state, every documented terminal state, incomplete bundles, secret/traversal failures and invalid generated candidates.
