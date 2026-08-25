# M8-C Full Spin-Orbit Coupling

M8-C adds the narrow, reproducible SIESTA 5.4.2 full-SOC input channel by
composing the existing effective-FDF materializer, M6 protocol, compiled
runtime and M7/M7.1 handoff. It adds no SOC runtime, scheduler, recovery path,
state machine, launcher, or DAG primitive.

## Supported input

The sole rendered spelling is:

```text
Spin spin-orbit
%block DM.InitSpin
  atom polarization [theta_deg phi_deg]
%endblock DM.InitSpin
Charge.Mulliken end
```

`SpinOrbitSpec` reuses the M8-B `NonCollinearSpinMoment` rows exactly. Thus an
absent block, an explicit empty block, implicit-z rows, and explicit theta/phi
rows retain their separate FDF bytes and ScientificIdentity. Angles are not
normalized. The canonical spin mode is `spin-orbit`.

M8-C rejects `Spin spin-orbit+onsite`, `Spin.OrbitStrength`, `Spin.Fix`,
`Spin.Total`, `Spin.Spiral`, `Spin.Spiral.Scale`, DFT+U/Hubbard, and an
explicit `TimeReversalSymmetryForKpoints true`. It neither silently renders a
strength of 1 nor changes SCF mixing, cutoffs, k-grid, basis, temperature, or
tolerances. Those remain numerical campaign decisions.

## Fully-relativistic pseudo safety

Full SOC requires PSML pseudopotentials with explicit fully-relativistic
semantics. The SIESTA engine layer accepts only PSML evidence declaring full
relativity/spin-orbit or explicit `l`/`j` projector channels. It blocks scalar
relativistic, unknown, malformed, and non-PSML inputs for SOC. File names,
species names, functional labels, and a `.psml` suffix are never evidence.

The generated `qraft.magnetic-state` records the pseudo SHA-256, PSML format,
compatibility classification, and evidence markers. The previous M8-A/B scalar
Fe pseudo remains valid for those milestones but is not accepted for SOC.

## Identity, retry, and evidence

Resolved FDF bytes already bind `Spin spin-orbit`, directional `DM.InitSpin`,
and pseudo hashes into ScientificIdentity. SOC Z/X/Y, non-collinear versus
SOC, and distinct full-SOC pseudo bytes therefore differ. MPI, launcher,
scheduler, host, paths, and timestamps do not. A changed SOC orientation or
a non-collinear-to-SOC transition gets a new identity/workspace and cannot
stage an incompatible `.DM`; exact retry keeps the established reuse policy.

QRAFT does not stage or discover `.ion` files in the existing scientific input
closure, so M8-C adds no `.ion` reuse channel.

SOC final-SCF output must be converged and declare SOC plus a labelled
Mulliken `S`, `Sx`, `Sy`, `Sz` table. The parser accepts the canonical
`spin-orbit`/four-component form and the native SIESTA 5.4.2 full-PSML
`spin-orbit+offsite`/eight-component form, the latter only with explicit
runtime SOC evidence (`spin-orbit semi-local pseudopotentials` or
`Enl(+so)`). It is fail-closed for truncated, ambiguous, non-finite,
duplicate, incomplete, or non-SOC-shaped output. Mulliken spin population is
not claimed to be an orbital magnetic moment. `WriteOrbMom` and SR/SO
decomposition are not required in V1.

`qraft.magnetic-state` remains the sole magnetic artifact. For SOC it records
requested direction, observed vector evidence, final-FDF/stdout hashes,
parent ScientificIdentity, convergence, parser provenance, and
`soc.enabled=true`, `implementation=full`, and pseudo provenance. M7 verifies
artifact bytes/envelope, identities, FDF/stdout/pseudo hashes, convergence,
mode agreement, and requested/observed summaries before BANDS/DOS/PDOS. M7.1
keeps `time_reversal=auto` unresolved for SOC; this is distinct from the
SIESTA FDF directive.

## Real acceptance preparation

`docs/validation/m8_c_full_soc_real_siesta_fixtures/` contains isolated-Fe Z
and X fixtures used through the canonical acceptance route with a separately
hash-verified fully-relativistic PBE PSML pseudo. The low-cost settings are
system-acceptance fixtures, not production convergence recommendations.

M8-C excludes onsite SOC, MAE campaigns/easy-axis search, Spin.Spiral,
DFT+U/Hubbard, SOC strength tuning, non-collinear extensions beyond the
existing directional initialization, and all M9 work.
