# M8-B Real-SIESTA Fixture Inputs

These are M8-B system-acceptance inputs for QRAFT's canonical SIESTA/OpenMPI
route.  The hash-verified external `Fe.psml` is staged beside each input at
execution time; pseudopotentials, density matrices, stdout, and workspaces
are intentionally not versioned here.

- Pseudopotential: Fe PBE PSML 1.1, scalar-relativistic.
- Required SHA-256: `6b540d480fbdf34ef2058028ed6a6d47fc818f9ead7ea31e496720420ab44e12`.
- SIESTA: 5.4.2 via OpenMPI with four ranks.
- M8-B initializations are evidence requests only; observed vectors are read
  from converged native `Charge.Mulliken end` output and are not presumed to
  equal their initial directions.

Computational settings are intentionally reduced system-acceptance fixtures; they are not numerical-convergence recommendations for Fe.

`bcc_fe_x.fdf` is the one-atom x-oriented M6 fixture.  Its equivalent
y-oriented real execution also completed and published a verified
`qraft.magnetic-state`.  `fe2_nonparallel.fdf` is the smallest two-atom
non-parallel fixture that converged in the canonical MPI-4 route.  It exists
to exercise separate X/Y initial directions and native vector parsing.

`fcc_fe_nonparallel.fdf` preserves the two-atom periodic input used for the
interrupted high-cost observation.  Its evidence is retained; it is not a
failed QRAFT acceptance calculation and is not used as the minimal fixture.
