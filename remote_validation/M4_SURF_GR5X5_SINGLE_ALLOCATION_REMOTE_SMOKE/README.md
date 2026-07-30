# M4_SURF_GR5X5_SINGLE_ALLOCATION_REMOTE_SMOKE

Self-contained technical acceptance package for `SURF_Gr5x5_clean_v01`. One `sbatch`
runs the Python controller directly in its allocation; every SIESTA calculation
is a bounded `srun --exclusive` job step. State under `state/`, attempts under
`work/`, and summaries under `results/` survive a later `sbatch` with a new job
ID. No scientific interpretation is allowed.

The package profile is external data, not a core default. Run the preflight on
Yoltla before submission. A failed preflight must not be bypassed.
