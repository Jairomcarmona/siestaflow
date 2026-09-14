# Effective FDF materializer determinism micro-hotfix

- Baseline: `1b581969c8941e358ba936d12ed3e279ac143fa7`
- Branch: `fix/qraft-effective-fdf-materializer-determinism`
- R1 root cause: an absent governed label was appended from destination bytes, making a repeated render non-idempotent.
- R2 root cause: `primary_destination` was applied without validating the complete source-to-destination map.
- Write policy: all expected bytes are computed from the original closure plus declared updates; destination state is validated before any directory creation or write.
- Destination map: root, includes, nested includes, and raw redirects are mapped and required to have unique destinations before writing.

Validation:

- Baseline focused: `58 passed`.
- Targeted determinism/collision plus F02/F03: `16 passed`.
- Final focused: `83 passed`.
- Full suite: invoked once with `python -m pytest -q`; the execution channel ended at 11% without an observable exit status or summary. Per the task instruction this result is `PARTIAL`, not PASS or FAIL.

DET-01–DET-30, DET-32, and DET-33 passed from verified focused evidence. DET-31 did not pass because the full-suite completion was not observable. M7 remains `NOT_STARTED` and its development gate is `BLOCKED`.

- `NEW_EXECUTION_AUTHORITY = NO`
- `RUNTIME_SPECIAL_CASE = NO`
- `CORE_SCHEMA_CHANGE = NO`
