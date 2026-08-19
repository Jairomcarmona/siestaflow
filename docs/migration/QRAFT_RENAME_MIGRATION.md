# QRAFT rename migration

QRAFT — Quantum Reproducible Automation & Flow Toolkit — is the project and
Python package identity beginning with this migration. SIESTA remains the
scientific engine name and is still exposed under `qraft.engines.siesta`.

## Migration map

| Previous identity | QRAFT identity | Scope | Risk |
| --- | --- | --- | --- |
| `src/siestaflow` | `src/qraft` | Python package | high |
| `siestaflow.cli` | `qraft.cli` | Python import | high |
| `siestaflow` command | `qraft` command | entrypoint | high |
| `runtime/siestaflow` | `runtime/qraft` | allocation-local package | critical |
| `.siestaflow-work` | `.qraft-work` | default new workspace | medium |
| SIESTAFLOW branding | QRAFT branding | current documentation/output | low |
| `engines/siesta` | unchanged | scientific backend | critical |

## Persisted compatibility boundary

The lowercase `siestaflow.*` identifiers used by Core Contracts 1.0,
workflow locks, run locks, capability IDs, recipe IDs, rule IDs, artifact
types, producers and evidence remain unchanged. They are serialized protocol
identifiers, not Python imports. Renaming them in place would invalidate or
alter hashes for existing evidence and would require an explicit versioned
schema migration, which is outside this identity-only change.

Readers therefore continue to accept historical v0.2 artifacts without
rewriting them. New Python imports and newly generated allocation-local
runtime packages use `qraft`; the stable v1 contract payloads may still contain
the legacy `siestaflow.*` protocol namespace.

Historical material is intentionally retained under `remote_validation/`,
`tests/fixtures/`, `docs/validation/`, `docs/governance/`, `docs/context/` and
the pre-existing migration records. These files record prior package names,
checksums, commands, jobs and provenance and must not be edited as though they
were current runtime sources.

The old `.siestaflow-work/` and `.siestaflow-local-slurm/` paths remain ignored
so local historical artifacts do not become untracked repository content.
QRAFT does not expose an active `siestaflow` Python compatibility package.

## Invariants

This migration does not intentionally change DAG semantics, scheduler
behavior, SLURM resources, MPI launchers, retries, recovery, scientific or
technical validation, SIESTA parsing, FDF handling, pseudopotential handling,
hash semantics, state transitions, events or result acceptance.
