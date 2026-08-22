# M5 production-readiness hotfix

- Baseline SHA: `16e45768d926ec1ae4d304a725801afea4d2daf1` (`feat: add fixed-cell relaxation capability v1`).
- Final SHA: final branch HEAD, recorded in the delivery report.
- Status: `M5 PARTIAL`; `M6 BLOCKED` because the one required full-suite run did not pass.
- Production files changed: `src/qraft/engines/siesta/input_closure.py`, `src/qraft/engines/siesta/relaxation.py`, `src/qraft/protocols/relaxation.py`, and pure closure composition in `src/qraft/protocols/single_fdf.py`.

## Corrective evidence

- Real-force fixture: the documented `siesta: Atomic forces (eV/Ang):` section with ordinary and constrained `Max` records. The parser chooses the final valid force section and its constrained `Max`; otherwise its final ordinary `Max`. `eV/Ang` and `Ry/Bohr` normalize explicitly to `eV/Ang`; the explicit legacy one-line fixture remains supported.
- Scientific input closure: the shared pure resolver binds the root FDF, recursive include/redirection files, resolved pseudopotentials, and (for M5) an explicit pseudo manifest. The M5 workflow binds and stages `input.fdf`, `subdir/settings.fdf`, `C.psf`, the manifest, and the initial geometry envelope. The adversarial test verifies source hashes in compiled external-artifact evidence and verifies all execution files are present before the fake executable succeeds.
- FDF semantics: missing `AtomicCoordinatesFormat` is `Bohr`. `MD.VariableCell` accepts true `T`, `true`, `.true.`, `yes`, and blank; false `F`, `false`, `.false.`, and `no`; absence is false; malformed values raise. True and blank variable-cell forms are rejected before launch.
- `SystemLabel` lookup uses existing `normalize_label()`; an aliased `System_Label` resolves `closure.STRUCT_OUT`.

## Test record

- Baseline focused: `37 passed` — `tests/relaxation tests/execution/test_capability_runtime.py tests/runtime_v1/test_single_fdf_vertical.py`.
- Targeted implementation: `19 passed` — `tests/relaxation/test_relaxation_protocol.py tests/runtime_v1/test_single_fdf_vertical.py`.
- Final focused: `49 passed` — `tests/relaxation tests/execution/test_capability_runtime.py tests/runtime_v1/test_single_fdf_vertical.py tests/campaigns/test_chained_numerical_convergence.py`.
- Full suite: executed exactly once with `pytest -q`; **FAIL**. Pytest recorded `tests/workflows/test_dag_execution_unification.py::test_convergence_execution_seam_is_characterized_before_unification` and `tests/runtime_v1/test_single_fdf_vertical.py::test_invalid_canonical_attempt_is_not_reused` as failed. No post-suite production or test changes were made.

`NEW_EXECUTION_AUTHORITY = NO`

`RUNTIME_SPECIAL_CASE = NO`

`CORE_SCHEMA_CHANGE = NO`

| Gate | Result |
| --- | --- |
| M5P-01 | PASS |
| M5P-02 | PASS |
| M5P-03 | PASS |
| M5P-04 | PASS |
| M5P-05 | PASS |
| M5P-06 | PASS |
| M5P-07 | PASS |
| M5P-08 | PASS |
| M5P-09 | PASS |
| M5P-10 | PASS |
| M5P-11 | PASS |
| M5P-12 | PASS |
| M5P-13 | PASS |
| M5P-14 | PASS |
| M5P-15 | PASS |
| M5P-16 | PASS |
| M5P-17 | PASS |
| M5P-18 | PASS |
| M5P-19 | PASS |
| M5P-20 | PASS |
| M5P-21 | PASS |
| M5P-22 | PASS |
| M5P-23 | PASS |
| M5P-24 | PASS |
| M5P-25 | PASS |
| M5P-26 | PASS |
| M5P-27 | PASS |
| M5P-28 | PASS |
| M5P-29 | FAIL |
| M5P-30 | PASS |
