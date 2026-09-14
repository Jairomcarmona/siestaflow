# Local Slurm WSL acceptance evidence

Date: 2026-07-30

Status: `LOCAL_SLURM_INTEGRATION_PASS`

This evidence is technical and local. It is not Yoltla acceptance and has no
scientific interpretation.

## Environment

- Ubuntu 24.04.1 LTS on WSL2 kernel
  `6.6.114.1-microsoft-standard-WSL2`
- `systemd` active; cgroup v2
- Slurm 23.11.4, single node, partition `local`
- MUNGE 0.5.15
- OpenMPI 4.1.6
- Python 3.12.3
- SIESTA 5.4.2, GNU 13.3.0, MPI enabled
- 12 logical CPUs and 6,837 MiB advertised to Slurm
- `/etc/slurm/slurm.conf` SHA-256:
  `9f90992727a24c0d4dd62d63a34371e487cbd89741fab34f65084595262d92a7`

The Slurm profile is generated from `slurmd -C`, advertises 90% of detected
memory, and refuses to replace an unmanaged configuration.

## Executed evidence

### Scheduler and step acceptance

Job 1 completed one real allocation with two sequential `srun` steps. Each
step materialized two rank records. The restart step consumed the exact
artifact created by the parent.

- status: `LOCAL_SLURM_INTEGRATION_PASS`
- job state: `COMPLETED`
- exit code: `0:0`
- artifact SHA-256:
  `de4c738e19fd1aa3ee6f4f70eef83b2c91e3ba3fcff406c111763490ff75deb7`

### Controller and SIESTA acceptance

The self-contained controller package used a real `srun --mpi=pmix` launcher,
two MPI processes, two dependent tasks, and a parent density-matrix transfer.

An initial package (job 5) failed closed before SIESTA started because a POSIX
absolute executable path had been serialized by Windows `Path` semantics as
`\home\...`. The builder now represents remote executable paths as strings,
and a regression test rejects backslashes.

A later run was interrupted when WSL stopped the distribution without a live
`wsl.exe` client. Job 7 was cancelled after its process was confirmed absent.
On job 8 the controller:

1. detected the new allocation;
2. reclassified the stale running attempt as `INTERRUPTED`;
3. executed parent attempt 2;
4. verified the parent result and `.DM`;
5. transferred the `.DM` with immutable pre-execution evidence;
6. launched the restart;
7. observed `Attempting to read DM from file... Succeeded...`;
8. completed both tasks.

Final job 8:

- Slurm state: `COMPLETED`
- Slurm exit code: `0:0`
- elapsed allocation time: 5 minutes 39 seconds
- parent SCF: converged in 10 iterations
- restart SCF: converged in 3 iterations
- controller status: `COMPLETED`, 2/2 tasks
- login-node persistent process required by package: `false`
- campaign SHA-256:
  `d627b3a9661841e5608e149441ef359705e83af2dc39d0ec65fce54b656741d2`
- parent result-manifest SHA-256:
  `46ab8ca8be6ce89dd97ee430acc8173c2cb69c9fb666a14cf714ea584c45b091`
- restart result-manifest SHA-256:
  `c6357098e1b4ca510bb30adb7bc5f6f525924e12c2ad8ef8bb24ae00af6fd487`

## WSL lifecycle rule

For a local controller acceptance, the Windows `wsl.exe` invocation must
remain open for the lifetime of `sbatch --wait`. The supplied PowerShell runner
does this synchronously and exits when the allocation ends. It leaves no
background monitor.

This rule belongs only to the WSL test harness. It is not added to generated
HPC packages.

## Boundaries

This sandbox does not validate:

- Yoltla partitions, QOS, fair-share, reservations, or backfill policy;
- Lustre, ACLs, quotas, or remote module availability;
- Intel MPI/Hydra, PSM3, or multinode networking;
- cluster performance or scaling;
- scientific validity of the smoke input.

The local profile uses `AccountingStorageType=accounting_storage/none`.
`jobcomp/filetxt` preserves completion records, but `sacct` historical
accounting is intentionally unavailable. Yoltla accounting still requires
remote evidence.
