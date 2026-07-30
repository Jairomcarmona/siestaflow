# M3B1R local MPI smoke evidence

## Scope and immutable inputs

The real `SURF_Gr5x5_clean_v01` single-point smoke was rerun locally as one new
serial control and two MPI runs. The approved inputs remained byte-identical
before and after all executions:

| Input | SHA-256 |
|---|---|
| `geometry/SURF_Gr5x5_clean_v01.xyz` | `870d92a224662755c3d10ad9d45c4b212a6b4c23f3966558c05cd929cea5c9fb` |
| `pseudos/C.psml` | `ce0f6a7fd43e70d44018e94286d934e9caadc005e95da87500d85fbe501d4c41` |
| `input/smoke.fdf` | `386c83e2f0a9cb3cfb0b0f5de0d02626af9e594bd353c295af1d571f7887aa1e` |

No mesh, k-grid, basis, XC, `MD.Steps`, coordinate, cell, or pseudopotential
content was changed.

## Isolated execution

Evidence root:

```text
/home/jmc/siestaflow-local-smoke/M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE/local_mpi_runs
```

Each of `serial_control`, `np2`, and `np4` contains independent `input/`,
`work/`, `results/`, and `evidence/` directories. The run IDs are:

- `serial-control-20260722T0405Z`
- `mpi-np2-20260722T0410Z`
- `mpi-np4-20260722T0414Z`

The executor refuses an existing destination, duplicate destination, invalid
run ID, missing or altered input, missing launcher, missing executable, invalid
task count, and non-MPI executable selected through an MPI launcher.

Machine-specific values are external in
`examples/reference_projects/graphene_surf_gr5x5/local_execution_profiles.yaml`.
Scientific paths and approved hashes are external in `local_smoke_spec.json`.
The core executor has no user, graphene, pseudopotential, OpenMPI, or fixed task
count hardcoding.

All profiles used `OMP_NUM_THREADS=1` and `OPENBLAS_NUM_THREADS=1` to prevent
hidden threaded oversubscription. Actual commands captured by the executor were:

```text
/usr/bin/time -v -o <run>/results/siesta.time /home/jmc/.local/siesta-5.4.2-serial/bin/siesta
/usr/bin/time -v -o <run>/results/siesta.time /usr/bin/mpirun -np 2 /home/jmc/.local/siesta-5.4.2-openmpi/bin/siesta
/usr/bin/time -v -o <run>/results/siesta.time /usr/bin/mpirun -np 4 /home/jmc/.local/siesta-5.4.2-openmpi/bin/siesta
```

Standard input was the protected copied `smoke.fdf`; stdout, stderr, GNU time,
hostname, version output, command argv, exit status and hashes are preserved per
run. MPI profiles also record `mpirun (Open MPI) 4.1.6`.

## Parsed results

All output was interpreted with `SiestaOutputParser`, including the authentic
SIESTA 5.4.2 `scf:` rows and termination markers.

| Field | serial control | MPI np=2 | MPI np=4 |
|---|---:|---:|---:|
| Exit code | 0 | 0 | 0 |
| Termination | `NORMAL_CONVERGED_TERMINATION` | same | same |
| Normal termination | true | true | true |
| SCF started / converged | true / true | true / true | true / true |
| SCF iterations | 10 | 10 | 10 |
| Atoms | 50 | 50 | 50 |
| Species | C | C | C |
| Final energy (eV) | -8261.710073 | -8261.710073 | -8261.710073 |
| Elapsed wall time (s) | 231.31 | 227.46 | 164.25 |
| Maximum RSS reported (KiB) | 1,336,308 | 904,072 | 605,808 |
| NaN detected | false | false | false |
| MPI failure detected | false | false | false |
| Filesystem failure detected | false | false | false |

Species identity comes from the protected external smoke specification and its
hashed FDF/pseudopotential; the parser independently observed one species and
50 atoms in every output.

Machine-readable comparison evidence is in `local_mpi_runs/comparison.json`.
Environment evidence is in `local_mpi_runs/environment_evidence.txt`.

## Framework regressions

The complete SIESTAFLOW suite passed after integration:

```text
240 passed in 24.96s
0 failed
0 errors
```

This includes the real-output parser, local executor, profiles, comparison,
hash gates, negative MPI classifications, duplicate run ID, and overwrite
refusal.
