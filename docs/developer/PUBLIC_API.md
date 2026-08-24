# Public API and extension points

For package version 0.2, only names in `qraft.__all__` are intentional public
Python API: application/configuration, ScientificIdentity, ExecutionSpec,
ExecutionProfile/ProfileStore, OutputModel, engine/launcher/scheduler adapter
protocols, and M7.1 neutral band-path planning models. The latter comprise
`CrystalStructure`, `BandPathMode`, `BandPathRequest`, `BandPathSegment`,
`BandPathProposal`, `BandPathPlanner`, `SymmetryAnalysis`, `ProviderPath`, and
`SymmetryPathProvider`. All other modules are internal unless a specific
contract document declares otherwise.

M8-A additionally exposes the neutral collinear-spin models
`CollinearSpinSpec`, `CollinearSpinMoment`, and `CollinearMomentToken`.  They
represent only `Spin polarized`, `DM.InitSpin`, and optional `Spin.Fix` /
`Spin.Total`; non-collinear angles, SOC, spirals, and Hubbard parameters are
not representable by this API.

Public CLI stability is documented in `docs/user/cli.md`. Persistent schema
stability is independent from Python import stability.

## Extensions

- Engine: implement `EngineAdapter`, declare executable/version probing through
  `EngineRegistry`, and register a protocol that names the engine.
- Launcher: register a `RegisteredLauncher` with factory, resource invariants,
  default command and probe metadata. Do not add a global launcher `if/elif`.
- Scheduler: register a `RegisteredScheduler` with command/environment probe
  metadata.
- Protocol: register a `ProtocolAdapter` with planner, runner, engine and
  accepted parameters. Planning must not authorize execution.
- Output: implement `OutputContributor`; machine evidence remains authoritative.
- Symmetry path: implement `SymmetryPathProvider` using only neutral
  `CrystalStructure`, `SymmetryAnalysis`, and `ProviderPath` values. A provider
  must never introduce an execution authority or transform an M6 parent
  structure silently.

Tests for a new adapter must cover missing executable, resource validation,
command rendering and registry extension. Never add cluster-specific defaults
to the core.
