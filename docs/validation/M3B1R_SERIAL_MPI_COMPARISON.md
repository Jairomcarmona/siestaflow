# M3B1R serial/MPI technical comparison

## Result

All three executions meet the technical smoke criteria: exit 0, normal and
converged termination, 10 SCF iterations, 50 carbon atoms, no NaN, no MPI
failure, and no filesystem failure.

| Metric | serial control | np=2 | np=4 |
|---|---:|---:|---:|
| Final energy (eV) | -8261.710073 | -8261.710073 | -8261.710073 |
| SCF iterations | 10 | 10 | 10 |
| Time (s) | 231.31 | 227.46 | 164.25 |
| Maximum RSS (KiB) | 1,336,308 | 904,072 | 605,808 |
| Speedup vs serial | 1.000000 | 1.016926 | 1.408280 |
| Parallel efficiency | 1.000000 | 0.508463 | 0.352070 |

Observed energy differences:

```text
delta_energy_serial_np2 = 0.0 eV
delta_energy_serial_np4 = 0.0 eV
delta_energy_np2_np4     = 0.0 eV
```

Classification: `NUMERICALLY_CONSISTENT`.

The basis is exact equality at the precision reported by SIESTA, not an
invented scientific tolerance. SIESTAFLOW has no configured energy tolerance
for this comparison. The generic comparator therefore sends any nonzero delta
to `NUMERIC_DIFFERENCE_REVIEW_REQUIRED` unless an external, approved tolerance
is supplied.

## Interpretation boundary

The observed local speedup is descriptive only. `np=4` was faster than `np=2`
in this WSL run, but no claim is made about Yoltla, `srun`, cluster scaling, or
production performance. Technical acceptance depends on correct MPI execution
and numerical consistency, not positive speedup.

