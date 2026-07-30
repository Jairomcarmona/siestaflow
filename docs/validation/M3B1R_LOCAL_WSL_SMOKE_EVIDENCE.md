# M3B1R local WSL SIESTA smoke evidence

Date: 2026-07-21

This is local technical evidence only. It does not establish Yoltla runtime,
SLURM, `srun`, scheduler, filesystem, or MPI compatibility and carries no
scientific interpretation.

Environment:

- Ubuntu under WSL2, x86_64
- AMD Ryzen 5 7535HS, 6 physical cores / 12 logical CPUs visible
- SIESTA 5.4.2 serial build
- GNU Fortran 13.3.0
- Compiler flags: `-fallow-argument-mismatch -O3 -march=native`
- OpenBLAS with `OPENBLAS_NUM_THREADS=6`, `OMP_NUM_THREADS=1`
- SIESTA parallelisations reported: `none`

Exact input hashes:

- Geometry: `870d92a224662755c3d10ad9d45c4b212a6b4c23f3966558c05cd929cea5c9fb`
- C.psml: `ce0f6a7fd43e70d44018e94286d934e9caadc005e95da87500d85fbe501d4c41`
- smoke.fdf: `386c83e2f0a9cb3cfb0b0f5de0d02626af9e594bd353c295af1d571f7887aa1e`

Observed result:

- SIESTA process exit status: 0
- Normal marker: `Job completed`
- Normal artifact: `0_NORMAL_EXIT` contains `SIESTA completed successfully`
- SCF: converged after 10 iterations by the DM+H criterion
- Atoms / species parsed: 50 / 1
- stderr: only the normal `Job completed` message
- NaN, MPI, filesystem, FDF, and missing-pseudopotential failure markers: none
- Wall time: 4 minutes 6.07 seconds
- Maximum resident set: 1,341,212 KiB
- Swaps: 0

The first parse of this genuine output exposed that the parser recognized only
synthetic version, atom/species, and SCF spellings. A test reproducing SIESTA
5.4.2 output was added before correcting `SiestaOutputParser`. It now extracts
version 5.4.2, 50 atoms, one species, SCF convergence, 10 iterations, and normal
termination. Genuine non-fatal SIESTA warnings retain the parser-level
`UNKNOWN_WARNING` classification, while the remote termination summary gives
normal converged termination priority when normal and converged markers exist.

The V2 upload ZIP was rebuilt reproducibly with this corrected parser. No SSH,
SLURM, `srun`, `sbatch`, or remote SIESTA action was performed.
