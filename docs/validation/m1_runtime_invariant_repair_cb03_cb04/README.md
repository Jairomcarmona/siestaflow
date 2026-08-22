# M1 runtime invariant repair — CB-03 / CB-04

Baseline SHA: `79a384f2284fba3b05e7f6068366e6c8ecee3f26`.

Final commit SHA: reported by the completed Git commit and task report; a Git
commit cannot contain its own final object SHA without a self-referential hash.

Production changed:

- `src/qraft/execution/capability_runtime.py`

Tests changed:

- `tests/execution/test_capability_runtime.py`

Focused commands and results:

- `python -m pytest tests/execution/test_capability_runtime.py` (baseline): `14 passed`
- `python -m pytest tests/execution/test_capability_runtime.py -k reserved_attempt_survives_crash`: `1 passed`
- `python -m pytest tests/execution/test_capability_runtime.py -k "valid_attempt_is_reused_without_relaunch or capability_implementation_version_invalidates_runtime_reuse or plugin_version_participates_in_runtime_provenance"`: `3 passed`
- `python -m pytest tests/execution/test_capability_runtime.py`: `17 passed`

CB-03 before: an attempt directory could become visible before the durable task
state reserved its number. After: the existing atomic runtime state records
`attempts`, `last_attempt`, and `RUNNING` before directory creation; a crash
in that window consumes `attempt-0001`, and recovery creates `attempt-0002`.

CB-04 before: runtime reuse identity omitted registered implementation
provenance. After: each task contributes its resolved capability ID,
implementation version, plugin ID, and plugin version to the deterministic
runtime fingerprint. ScientificIdentity and ExecutionSpec are unchanged.

`FULL_SUITE_RERUN = NO`

Reason: the full suite is intentionally deferred until all reopened blocking
defects are repaired.
