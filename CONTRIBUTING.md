# Contributing

SIESTAFLOW uses one Python codebase for editable development, user
distributions and generated HPC runtime packages. Read
[`DEVELOPMENT_GOVERNANCE.md`](docs/developer/DEVELOPMENT_GOVERNANCE.md) before
changing contracts, locks, runtime, MPI or scientific validation.

## Prepare the environment

Use Python 3.11 or newer in an isolated environment:

```bash
python -m venv .venv
python -m pip install -e .
```

Install pytest and build tooling in the development environment when they are
not already available. General YAML authoring additionally requires PyYAML;
canonical JSON and JSON-compatible YAML do not.

## Work on a change

1. Start from a locally verified commit and create a short branch such as
   `docs/scope`, `fix/runtime` or `phase3/recovery`.
2. Keep scientific inputs and project policy outside `src/siestaflow/`.
3. Add focused tests for the behavior and compatibility affected.
4. Update user and operational documentation with the same logical change.
5. Inspect the complete diff and obtain independent review proportional to
   risk.
6. Commit one meaningful unit with a Conventional Commit message.

Do not commit credentials, unauthorized geometries, generated workspaces,
pseudopotential binaries without redistribution authority or remote evidence
containing secrets. Do not invent HPC results, job IDs or acceptance.

## Verify

The default gate is:

```bash
git diff --check
python -m compileall -q src
python -m pytest -q
```

Focused categories are documented in
[`TESTING.md`](docs/developer/TESTING.md). A packaging change also builds and
inspects a clean wheel/sdist. Record missing external context as
`BLOCKED_BY_EXTERNAL_CONTEXT`; a local WSL pass is not a Yoltla pass.

## Documentation obligations

- New command: update `docs/user/CLI_REFERENCE.md`.
- New user flow: update `docs/user/USER_MANUAL.md`.
- Remote behavior: update `docs/operations/YOLTLA_RUNBOOK.md`.
- State or scientific gate: update `docs/scientific/SCIENTIFIC_GOVERNANCE.md`.
- User-visible behavior: update `CHANGELOG.md`.
- Architecture or contract decision: add an ADR and compatibility/migration
  plan.

Core-contract changes require contract tests and explicit compatibility.
Modules in `src/siestaflow/contracts/` must not import engines, launchers,
clusters, subprocesses, storage implementations or reference projects. Plugin
registration is explicit during composition; import-time registry mutation is
forbidden.

## Build and integrate

Use the `pyproject.toml` build backend; do not add CMake without a native
component and accepted ADR. Before integration, confirm a clean scope with
`git status --short`, review `git diff --stat` and the full diff, then run the
required gates. Phase transitions use a separate acceptance commit and
[`PHASE_ACCEPTANCE_TEMPLATE.md`](docs/validation/PHASE_ACCEPTANCE_TEMPLATE.md).
