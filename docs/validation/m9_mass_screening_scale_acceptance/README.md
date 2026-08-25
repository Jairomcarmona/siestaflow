# M9 — Mass Screening Scale Acceptance

Status: **CLOSED**

M9 was accepted on the canonical synthetic workflow path with deterministic
10/25/100/500-candidate characterization and P=4 concurrency. The validated
resource shape was 4 CPUs per task, 16 CPUs total, and 1 physical node.

Acceptance evidence records candidate isolation, deterministic scientific
metrics/ranking, filesystem/evidence behavior, memory/runtime observations,
the PRE-FIX persistence bottleneck, and its canonical-snapshot plus
append-only-journal remediation. POST-FIX N=500/P4 completed all 500
candidates with zero failures, blocks, interruptions, collisions, leakage,
propagation, ranking mismatches, or silent skips.

Recovery-cost evidence at N=100/P4 records selective reuse, immutable
attempts, branch-local retry, and completion of all final nodes without a
clean-equivalent duplicate campaign.

Focused native regression: 54 passed in 14.28 s. Authoritative native full
regression: 668 passed, 1 expected conditional productization skip, 0 failed;
the skip is `tests/productization/test_productization_v1.py:159` because
release build tooling is not installed (`QRAFT_BUILD_PYTHON`).

M9 intentionally used no DFT, SIESTA, MPI, Slurm, Hydra, or Yoltla runs.
Those portability and production concerns belong to M10, which remains
`NOT_STARTED`.

See `RESULT.md` and the preserved `PRE-FIX`, `root_cause`, `post_fix`,
`n500_p4`, and `recovery_cost_n100` evidence.
