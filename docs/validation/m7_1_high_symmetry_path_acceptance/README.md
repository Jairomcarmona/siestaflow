# M7.1 High-Symmetry Path Acceptance

## Scope

M7.1 was accepted against the uncommitted implementation based on
`91202f3732b9a7cde6ff16a1c201adeaff23b3cb`.  It adds only reproducible
construction of the established M7 `BandPathSpec`; the existing
`ElectronicPropertiesProtocol` and generic compiled workflow runtime remain
the execution authority.

## Real symmetry provider

- SeeK-path `2.2.1`; spglib `2.7.0`.
- `SeekPathProvider` executed `get_path_orig_cell()` and
  `get_explicit_k_path_orig_cell()` only.  It did not call the primitive-cell
  or standardized-cell APIs.
- Verified M6 Si input geometry SHA-256:
  `c39745c155e75ddfa69c17648775b90b89b84fe1c699b3371cc8f8fb0c7c9b88`.
- Detected symmetry: No. 227, `Fd-3m`, Bravais lattice `cF`, inversion
  present, no augmented path, and not a supercell.
- The `0.1x`, `1x`, and `10x` `symprec` runs (`1e-6`, `1e-5`, `1e-4`) had the
  same space group, Bravais lattice, inversion state, supercell state, point
  coordinates, and full path topology: `SYMMETRY_STABLE`.
- The generated HPKOT topology was
  `GAMMA-X-U | K-GAMMA-L-W-X`; the explicit intervals were preserved as
  `[start, stop)` ranges.  The disconnected `U | K` boundary compiled as a
  fresh SIESTA BandLines row with point count `1`, not as a `U-K` segment.

## Mode and policy gates

- MANUAL: PASS.  It used no provider and preserved labels, reciprocal
  coordinates, point counts, and the discontinuity `G-X-U | K-G` exactly.
- SUGGEST: PASS.  Repeated identical input produced proposal SHA-256
  `edf4311491b13e79ba65db906b8a4a497d14a742841b8ebfe0e8c5d7e5d61618`;
  it created no M7 attempt, `.DM`, or `.bands` output.
- AUTOMATIC: PASS.  It produced BandPathSpec SHA-256
  `4f312b18e63624b11d183a24f4c86d2c26f8b182ddab1ddea9523ef274f802d0`.
- Explicit `time_reversal=true` and `false` were preserved.  Unresolved
  `auto` returned SUGGEST `REVIEW` and AUTOMATIC `BLOCKED` with
  `TIME_REVERSAL_UNRESOLVED`; the non-magnetic Si M6 FDF supplied explicit
  evidence for the real AUTOMATIC run.
- A real Si supercell yielded SUGGEST `REVIEW` and AUTOMATIC `BLOCKED`; MANUAL
  remained allowed.  Synthetic tests cover provider unavailable, provider
  execution failure, invalid provider data/geometry/coordinates/reference
  distance, corrupted topology, and symmetry ambiguity as fail-closed cases.

## M6 continuity and native SIESTA

- The verified parent M6 ScientificIdentity was
  `934cfae2ab5b432cabc680ae325a535ac4b499c3cbf047b217b20c6417515f79`.
- The final FDF, lattice, atoms and ordering, geometry hash, M6 identity, and
  `qraft_si.DM` reference/SHA-256 were unchanged before and after path
  generation.
- QRAFT ran SIESTA `5.4.2` through its configured OpenMPI launcher
  (`/usr/bin/mpirun`, Open MPI `4.1.6`) with `mpi_ranks=4`.
- M7 BANDS, DOS, and PDOS each completed with TechnicalValidation `PASS`.
  The native `.bands` had 208 k-points, 16 bands, and the expected path labels;
  `parse_bands()` validation passed.  BANDS artifact SHA-256:
  `c6653978a743f76380efca5b921fa1db970a65123f8c69ba90cd1a04e6305937`.

## Regression and modularity

- Focused M7/M7.1 regression: `28 passed`.
- Direct public-API contract: `1 passed`.
- Native full regression: `631 passed`, `1 skipped`, `0 failed` in `114.60 s`
  (`115.8045556 s` PowerShell measured).
- The final native runner used a short explicit base-temp and
  `PYTHONDONTWRITEBYTECODE=1`.  This avoids Windows path-length and ignored
  bytecode-cache contamination in unrelated package-builder tests; it does
  not alter QRAFT production or test behavior.
- Diffs from the baseline are empty for `src/qraft/core/`,
  `src/qraft/contracts/`, `capability_runtime.py`, scheduler code, and launcher
  code.  Generic provider code is under `src/qraft/symmetry/`; the only
  SIESTA-specific conversion is under `src/qraft/engines/siesta/`.
- Unresolved QRAFT defects: `0`.

## Formal status

- M0--M7: CLOSED
- REAL-SIESTA GATE: PASS
- M7.1: CLOSED
- M8: NOT_STARTED
- M8 development gate: CLEARED
