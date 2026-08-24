# M8-B Real Non-Collinear Magnetism Acceptance Evidence

## Environment

- Baseline: `a6b8fcc368e46d2064512ff7c8cf26f8e9bce31d`.
- SIESTA: `/home/jmc/.local/siesta-5.4.2-openmpi/bin/siesta`, version 5.4.2.
- Launcher: QRAFT `ExecutionSpec` with OpenMPI `/usr/bin/mpirun`.
- Placement: one native-WSL filesystem workspace, one node, four MPI ranks,
  one CPU per rank.  The execution fingerprint is
  `dbbb3ce88e19964f82d1a96158485fc70439dbfdd573f5e277f364c0e7013707`.
- Fe PBE PSML SHA-256:
  `6b540d480fbdf34ef2058028ed6a6d47fc818f9ead7ea31e496720420ab44e12`.

Computational settings are intentionally reduced system-acceptance fixtures; they are not numerical-convergence recommendations for Fe.

## Preserved FCC performance diagnosis

The original two-atom periodic FCC attempt is retained under its native WSL
workspace and is not treated as a QRAFT failure.  Its effective FDF shows the
expensive `TZP`, `400 Ry`, and `8x8x8` point.  The preserved native stdout
records the first SCF iteration as 972.753 s and retains five real vector-spin
iterations; no evidence was deleted or overwritten.

- SIESTA declares `Parallelisations: MPI`, four parallel ranks, four
  non-collinear spin components, and a 2x2 diagonalization distribution.
- The comparable preserved four-rank timing report accounts for 2,180.394 CPU
  seconds across ranks against 562.809 wall seconds (about 545 CPU seconds per
  rank, approximately 97% of wall time).  `MPI total` is zero in that report.
- QRAFT's recorded `ExecutionSpec` environment is empty: it sets no
  `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, or `OPENBLAS_NUM_THREADS`.  The native
  SIESTA report identifies MPI, not a nested OpenMP mode.
- Workspaces are under `/home/jmc`, rather than `/mnt/c`; the preserved output
  is small (tens of KiB) and the timing profile is dominated by `compute_dm` /
  `diagon`, not I/O or MPI communication.

The high cost is therefore computation dominated — principally repeated
diagonalization in the production-like periodic fixture and its nonconvergent
SCF history — rather than an I/O, placement, or nested-threading failure.

## Native evidence

### BCC Fe, one atom

M6 completed for requested X (`+ 90.0 0.0`) and Y (`+ 90.0 90.0`) vectors.
The final-SCFs converged and published non-collinear `qraft.magnetic-state`
artifacts; M7 then prepared BANDS, DOS, and PDOS after its complete magnetic
parent verification.

| Request | Observed `S` | `Sx` | `Sy` | `Sz` | Artifact content SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| X | 2.267212 | 2.267212 | 0.0 | 0.0 | `55ecd4119cdb3255edbb296d891344149e61dbe85ba3213a002876cefd1ff2dc` |
| Y | 2.267212 | 0.0 | 2.267212 | 0.0 | `a78e1f796dfd9b3b84b6586158df259624571feb42ac9cafd331eccb0650535b` |

The corresponding artifact-file hashes are respectively
`2e8dba625fc825153edb9376d4b6e3d6f62e3077e69dbaa1f55cd6eeb8406889` and
`e5dd912b456633731b787456efc6c5ad1f84295f341dc5d7d4a1c5e073ea306b`.

### Fe2, non-parallel input

Requested vectors were atom 1 `+ 90.0 0.0` and atom 2 `+ 90.0 90.0`.  A
canonical QRAFT MPI-4 static execution completed normally, converged in 59
SCF iterations, and was subsequently recovered as a validated attempt.

| Evidence | `S` | `Sx` | `Sy` | `Sz` |
| --- | ---: | ---: | ---: | ---: |
| Atom 1 | 3.203569 | 2.997290 | 1.130978 | 0.0 |
| Atom 2 | 3.202395 | 1.126546 | 2.997704 | 0.0 |
| Total | 5.835412 | 4.123836 | 4.128681 | 0.0 |

ScientificIdentity is
`0ca5c80395cae45c872a3f6181865a8c0d438aae9851613668f4debcdaf57766`.
The magnetic artifact content and file hashes are respectively
`1305eda493a95737fc9eec9efc7c81c244710a55b68b52aa1ed270b978f95c57` and
`02d22195899803ffeee42e550468b889aaa4a2538059b0027abd527a67fcc5c1`.

The quantity is explicitly `mulliken_spin_population`, sourced from
`Charge.Mulliken`, with Cartesian `Sx`, `Sy`, and `Sz`, magnitude `S`, and
unit `electron_charge`.  It is not represented as an inferred magnetic moment
in `mu_B`.

## Identity, recovery, and safety gates

- Vector identities differ: Z
  `a45eaf28d3ef574eff046f7a1b41f734b4f1a67d80f095b88a2b073bd0990d5f`, X
  `1eca093539e45182aae66eb7eefab6ddb1a7a8501074893e8451535b231ed14a`, and Y
  `f2b4de26029c093846178746c4a2a66898091f9c1971ddd5d98f9c75749ad681`.
- Collinear and non-collinear identities differ; the collinear fixture is
  `172de064a17fa6d8e88bcf87ab39d44b51627117a234930b77beac0194e8db8c`.
- Changing only MPI resources preserves ScientificIdentity while changing the
  execution fingerprint (MPI-1:
  `31761d7637a25fcc5ab0d6c734a2a61b20e5be769f6e6ecd7dddcc49c0c3b134`).
- X and Y use distinct identities and attempts; the X density matrix is absent
  from Y's staged input.  An exact repeat of Y reused `attempt-0001`.
- M7 rejects a corrupted magnetic artifact and corrupted source stdout by
  SHA-256 before BANDS/DOS/PDOS preparation.
- For a real non-collinear parent, M7.1 `time_reversal=auto` is unresolved;
  explicit false remains representable.  M8-B does not inject
  `TimeReversalSymmetryForKpoints true`.
- Parser negatives cover truncation, missing and duplicate atoms, non-finite
  values, and inconsistent vector magnitude.  `Spin.Fix`, `Spin.Total`,
  Spin.Spiral, SOC, and Hubbard directives are rejected or out of scope.

## Test evidence and regression gate

- The WSL diagnostic full suite produced **637 passed, 1 skipped, 9 failed**
  in 228.61 s.  The same nine failures reproduce on the pre-M8A checkout
  `90cdd4e54e20cc2d99b631cffc23c2a305c74447`: a stale ZIP-member count, a
  Windows-only absolute pseudopotential path, and non-executable Slurm Bash
  test stubs.  Classification: `ENVIRONMENT_SETUP / TOOLING_OS /
  HERITAGE_TEST_ARTIFACT`, not M8-B.
- The formal native historical non-magnetic identity is
  `8e8723a8216fd0f0f6dfb0cbf61ee1da3f7381162878b85431255ef380785522`.
  A WSL observation of `757dcbfef9a93c5a84201c93e845a9282bcebc633ff76b73ba47ac0dddac4fd4`
  is recorded as `PORTABILITY_OBSERVATION`, plausibly due to fixture
  byte/newline representation.  It is deferred to M10 and is not accepted as
  the native baseline contract.
- Twelve ignored `src/qraft/**/__pycache__` directories generated by earlier
  interpreter runs were removed as workspace hygiene.  Native validation sets
  `PYTHONDONTWRITEBYTECODE=1`; no product code or package-builder behavior was
  changed for this cleanup.
- Native package preflight: **2 passed** in 6.38 s.  Native historical/vector
  identity gate: **2 passed** in 1.02 s.  Native focused M8-B/M8-A/M6/M7/M7.1/
  public API/package closure: **55 passed, 1 skipped** in 12.26 s.
- Authoritative native PowerShell full regression: Python 3.13.14, pytest
  9.0.3, command `python -m pytest -q --basetemp=<clean external base-temp>
  -p no:cacheprovider`, **646 passed, 1 skipped, 0 failed** in 211.55 s;
  process exit `0` (PowerShell elapsed 212.8970512 s).

The full-native regression gate is PASS.  M8-B keeps the existing generic
runtime, scheduler, launcher, core, and contracts boundaries unchanged; M8-C
remains out of scope and not started.
