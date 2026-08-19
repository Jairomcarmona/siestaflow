# Public API and extension points

For package version 0.2, only names in `qraft.__all__` are intentional public
Python API: application/configuration, ScientificIdentity, ExecutionSpec,
ExecutionProfile/ProfileStore, OutputModel, and engine/launcher/scheduler
adapter protocols. All other modules are internal unless a specific contract
document declares otherwise.

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

Tests for a new adapter must cover missing executable, resource validation,
command rendering and registry extension. Never add cluster-specific defaults
to the core.
