# Contributing

Use Python 3.11 or newer, install editable, and run `python -m pytest -q` before proposing a change. Do not commit credentials, pseudopotential binaries, scientific geometry copied without authority, generated workspaces, or remote evidence containing secrets.

Project policy:

- Every new command updates `docs/user/CLI_REFERENCE.md`.
- Every new flow updates `docs/user/USER_MANUAL.md`.
- Every remote change updates `docs/operations/YOLTLA_RUNBOOK.md`.
- Every new state or gate updates `docs/scientific/SCIENTIFIC_GOVERNANCE.md`.
- Every user-visible change updates `CHANGELOG.md`.
- Every core-contract change includes compatibility classification, contract
  tests, and an adapter/migration when persisted or public data is affected.
- Modules under `src/siestaflow/contracts/` may not import engines, launchers,
  clusters, subprocesses, storage implementations, or reference projects.
- Plugin registration is explicit during composition; import-time registry
  mutation is forbidden.

Keep scientific data in external packages. A change that introduces project identifiers, species lists, fixed pseudopotential hashes, or mandatory parameter grids under `src/siestaflow/` will fail the anti-hardcoding test.
