# QRAFT Real-SIESTA Acceptance Closure

## Validated working tree

- Baseline commit: `20c07727dd0a40708957e97493a30027057cf391`.
- SIESTA: `5.4.2`.
- Launcher: OpenMPI `/usr/bin/mpirun`; `mpi_ranks = 4`.
- The supported M6/M7 boundary is the public Python API:
  `GroundStateProtocol` followed by `ElectronicPropertiesProtocol`.

The only validated production deltas are narrowly scoped SIESTA renderers:

- `ground_state.py`: a zero-valued geometric float is emitted as `0.0`.
- `electronic_properties.py`: integral-valued floating DOS/PDOS inputs retain
  a decimal representation such as `2.0`.

Focused assertions preserve both real-SIESTA regressions. No core, contracts,
or generic capability-runtime change is part of this closure.

## Native regression

- Result: `612 passed, 1 skipped, 0 failed`.
- Pytest duration: `159.51 s`.
- PowerShell duration: `163.1771617 s`.
- Exit: `0`.

The validated production/test files predate this regression and had these
SHA-256 values immediately before the documentation-only closure commit:

| File | SHA-256 |
| --- | --- |
| `src/qraft/engines/siesta/ground_state.py` | `cd9676e4a65139fc2d388cf68134cb7e124134d1ca961f502cf3ffaba5b8e93e` |
| `src/qraft/engines/siesta/electronic_properties.py` | `5ae16c5fb117159656ebb7f18fbcb7fd0dd82274aee623e75aeebb63dbe3bacc` |
| `tests/ground_state/test_ground_state_chain.py` | `6d2d3f5dc323d50b564e6f23e755d8842b20c23732661bdc186be0e5c9580950` |
| `tests/electronic_properties/test_electronic_property_fanout.py` | `872da119ab9df273da1e92fc784994172da4c0455ceeb9b3969e50dbdffe91fd` |

## Real-SIESTA gates

- M6 completed with converged SCF, a real `qraft.electronic-state`, and a
  real `.DM`.
- M7 BANDS, DOS, and PDOS completed with native `.bands`, `.DOS`, and `.PDOS`
  artifacts.
- The clean-room used only source FDF/templates, the Si pseudopotential, and
  convergence recipes; it created the run root, handoffs, attempts,
  stdout/stderr, artifacts, and provenance from scratch.
- SIESTA reported MPI execution with four parallel ranks for final SCF and
  each M7 sibling.
- M6 final-SCF and M7 parent ScientificIdentity are identical:
  `934cfae2ab5b432cabc680ae325a535ac4b499c3cbf047b217b20c6417515f79`.
- Missing and truncated/corrupt copies of real BANDS, DOS, PDOS, and
  STRUCT_OUT outputs were rejected fail-closed.
- In an independent two-process generic-runtime recovery, A/C were reused,
  B alone was retried, and the prior attempts/artifacts remained immutable.

External, non-versioned evidence is retained at:

- `/home/jmc/qraft-real-siesta-m6m7-acceptance/clean-room-final-mpi4`
- `/home/jmc/qraft-real-siesta-m6m7-acceptance/closure-negative-output-audit`
- `C:\Users\Jairo\Downloads\SIESTAFLOW_CONTEXT\qraft-closure-retry-reuse`

## Formal result

- `QRAFT_DEFECT unresolved = 0`.
- `QRAFT LOCAL CORE + M6/M7 REAL-SIESTA ACCEPTANCE = PASS`.
- `M8 = NOT_STARTED`.
- `M8 development gate = CLEARED`.
