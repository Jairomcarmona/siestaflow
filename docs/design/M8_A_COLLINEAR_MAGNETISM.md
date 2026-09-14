# M8-A — Collinear magnetism

M8-A adds reproducible **collinear** magnetic intent to the existing SIESTA
and M6/M7 composition.  It does not add an executor, scheduler, recovery
engine, workflow primitive, non-collinear magnetism, SOC, spin spirals,
DFT+U, Hubbard terms, or magnetic anisotropy.

## Model and SIESTA rendering

`qraft.CollinearSpinSpec` is immutable, canonical JSON data for `Spin
polarized`.  Its `initial_moments` field has two intentionally distinct
states:

- `None`: no `DM.InitSpin` block is rendered; SIESTA retains its distinct
  default initialization semantics.
- `()`, or a tuple of moments: an explicit `DM.InitSpin` block is rendered.
  An explicit empty block is therefore never canonicalized into absence.

Each `CollinearSpinMoment` carries one-based atom index and either `+`, `-`,
or a finite numerical moment.  `+` and `-` retain SIESTA's maximum-up and
maximum-down spelling.  Atom indices are unique, positive, and bounded by
`NumberOfAtoms`; numerical values are finite.  M8-A emits only modern SIESTA
5.4 syntax:

```text
Spin polarized
%block DM.InitSpin
  1 +
  2 -
%endblock DM.InitSpin
Spin.Fix true
Spin.Total 0.0
```

`Spin.Total` requires `Spin.Fix true`.  `Spin.Fix` may be present without a
target total.  The adapter fails closed on a parent FDF that already expresses
different magnetic directives, non-collinear/SOC directives, malformed rows,
out-of-range atoms, or a conflicting Mulliken output policy. Rendering delegates to the existing effective-FDF
materializer and preserves the normal include, pseudopotential, and geometry
closure.

## Identity and M6/M7 continuity

`DM.InitSpin`, `Spin.Fix`, and `Spin.Total` are part of the existing SIESTA
`charge_spin` ScientificIdentity component.  Thus FM (`1 +; 2 +`), AFM
(`1 +; 2 -`), numerical moments, absent initialization, and explicit-empty
initialization are all distinct when their effective FDF bytes differ.
Placement (MPI ranks, nodes, launcher, scheduler, host, paths, timestamps)
remains outside ScientificIdentity.

The existing M6 ground-state protocol requires the same collinear intent in
its numerical, relaxation, and final-SCF templates.  For a converged polarized
final SCF it publishes a `qraft.magnetic-state` artifact and adds minimal
magnetic evidence to `qraft.electronic-state`:

- requested initialization and fixed-spin policy;
- observed spin mode, total moment when output provides it, and Mulliken
  per-atom moments when an adequate section is present;
- final-FDF and stdout hashes, parser provenance, and SIESTA version.

For a polarized final-SCF, M8-A materializes `Charge.Mulliken end`
deterministically. This is the supported SIESTA output control for final
atomic moments; M8-A does not introduce `WriteMullikenPop`. The electronic
state references the magnetic envelope and stdout through root-relative paths
with file hashes. M7 re-opens both files, verifies envelope hashes, source
hashes, convergence, parent ScientificIdentity, and summary agreement before
accepting a polarized handoff.

Requested FM/AFM intent and observed final moments are separate fields.  M8-A
never declares an observed magnetic order solely from the initialization.
Legacy non-magnetic electronic states remain valid.

The M7 parent loader preserves `spin_mode` and magnetic artifact provenance.
M7.1 continues to return unresolved time reversal for `Spin polarized`; M8-A
does not infer `false` merely from collinearity.  A user must provide an
explicit M7.1 time-reversal policy until a later milestone establishes a safe
scientific rule.

## Output evidence

The SIESTA adapter parses `redata` evidence for `Spin configuration =
polarized` and two spin components.  It parses an optional completed Mulliken
atomic-population section using the documented `Atom ... Total charge spin`
and final `Total charge spin` rows.  A declared but incomplete section,
duplicate atomic moment, conflicting totals, non-collinear/SOC evidence, or a
non-converged SCF fails closed. Because M8-A materializes `Charge.Mulliken
end`, the M6 magnetic final-SCF also requires one final moment for every atom;
it does not publish a polarized state with missing atomic evidence. No generic
runtime parser was changed.

## Future real acceptance fixtures

Real M8-A acceptance requires both small Fe cases with the available
SIESTA-5.4.2-compatible Fe pseudo, not just a serial or one-atom smoke test:

- the official one-atom bcc Fe PBE example (`Examples/Fe/Fe.fdf`) using its
  accompanying `Fe.psml`, to validate polarized output and total-moment
  parsing;
- a two-atom fcc Fe case using the same compatible pseudo, with explicit
  `DM.InitSpin` rows `1 +` and `2 -`, to validate a real AFM initialization
  and two opposite atomic Mulliken moments.

A compatible tutorial `Fe.psf` is also locally available. These are future
real-SIESTA acceptance fixtures only; no SIESTA calculation is run by M8-A
implementation validation.

## Scope boundary

M8-B (non-collinear magnetism) and M8-C (SOC and related physics) remain
`NOT_STARTED`.  They must not reuse an implicit M8-A time-reversal decision or
extend this scalar model with angle fields.
