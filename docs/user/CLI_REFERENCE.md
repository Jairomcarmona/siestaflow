# CLI reference

All commands use `python -m siestaflow.cli [--workspace PATH] [--examples-root PATH]`. Success is exit `0`; invalid input, blocked validation, hash mismatch, or failed evidence is exit `2`. `--dry-run` predicts actions and produces zero filesystem effects.

```text
project inspect PATH [--json]
project validate PATH [--json]
project load PATH [--json]
fdf inspect PATH [--json]
input validate PATH [--json]
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

`remote package` and `remote environment package` generate `PREVIEW` artifacts only and never submit. Environment import returns `0` for review/incomplete and `2` for invalid/failed evidence; only a real complete bundle can become `REMOTE_VERIFIED`.

`remote controller-package` creates a deterministic, self-contained package
for a schema-1 or schema-2 allocation-controller campaign. It never calls
`sbatch`. `campaign worker` is intended to run only inside the generated SLURM
allocation. `campaign progress` and `watch` are read-only.

The `workflow` command family implements Phase 1 compilation only. Validation,
planning and graph rendering are read-only. `workflow compile` writes a
canonical, hash-bound `siestaflow.workflow-lock@1.0` envelope and never
authorizes or starts execution.
