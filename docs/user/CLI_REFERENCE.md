# CLI reference

All commands use `python -m qraft.cli [--workspace PATH] [--examples-root PATH]`. Success is exit `0`; invalid input, blocked validation, hash mismatch, or failed evidence is exit `2`. `--dry-run` predicts actions and produces zero filesystem effects.

```text
environment check [--siesta PATH_OR_COMMAND] [--launcher {auto,direct,srun,mpiexec,mpirun}] [--require-slurm] [--working-directory PATH] [--json]
project init PATH --project-id ID --title TITLE --system-id ID --fdf PATH --structure PATH --pseudo-manifest PATH [--dry-run] [--json]
project inspect PATH [--json]
project validate PATH [--json]
project load PATH [--json]
fdf inspect PATH [--json]
input validate PATH [--pseudo-manifest PATH] [--require-pseudos] [--profile PATH] [--engine-version 5.4.2] [--explain] [--json]
input rules [--engine-version 5.4.2] [--json]
pseudo verify MANIFEST [--species SPECIES ...] [--json]
workflow recipes [--json]
workflow recipe RECIPE_ID [--json]
workflow create INTENT --output PATH [--dry-run] [--json]
workflow compose INTENT --output PATH [--dry-run] [--json]
workflow validate DEFINITION [--json]
workflow preflight DEFINITION [--profile PATH] [--pseudo-manifest PATH] [--require-pseudos] [--json]
workflow plan DEFINITION [--json]
workflow graph DEFINITION [--format {text,mermaid,json}]
workflow compile DEFINITION --output PATH [--force] [--dry-run] [--json]
run prepare WORKFLOW_LOCK --source-root PATH --profile EXECUTION_PROFILE --output PATH --run-id ID [--dry-run] [--json]
run candidates --workflow WORKFLOW_LOCK --profile EXECUTION_PROFILE --snapshot SNAPSHOT [--json]
run discover --cluster-id ID --output SNAPSHOT [--json]
run snapshot-import --cluster-id ID --output SNAPSHOT [--sinfo FILE] [--scontrol-partitions FILE] [--scontrol-nodes FILE] [--sacctmgr FILE] [--sjstat FILE] [--observed-at TIMESTAMP] [--json]
run inspect PACKAGE [--json]
run status PACKAGE [--json]
run resume PACKAGE [--previous-job-terminal] [--json]
results dos-pdos PACKAGE --output DIRECTORY [--dry-run] [--json]
results bands PACKAGE --output DIRECTORY [--dry-run] [--json]
results optics PACKAGE --output DIRECTORY [--dry-run] [--json]
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
contains a stable rule code, decision, scope, location where available,
evidence, and a remediation hint. `--profile` adds researcher-declared context
for periodicity, required outputs, and cost-review limits. `--explain` makes
the intent explicit; the human renderer always includes evidence and
remediation. With `--require-pseudos`, a manifest is mandatory and the
pseudopotential files and hashes are checked.

`input rules` lists the immutable built-in rule catalog, its SIESTA version,
manual source, per-rule evidence class, and ruleset SHA-256. The initial
catalog supports SIESTA 5.4.2 only.

`workflow preflight` first compiles and hash-resolves the DAG, then applies the
same input validator to every external artifact declared as
`text/x-siesta-fdf` or `application/x-siesta-fdf`. It is read-only, does not
resolve arbitrary FDF includes, and never authorizes execution.

`remote package` and `remote environment package` generate `PREVIEW` artifacts only and never submit. Environment import returns `0` for review/incomplete and `2` for invalid/failed evidence; only a real complete bundle can become `REMOTE_VERIFIED`.

`remote controller-package` creates a deterministic, self-contained package
for a schema-1 or schema-2 allocation-controller campaign. It never calls
`sbatch`. `campaign worker` is intended to run only inside the generated SLURM
allocation. `campaign progress` and `watch` are read-only.

The `workflow` command family implements compilation plus read-only preflight.
Validation, preflight, planning and graph rendering are read-only.
`workflow compile` writes a canonical, hash-bound
`siestaflow.workflow-lock@1.0` envelope and never authorizes or starts
execution.

`workflow recipes` lists the registered scientific recipes; `workflow recipe`
describes one recipe; `workflow create` materializes an explicit scientific
intent as a canonical definition; and `workflow compose` creates a selected
modular composition. They do not choose scientific values on the researcher's
behalf.

`run prepare` is the strict bridge from a compiled workflow to the persistent
allocation controller. It rechecks workflow-lock integrity, external artifact
size and SHA-256, SIESTA FDF preflight, task placement, allocation fit, and the
external Slurm profile. Exact workflow input destinations are preserved;
artifact edges become parent-to-child transfers. The resulting directory and
ZIP include `workflow.lock.json`, `execution-profile.json`,
`run.lock.json`, the protected inputs, controller runtime, verifier,
`progress.sh`, and `submit.slurm`. It never executes the submit script.

`run inspect` verifies all immutable package files and cross-checks workflow,
profile, run, campaign, and task identities. `run status` adds validated
mutable progress. `run resume` only prints a fail-closed resubmission plan; it
never contacts Slurm or invokes `sbatch`. A noninitial resubmission requires
the researcher to confirm scheduler evidence with `--previous-job-terminal`;
the flag records that assertion but still performs no submission.

`run discover` captures read-only scheduler capability data on a cluster.
`run snapshot-import` combines saved scheduler output, including optional
site-specific capacity evidence such as `sjstat -c`, into a hash-bound
snapshot. `run candidates` ranks snapshot variants deterministically; it is
not a queue-time predictor and never submits work. A confirmed snapshot
candidate or a compatibility-evidence-bound manual resolution is then supplied
to `run prepare`.

`results dos-pdos` is a read-only consumer for a completed, canonical prepared
run that declares exactly one DOS/PDOS-producing task. It first applies the
same immutable package verification as `run inspect`, then requires successful
termination, SCF convergence, manifest-backed DOS/PDOS hashes, and—when the
task consumes a density matrix—evidence that SIESTA read that DM. It writes a
fresh directory containing `total_dos.csv` and `dos_pdos_export.json`. The
manifest binds the table to the workflow lock, run lock, task attempt, raw DOS,
raw PDOS, and any restart transfer. It exports numbers only: it never infers a
gap, peak, orbital assignment, or scientific conclusion.

`results bands` is the equivalent read-only consumer for one completed task
that declares a SIESTA `.bands` artifact. It verifies immutable provenance,
successful SCF completion, and the artifact hash, then writes `bands.csv` in
long form plus `bands_export.json`. The latter records the Fermi energy and the
declared k/energy ranges exactly as written by SIESTA. It does not shift bands,
identify a gap, generate a k-path, or assign physical meaning to the result.

`results optics` verifies one completed `EPSIMG` artifact and exports
`epsimg.csv` plus `optical_export.json`. It preserves energy and epsilon-2
values exactly as written by SIESTA and binds them to the package locks and
artifact hash. It does not infer absorption edges, peaks, dielectric constants,
or any optical property.
