# Phase 2 researcher CLI acceptance

Status: `IMPLEMENTED_LOCAL_ACCEPTANCE`

Date: 2026-07-30

## Accepted vertical

- `environment check`: read-only discovery of Python, SIESTA identity/version,
  MPI capability, launcher, optional SLURM clients and workspace access.
- `project init`: dry-run and idempotent creation of a valid preparation-only
  ProjectPackage from explicit FDF, structure and pseudopotential manifest
  inputs.
- `input validate`: Core Contracts validation findings with stable rule code,
  severity, scope, location, evidence and remediation.

## Real local environment observation

The environment checker passed against the repository WSL sandbox with:

- Python 3.12.3;
- SIESTA 5.4.2 with MPI;
- `srun` and SLURM clients 23.11.4;
- a writable working directory.

The emitted environment ruleset SHA-256 was
`94b2c3105af1b26a0a92d8bedd244a609aa7a573cdf2bebebd0c9e32fedf5d86`.

This evidence confirms local command discovery only. It does not establish
Yoltla compatibility, controller reachability, scalability, numerical
convergence or scientific validity.

## Project initialization invariants

- Validation completes before any destination is written.
- Source FDF, structure and manifest bytes are preserved.
- Species declared in the FDF must be covered by the manifest.
- A request hash is stored in `project_init.lock.json`.
- An identical rerun is unchanged; a conflicting rerun is refused.
- Dry-run produces no filesystem effects.
- The generated campaign is `synthetic_only` and preparation-only.
- No functional, Hubbard U, spin, grid, pseudopotential, resource or
  convergence choice is synthesized.
- Structure chemistry remains explicitly marked for researcher review.

## Acceptance boundary

This is a local engineering acceptance of the Phase 2 CLI vertical. Phase 2
itself does not grant execution authority. The separately accepted local
Phase 3 prepared-run slice now connects `workflow.lock.json` to the allocation
controller, but its Yoltla acceptance remains pending.
