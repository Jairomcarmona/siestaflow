# M5 clean-room revalidation

- Validated SHA: `cab681310182ee8f3d4ee1763c10e9e309b1adbf`.
- Branch: `validate/qraft-m5-clean-room-revalidation`.
- Clean worktree: `C:\Users\Jairo\Downloads\SIESTAFLOW_CONTEXT\qraft-m5-clean-room`.
- Environment: Python 3.13.14, pytest 9.0.3, PyYAML 6.0.3.
- Bootstrap: `python -m pip install "PyYAML>=6.0" "pytest>=8"`; only the already-declared PyYAML dependency was installed. No tracked repository files changed.
- The first clean-room attempt was environment-blocked by missing PyYAML and did not execute a full suite.

## Inventory and gates

- Collect-only: `14 tests collected` without import errors.
- `test_convergence_execution_seam_is_characterized_before_unification`: absent.
- `test_convergence_execution_uses_the_canonical_runtime`: present.
- `test_invalid_canonical_attempt_is_not_reused`: absent.
- Workflow module: `1 passed`.
- Single-FDF vertical module: `13 passed`.
- Relaxation module: `6 passed`.
- M1/M4 sentinel: `30 passed`.
- Full suite (once): `591 passed, 1 skipped in 136.49s`.

The two failures reported by the earlier non-clean run were not reproducible
from the exact committed SHA in a dependency-complete clean worktree.

| Gate | Result |
| --- | --- |
| CRE-01 | PASS |
| CRE-02 | PASS |
| CRE-03 | PASS |
| CRE-04 | PASS |
| CRE-05 | PASS |
| CRE-06 | PASS |
| CRE-07 | PASS |
| CRE-08 | PASS |
| CRE-09 | PASS |
| CRE-10 | PASS |
| CRE-11 | PASS |
| CRE-12 | PASS |
| CRE-13 | PASS |
| CRE-14 | PASS |
| CRE-15 | PASS |
| CRE-16 | PASS |
| CRE-17 | PASS |
| CRE-18 | PASS |
| CRE-19 | PASS |

M5 is `CLOSED`; M6 is `READY TO START`.
