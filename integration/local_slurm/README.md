# Local Slurm integration sandbox

This profile exercises real Slurm semantics inside Ubuntu/WSL2 without using
Yoltla. It is deliberately single-node and non-scientific.

It validates:

- `systemd`, MUNGE, `slurmctld`, `slurmd`, `sbatch`, `squeue`, `scontrol`,
  command-level `sacct` behavior, and sequential `srun` steps;
- the allocation environment and rank variables;
- an artifact produced by a parent step and consumed by a restart step;
- deterministic local evidence with the status
  `LOCAL_SLURM_INTEGRATION_PASS`.

It does **not** validate Yoltla scheduling policy, modules, Lustre, Intel MPI,
PSM3, multinode networking, performance, or scientific correctness. Local
evidence always records `scientific_results_allowed=false` and
`yoltla_runtime_verified=false`.

## Bootstrap in WSL2

Run from Windows PowerShell at the repository root:

```powershell
wsl -d Ubuntu -u root --exec bash integration/local_slurm/bootstrap_wsl.sh
```

The bootstrap refuses to overwrite an existing `/etc/slurm/slurm.conf` unless
that file carries the SIESTAFlow sandbox marker. Hardware values are detected
from `slurmd -C`; 90% of detected memory is advertised to preserve operating
system headroom.

## Acceptance

```powershell
wsl -d Ubuntu --exec bash integration/local_slurm/run_acceptance.sh
```

Generated evidence lives below `.siestaflow-local-slurm/`, which is excluded
from Git. The test consists of one allocation and two sequential `srun` steps.

Ubuntu's lightweight local profile uses
`AccountingStorageType=accounting_storage/none`. Therefore `sacct` reports that
historical accounting is disabled; this is recorded as a sandbox limitation,
not treated as Yoltla accounting evidence.

## Controller plus SIESTA acceptance

The PowerShell runner builds a fresh self-contained package, retains an open
`wsl.exe` client for the lifetime of `sbatch --wait`, and runs the two-stage
parent/DM-restart controller with the first MPI-enabled SIESTA found below
`$HOME/.local`:

```powershell
powershell -ExecutionPolicy Bypass -File `
  integration/local_slurm/run_controller_acceptance.ps1
```

The open client is necessary because WSL may stop a distribution that has only
service-owned processes. A real HPC node does not share that lifecycle.
