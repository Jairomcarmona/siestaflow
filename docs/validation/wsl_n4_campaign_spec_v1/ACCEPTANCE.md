# WSL N=4 Acceptance

| Field | Verified value |
|---|---|
| Date | 2026-08-19 (America/Mexico_City) |
| Branch | `feat/qraft-campaign-spec-v1` |
| QRAFT commit | `3264c7beca29860e2fb4fb4f0f79a243ac5eac38` |
| QRAFT | 0.2.0 |
| SIESTA | 5.4.2 |
| MPI | OpenMPI 4.1.6 |
| Scheduler | local SLURM |
| SLURM job | 264 |
| Nodes | 1 |
| MPI ranks | 4 |
| Campaign | MgO mesh smoke |
| Points | 80, 100 Ry |
| Metric | `energy_per_atom` |
| Criterion | delta <= 0.1 eV, consecutive=1 |
| Technical result | PASS for both points |
| Scientific result | CONVERGED; selected point 100 Ry |
| Recovery | PASS; `REUSED_VALIDATED_ATTEMPT` |
| Identity check | PASS |
| Overall | PASS |

The acceptance was executed through QRAFT inside the single local SLURM
allocation. No manual SIESTA replacement was used.
