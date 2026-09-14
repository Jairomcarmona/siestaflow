# M8-A Collinear Magnetism Real-SIESTA Acceptance

## Scope and environment

- Baseline: `90cdd4e54e20cc2d99b631cffc23c2a305c74447`.
- QRAFT invoked the existing MPI-enabled SIESTA executable at
  `/home/jmc/.local/siesta-5.4.2-openmpi/bin/siesta` through `/usr/bin/mpirun`
  with `mpi_ranks=4` (OpenMPI 4.1.6).
- Native regression environment: Python 3.13.14 and pytest 9.0.3.
- The temporary, non-versioned acceptance workspace was
  `/home/jmc/qraft-real-siesta-m8a-acceptance`.  Raw outputs, pseudopotentials,
  density matrices, and execution workspaces are intentionally not committed.
- The acceptance pseudopotential was `Fe.psml`, PSML 1.1, scalar-relativistic,
  PBE, SHA-256 `6b540d480fbdf34ef2058028ed6a6d47fc818f9ead7ea31e496720420ab44e12`.

## Real-SIESTA results

- BCC Fe, one atom, explicit `DM.InitSpin 1 +`: M6 completed through final
  SCF and published a verified `qraft.magnetic-state`.  ScientificIdentity:
  `5619b574ce5f710ad32bdb5d8587d4cb34f8cb550167aa3fcb0a34f46b33cb4d`.
  The requested initialization remained distinct from the observed Mulliken
  moment, `2.169840` electron charges.
- FCC Fe, two atoms, FM (`1 +`, `2 +`): M6 completed with identity
  `77d26c4d837034942099c0d1efeed5708b4375dc9245d0af9f230bc1211465c7`.
- FCC Fe, two atoms, AFM (`1 +`, `2 -`): M6 completed with identity
  `7b6787872da8a04020ba36299cbca1731d739a37679ed73f03a7722d8e29e63d`.
  The observed moments were `+2.129483` and `-2.129483`, with total `0.0`.
  This is physical output evidence; QRAFT does not infer observed magnetic
  order merely from the requested initialization.
- FM and AFM ScientificIdentities differ.  Independent workspaces and input
  manifests contained no transferred density matrix, so a new magnetic intent
  cannot silently reuse a prior incompatible `.DM`.  Exact re-execution of an
  identical AFM identity reused its eight completed attempts without rerunning
  SIESTA.
- A canonical MPI-4 `Spin.Fix true` / `Spin.Total 2.0` smoke execution
  converged successfully.

## Evidence and downstream checks

- The real SIESTA 5.4.2 parser accepts the documented collinear output form
  (`Spin configuration = collinear`, two spin components, and `Sz` Mulliken
  columns), rejects truncation/ambiguity, and records observed moments only
  when present.
- `Charge.Mulliken end` is rendered deterministically for collinear evidence.
- `qraft.magnetic-state` is hash-bound to its source output and parent
  ScientificIdentity.  Independently corrupting either its artifact content or
  its referenced stdout was rejected.
- A polarized M6 electronic state was accepted by M7 preparation for BANDS,
  DOS, and PDOS only after magnetic-parent verification.
- M7.1 time-reversal `auto` remains unresolved for a polarized parent, so it
  requires review/blocking rather than assuming a non-magnetic parent.

## Test evidence

- Focused M8-A, package-closure, M6/M7, and M7.1 tests: **48 passed** in
  15.73 s.
- Final native regression, executed once after the final production changes:
  **639 passed, 1 skipped** in 117.75 s; `FULL_SUITE_EXIT=0` (PowerShell
  measured 118.5113582 s).

## Scope protection and formal status

- No changes were made to `qraft.core`, `qraft.contracts`, generic capability
  runtime, runtime composition, scheduler, or launcher layers.
- The package closure change includes the new engine-neutral
  `qraft.magnetism` module in both canonical controller and M4 remote runtime
  packages.
- Unresolved QRAFT defects: 0.

Formal status: M0--M7 CLOSED; REAL-SIESTA GATE PASS; M7.1 CLOSED; M8-A
CLOSED; M8-B NOT_STARTED; M8-C NOT_STARTED.
