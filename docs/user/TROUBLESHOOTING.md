# Troubleshooting

- `qraft: command not found`: activate the venv and confirm the wheel is
  installed with `python -m pip show qraft`.
- SIESTA `NOT_FOUND`: load its module, fix `PATH`, or set `engine.executable`
  in a profile/`--siesta`.
- Launcher unavailable: inspect `qraft env`; load MPI/SLURM or select a valid
  registered launcher. Do not emulate MPI with unrelated process launches.
- Invalid profile: run `qraft profile validate NAME`; verify schema 1.0,
  positive resources and node capacity.
- Invalid partition or MPI launch failure: compare `qraft config` with the
  actual allocation and inspect attempt stderr.
- SLURM unavailable: use a local profile or execute the cluster profile inside
  the intended cluster environment.
- SCF/technical failure: inspect `qraft.out`, `stdout.txt`, and `stderr.txt`.
  SCF failure is not repaired automatically.
- Resume: run from the project containing `.qraft-runs/session.json`, or pass
  `--runs-root`.
- Output location: `qraft status` and REPL `paths`/`attempts` show exact paths.

`qraft env` is read-only and is the first diagnostic command.

## Specialized and legacy diagnostics

- `SIESTA_IDENTITY_UNCONFIRMED`: pass the actual engine executable, not a
  wrapper that merely accepts `--version`.
- `PSEUDOPOTENTIAL_DECLARATION_MISSING` or hash mismatch: repair the external
  manifest; QRAFT never guesses or downloads a replacement.
- `STRUCTURE_CHEMISTRY_REVIEW_REQUIRED`, periodic-charge, D3-periodicity and
  Bader messages require researcher review and are not automatic proof of
  invalid physics.
- `KEYWORD_VALUE_INVALID`, `LATTICE_MATRIX_*`, or `KGRID_MATRIX_*` is a
  deterministic input consistency failure; correct the reported FDF line.
- `DFTU_LINEAR_RESPONSE_MODE_ACTIVE` means potential shifts are perturbations,
  not a productive Hubbard U value.
- `EMBEDDED_PYTHON_SYNTAX_ERROR` or
  `GENERATED_SCHEDULER_SCRIPT_INVALID`: do not submit the generated candidate;
  preserve the diagnostic and regenerate after correction.
- Empty `squeue` without terminal accounting is incomplete evidence, never
  proof of success.
- Scheduler selection blocks mean the observed candidates are absent or
  ambiguous; use evidence-backed human selection rather than hardcoding.
- Standalone package revision errors require transfer of one complete current
  package. Never patch together files from different bundle revisions.
