# Effective-FDF final revalidation

- Validated SHA: `1b8301ca323fd7ab53e483cb8daea63d5f7eea93`
- Final validation execution: native Windows PowerShell, outside the Codex sandbox
- Python: `3.13.14`
- pytest: `9.0.3`
- PyYAML: `6.0.3`
- `FULL_SUITE_EXIT=0`
- Result: `603 passed`, `1 skipped`, `0 failed`
- pytest elapsed: `157.83 s`
- PowerShell measured elapsed: `159.0866194 s`

Earlier Codex-local `WinError 5` failures in pytest `tmp_path` and
`cleanup_dead_symlinks` are classified as `ENVIRONMENT_SETUP / TOOLING_OS`,
not as a QRAFT defect.

- Production changes during final validation: `NONE`
- Test changes during final validation: `NONE`
- Config changes during final validation: `NONE`
- DET-31: `PASS`
- Effective-FDF freeze: `YES`
- M0–M6: `CLOSED`
- M7 formal status: `NOT_STARTED`
- M7 development gate: `CLEARED`
