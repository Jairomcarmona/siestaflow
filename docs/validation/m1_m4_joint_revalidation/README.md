# Joint M1–M4 revalidation

- Baseline SHA: `71773e3dd707190608d36c27b47a49a36cea9dfc`
- Validation branch: `validate/qraft-m1-m4-joint-revalidation`
- Date: `2026-08-22`
- Final SHA: final branch HEAD, recorded in the delivery report.

## Results

- M1: `pytest -q tests/execution/test_capability_runtime.py tests/runtime_v1/test_single_fdf_vertical.py tests/runtime_v1/test_cli_profiles_output_v11.py tests/output/test_output_system.py` — `52 passed in 7.62s`.
- M2 runtime: `pytest -q tests/execution/test_runtime_convergence_closure.py` — `22 passed in 2.85s`.
- M2 outputs: `pytest -q tests/m2/test_outputs_campaigns.py` — `17 passed in 0.77s`.
- M3: `pytest -q tests/execution/test_m3_generic_composition_failure_model.py` — `3 passed in 0.89s`.
- M4: `pytest -q tests/campaigns/test_chained_numerical_convergence.py` — `9 passed in 7.89s`.
- Full suite: `pytest -q` — `584 passed`, no failures, skips, xfails, or xpasses.

| Gate | Result |
| --- | --- |
| RV-01 | PASS |
| RV-02 | PASS |
| RV-03 | PASS |
| RV-04 | PASS |
| RV-05 | PASS |
| RV-06 | PASS |
| RV-07 | PASS |
| RV-08 | PASS |
| RV-09 | PASS |
| RV-10 | PASS |
| RV-11 | PASS |
| RV-12 | PASS |
| RV-13 | PASS |
| RV-14 | PASS |
| RV-15 | PASS |
| RV-16 | PASS |
| RV-17 | PASS |

M1 CLOSED

M2 CLOSED

M3 CLOSED

M4 CLOSED

M5 UNBLOCKED / READY TO START
