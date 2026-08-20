# Current implementation limits

## Execution authority

`src/qraft/protocols/single_fdf.py` contains a fixed single-FDF DAG and an execution path with technical validation, immutable attempts, and reuse checks. `src/qraft/protocols/convergence.py` exposes a DAG-shaped plan, but its runtime iterates rendered points and calls `execute_fdf_plan` directly.

`src/qraft/workflows/` compiles deterministic hash-bound workflows and deliberately does not authorize execution. `src/qraft/execution/allocation_controller.py` executes a separate controller campaign schema. The application layer does not currently connect the CampaignSpec v1 runtime to the general compiler and allocation controller as one authority.

Therefore “DAG exists” must not be reported as “DAG executed” for the general workflow path.

## Scientific protocol boundary

The current CampaignSpec v1 evidence covers a small MgO mesh convergence campaign. It does not establish relaxation, vacuum/structural transforms, chained protocols, DOS/PDOS/bands as CampaignSpec fan-out nodes, spin-state selection, noncollinear/SOC, DFT+U, or LR-U.

DFT+U and LR-U are `DEFERRED_BY_PROJECT_DECISION`; this audit does not reinterpret that decision.

## Parser boundary

Real evidence validates normal SIESTA completion, SCF convergence, energy extraction, stdout/stderr preservation, technical PASS, and recovery reuse. Synthetic fixtures exercise non-convergence, truncation, missing pseudopotential, input, environment, timeout, spin, and warning cases. OOM, node failure, cancellation, numerical failure, and scientific extraction of stress/final geometry/magnetization are not claimed as real runtime evidence here.

DOS/PDOS/bands exporters and tests exist in legacy/read-only paths, but they are not evidence that CampaignSpec v1 executes an electronic fan-out.

## Environment note

The Windows focused pytest runner was blocked by `PermissionError [WinError 5]` while pytest scanned/cleaned its temporary directory. The same focused tests passed in native WSL Python; this is recorded as an environment soft issue, not a QRAFT functional result.
