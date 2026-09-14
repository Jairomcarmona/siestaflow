# Task B — single-FDF canonical runtime authority

Baseline: `5309ad74514464db9b43550ebd78f650c057f85f`.

HEAD: recorded by the completed Git commit and task report; a commit cannot
contain its own final object SHA without a self-referential hash.

Production changed:

- `src/qraft/protocols/single_fdf.py`
- `src/qraft/execution/capability_runtime.py`

Focused tests:

- `python -m pytest tests/runtime_v1/test_single_fdf_vertical.py`: `10 passed`
- `python -m pytest tests/runtime_v1/test_single_fdf_vertical.py tests/runtime_v1/test_cli_profiles_output_v11.py tests/output/test_output_system.py tests/execution/test_capability_runtime.py`: `45 passed`

Final full suite: `577 passed`.

Gates: `TB-01` through `TB-09` are `PASS`.

Single-FDF now composes one canonical SIESTA capability node and delegates
attempt allocation, recovery, reuse and force-new behavior to
`CompiledWorkflowRuntime`. The historical helper remains inactive.
