# M8-B Non-Collinear Magnetism

M8-B adds reproducible SIESTA 5.4.2 non-collinear magnetic intent by
composition over the existing effective-FDF materializer, M6 ground-state
protocol, compiled workflow runtime, and M7/M7.1 handoffs.  It introduces no
magnetic runtime, scheduler, recovery policy, or DAG primitive.

## Scientific input

The sole modern SIESTA interface rendered by M8-B is:

```text
Spin non-colinear
%block DM.InitSpin
  atom polarization [theta_deg phi_deg]
%endblock DM.InitSpin
```

`polarization` is `+`, `-`, or a finite numeric value.  A row has either two
fields (the SIESTA implicit z direction) or four fields (explicit spherical
angles in degrees).  M8-B preserves absent block, explicit empty block,
implicit-z rows, and explicit theta/phi rows as distinct scientific intent;
it does not normalize equivalent angles or convert collinear intent.

The renderer always writes `Charge.Mulliken end` when magnetic evidence is
required.  It does not introduce `NonCollinearSpin`, `SpinPolarized`,
`SpinOrbit`, `Spin.Spiral`, or `WriteMullikenPop` as a new interface.

`Spin.Fix`, `Spin.Total`, `Spin.Spiral`, SOC directives, DFT+U/Hubbard,
duplicate/out-of-range atom indices, partial directions, and non-finite values
are rejected.  An explicit `TimeReversalSymmetryForKpoints true` is likewise
rejected for a non-collinear input; M8-B does not add that reduction.

## Identity, restart, and evidence

The existing ScientificIdentity hashes the resolved `Spin` scalar and
`DM.InitSpin` block bytes.  Consequently z, x, y, and multi-atom directions
produce distinct identities, while MPI ranks, launcher, scheduler, host, and
timestamps do not.  This identity boundary prevents a changed vector intent
from reusing an incompatible density matrix; exact retries retain existing
reuse semantics.

M8-B extends the compatible `qraft.magnetic-state` artifact rather than
creating a second artifact type.  Its requested input is separate from
observed output.  Vector observations are explicitly identified as
`mulliken_spin_population`, sourced from `Charge.Mulliken`, represented in
Cartesian `Sx`, `Sy`, `Sz` with optional/reported `S`, and measured in the
SIESTA Mulliken population quantity (`electron_charge`), not assumed to be
magnetic moment in μB.  Parser provenance, final-FDF/stdout hashes, parent
ScientificIdentity, and convergence remain hash-bound.

M7 verifies the same artifact and source hashes for `polarized` and
`non-collinear` parents before BANDS/DOS/PDOS preparation.  M7.1 remains
conservative: a non-collinear parent leaves time-reversal `auto` unresolved;
explicit M7.1 policies remain representable.  This crystallographic policy is
separate from SIESTA's k-point time-reversal directive.

## Parser and real-acceptance preparation

The M8-B parser is fail-closed and requires a four-component non-collinear
runtime declaration plus a labelled Mulliken vector table containing `S`,
`Sx`, `Sy`, and `Sz`.  It rejects truncated, duplicate, incomplete,
inconsistent, or SOC-marked evidence and never reads charge as spin.

Two unexecuted real-SIESTA fixtures are prepared for the next acceptance gate
under `docs/validation/m8_b_noncollinear_real_siesta_fixtures/`, using the
M8-A hash-verified Fe PBE PSML:

1. BCC Fe, one atom: `1 + 90.0 0.0`.
2. Two-atom Fe, non-parallel input: `1 + 90.0 0.0`; `2 + 90.0 90.0`.

Their final vectors are physical observations, not assumed to equal the
initialization.  No real SIESTA execution is part of M8-B implementation.

## Boundaries

SOC (`Spin spin-orbit`), magnetic anisotropy, Spin.Spiral, DFT+U/Hubbard, and
all M8-C work remain excluded.  M8-B does not modify core, contracts, generic
runtime, runtime composition, scheduler, launcher, or attempt/recovery logic.
