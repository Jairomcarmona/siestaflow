# Public API and extension points

## Integration API 1.0 (Ola 1)

`qraft.api.__all__` is additionally public, with `API_VERSION = "1.0"`.
It exports the typed compose → compile → prepare → inspect route, its request,
result and policy types, lock readers/writer, contextual validator, canonical
controller and compiled runtime. The existing `qraft.__all__` is unchanged.
Changes to this surface follow the package 0.x compatibility policy; API version
and native contract versions are independent. No CLI JSON surface is promoted.

`WorkflowCompiler.compile_mapping(definition, source_root=..., source_bytes=None)`
uses `source_root` to resolve external artifacts without creating a definition
file. Native definition identity remains the SHA-256 of **document bytes**.
Without `source_bytes` it hashes compact, sorted UTF-8 JSON; with verified original
JSON/YAML bytes it returns the exact same lock as `compile(path)`. Different
whitespace or serialization still means a different native definition digest.
Supplied bytes disagreeing with the mapping are rejected. Legacy digests and
`compile(path)` are unchanged.

`RunPreparer(repository_root, task_adapters={capability_id: callable})` explicitly
registers preparation adapters. The callable receives `task` and keyword arguments
`by_task`, `artifacts`, `resolved_sources`, `profile`, `protected`, and returns one
controller task mapping. It must protect every scientific input in `protected`
(relative path → source Path); package validation and hashes remain mandatory.
Built-in adapters cannot be replaced. This does not execute or authorize tasks.

`CanonicalController.from_file(..., register_capabilities=callback,
capability_bindings={task_id: capability_id})` invokes the callback on its fresh
registry after built-ins and before freezing. Bindings require a verified prepared
run package and must equal the capability already fixed in its native workflow
lock. An arbitrary runtime override is forbidden. Effective capability IDs enter
the compiled workflow payload and runtime fingerprint before any attempts. The
registry rejects duplicate IDs, incomplete implementations and incompatible
contracts. Installed external capability dependencies are the deployment's
responsibility; they are not copied or dynamically discovered in QRAFT. The
legacy worker continues to use its existing built-ins; HF-1 orchestration and HPC
qualification remain pending, rather than calling Hubbard through a generic
command or pretending to establish its scientific outcome.

Consumer fixtures: `tests/consumer/`; reproducible CPython 3.12.10/uv 0.11.14
environment: `uv sync --locked --extra dev --group ci --python 3.12.10`.
The Windows/Linux consumer gate builds and tests an installed wheel outside the
checkout with isolated Python. Existing complete Linux 3.11–3.13 regressions
remain separate; this Windows gate does not claim HPC acceptance.

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

M8-B additionally exposes `NonCollinearSpinSpec` and
`NonCollinearSpinMoment`.  They model only `Spin non-colinear` and
`DM.InitSpin` polarization with optional explicit theta/phi directions.  SOC,
Spin.Spiral, DFT+U/Hubbard, and execution controls remain outside this API.

M8-C additionally exposes `SpinOrbitSpec`.  It intentionally reuses
`NonCollinearSpinMoment` for `Spin spin-orbit` directional `DM.InitSpin`
rows; full SOC requires engine-verified fully-relativistic PSML inputs.
Onsite SOC, `Spin.OrbitStrength`, spin spirals, Hubbard controls, orbital
moments, and execution controls are not representable.

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
