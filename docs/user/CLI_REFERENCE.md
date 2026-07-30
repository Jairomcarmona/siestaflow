# CLI reference

All commands use `python -m siestaflow.cli [--workspace PATH] [--examples-root PATH]`. Success is exit `0`; invalid input, blocked validation, hash mismatch, or failed evidence is exit `2`. `--dry-run` predicts actions and produces zero filesystem effects.

```text
environment check [--siesta PATH_OR_COMMAND] [--launcher {auto,direct,srun,mpiexec,mpirun}] [--require-slurm] [--working-directory PATH] [--json]
project init PATH --project-id ID --title TITLE --system-id ID --fdf PATH --structure PATH --pseudo-manifest PATH [--dry-run] [--json]
project inspect PATH [--json]
project validate PATH [--json]
project load PATH [--json]
fdf inspect PATH [--json]
input validate PATH [--pseudo-manifest PATH] [--require-pseudos] [--json]
pseudo verify MANIFEST [--species SPECIES ...] [--json]
workflow validate DEFINITION [--json]
workflow plan DEFINITION [--json]
workflow graph DEFINITION [--format {text,mermaid,json}]
workflow compile DEFINITION --output PATH [--force] [--dry-run] [--json]
campaign create --project PATH --campaign-id ID [--dry-run] [--json]
campaign validate CAMPAIGN [--dry-run] [--json]
campaign simulate CAMPAIGN [--dry-run] [--json]
campaign status CAMPAIGN [--dry-run] [--json]
campaign worker CAMPAIGN_FILE [--root PATH] [--json]
campaign progress PACKAGE_OR_CAMPAIGN_FILE [--json]
campaign watch PACKAGE_OR_CAMPAIGN_FILE [--interval SECONDS] [--iterations N] [--json]
examples list [--json]
examples inspect EXAMPLE [--json]
examples validate EXAMPLE [--json]
examples stage EXAMPLE --pseudo-root PATH --output PATH --policy {copy,link} [--dry-run] [--json]
examples package EXAMPLE --output PATH [--dry-run] [--json]
examples run EXAMPLE --campaign-id ID [--json]
examples results import BUNDLE --output PATH [--campaign-id ID] [--dry-run] [--json]
remote package CAMPAIGN [--output PATH] [--dry-run] [--json]
remote controller-package CAMPAIGN_FILE --output PATH [--dry-run] [--json]
remote results import BUNDLE [--campaign-id ID] [--output PATH] [--dry-run] [--json]
remote environment package [--output PATH] [--pseudo-manifest PATH] [--status-labels PATH] [--dry-run] [--json]
remote environment import BUNDLE [--output PATH] [--dry-run] [--json]
```

`environment check` is read-only. It identifies Python, the requested SIESTA
executable, MPI capability, the selected launcher, optional SLURM clients, and
workspace accessibility. It neither submits jobs nor claims scientific
validity.

`project init` creates a preparation-only ProjectPackage from explicit existing
files. It preserves their bytes, validates the FDF and species-to-manifest
coverage, writes an idempotency lock, and refuses conflicting reuse of the
destination. It does not select functionals, Hubbard U, spin, grids,
pseudopotentials, resources, or convergence thresholds.

`input validate` emits the common explainable validation contract. Each finding
contains a stable rule code, severity, scope, location where available,
evidence, and a remediation hint. With `--require-pseudos`, a manifest is
mandatory and the pseudopotential files and hashes are checked.

`remote package` and `remote environment package` generate `PREVIEW` artifacts only and never submit. Environment import returns `0` for review/incomplete and `2` for invalid/failed evidence; only a real complete bundle can become `REMOTE_VERIFIED`.

`remote controller-package` creates a deterministic, self-contained package
for a schema-1 or schema-2 allocation-controller campaign. It never calls
`sbatch`. `campaign worker` is intended to run only inside the generated SLURM
allocation. `campaign progress` and `watch` are read-only.

The `workflow` command family implements Phase 1 compilation only. Validation,
planning and graph rendering are read-only. `workflow compile` writes a
canonical, hash-bound `siestaflow.workflow-lock@1.0` envelope and never
authorizes or starts execution.
