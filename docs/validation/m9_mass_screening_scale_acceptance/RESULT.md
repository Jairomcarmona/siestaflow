# M9 — Mass Screening Scale Acceptance — CLOSED

## Acceptance

- Progressive characterization: 10, 25, 100, and 500 candidates.
- Canonical runtime concurrency: P=4.
- Resource shape: 4 CPUs/task, 16 CPUs total, 1 physical node.
- Candidate isolation and deterministic summary/ranking: PASS.
- N=500/P4: 500 completed, 0 failed, 0 blocked, 0 interrupted; zero
  collisions, leakage, unexpected propagation, ranking mismatches, and skips.
- N=500 summary SHA-256:
  `1ebd5d127d23bb8afd26562f99f5804e07b7a861e5b297f95fb9adf8fdda833e`.

## Persistence and recovery

The PRE-FIX full-state rewrite was confirmed O(N²)-like. The remediation uses
a deterministic canonical snapshot plus an incremental append-only journal,
while preserving legacy snapshots, recovery, evidence, and attempts.

N=100/P4 persistence improved from 3,862,714 bytes PRE-FIX to 117,163 bytes
POST-FIX (2 snapshots, 203 journal appends). N=500/P4 recorded 2 snapshots,
1,003 journal appends, and 578,771 total persistence bytes.

N=100/P4 recovery-cost characterization: 5 deterministic failed EVAL
branches, 5 blocked SCORE descendants, 190 reused nodes, 10 justified new
attempts, 5 candidates reexecuted, and 100 final completions. `attempt-0001`
remained immutable; `attempt-0002` appeared only on affected branches.

## Regression and boundary

- Focused native regression: 54 passed in 14.28 s.
- Authoritative native full regression: 668 passed, 1 expected conditional
  productization skip, 0 failed. The skip is
  `tests/productization/test_productization_v1.py:159` because
  `QRAFT_BUILD_PYTHON` is not installed; it is not M9-relevant.
- DFT runs = 0; SIESTA runs = 0; MPI runs = 0; Slurm runs = 0; Hydra runs = 0;
  Yoltla jobs = 0.

M10 remains `NOT_STARTED`.
