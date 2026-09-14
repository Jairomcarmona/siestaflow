# QRAFT CLI UX V2 — design freeze

Status: **FROZEN FOR IMPLEMENTATION**
Scope: CLI presentation, routing, help, compatibility, and output conventions only.
Baseline: branch `feat/qraft-m10-hpc-production-acceptance`, commit `25f4921cf58bb5c2b5a18f539b315a30a242d6d0`.

Normative terms **MUST**, **SHOULD**, and **MAY** have their usual requirements meaning. This design does not change scientific algorithms, convergence or relaxation semantics, runtime/recovery behavior, Slurm/MPI behavior, evidence schemas, or package version.

## 1. Design goals

1. A new user can discover a complete workflow from `qraft` alone.
2. Normal work uses seven task concepts: `init`, `check`, `run`, `status`, `resume`, `results`, and `examples`.
3. Configuration and diagnostic tools remain nearby under `setup` and `inspect`; architecture-facing tools live under `advanced`.
4. Readiness, model consistency, numerical adequacy, and scientific readiness remain independent claims.
5. Every public leaf command has one specification record, copyable examples, actionable next steps, and an explicit human/JSON contract.
6. Existing routes remain callable during migration and preserve their current scientific and execution behavior.
7. No-argument invocation is safe in scripts: it prints orientation and exits; it never starts a prompt.

Non-goals are command implementation, scientific-policy invention, schema redesign, architecture rewrite, or removal of a working route.

## 2. User mental model

The public model is a campaign lifecycle, not QRAFT's internal object model:

```text
create or select target
        |
        v
qraft init -> edit -> qraft check -> qraft run
                                  |
                                  v
                        qraft status / resume
                                  |
                                  v
                            qraft results

qraft examples teaches the same path.
```

A **target** is a path QRAFT already knows how to classify: CampaignSpec, single FDF, workflow definition/lock, prepared run package, or runs root. A command MUST classify by validated content/markers, not filename extension alone. If zero or multiple interpretations remain, it MUST stop and list accepted target types; it MUST NOT guess.

The user need not know `WorkflowCompiler`, `ExecutionSpec`, `ScientificIdentity`, allocation-controller internals, FDF parser stages, or rendering stages. These terms may appear in `advanced` help and detailed evidence, but not as prerequisites for the normal workflow.

## 3. Final command hierarchy

```text
qraft
├── init [PATH]                         CORE
├── check TARGET                        CORE
├── run TARGET                          CORE
├── status [TARGET]                     CORE
├── resume [TARGET]                     CORE
├── results [TARGET]                    CORE
│   └── export {dos-pdos,bands,optics}
├── examples [TOPIC]                    CORE
│   └── --create DIRECTORY              FUTURE, topic-gated (not V2 launch)
├── setup                               GROUPED_PUBLIC
│   ├── env
│   ├── config
│   └── profile {list,show,validate}
├── inspect                             GROUPED_PUBLIC
│   ├── fdf PATH
│   ├── input PATH
│   ├── rules
│   ├── pseudo MANIFEST
│   └── plan TARGET
└── advanced                            ADVANCED
    ├── project {init,inspect,validate,load}
    ├── campaign {create,validate,simulate,render,worker,progress,watch}
    ├── workflow {recipes,recipe,create,compose,validate,preflight,plan,graph,compile}
    ├── scientific {decide,profile}
    ├── execution {prepare,candidates,discover,resources,placement,snapshot-import,inspect,status,resume}
    ├── example {inspect,validate,stage,package,simulate,import-results}
    └── remote {package,m4-package,controller-package,results,environment}
```

`CORE`, `GROUPED_PUBLIC`, `ADVANCED`, `LEGACY_ALIAS`, and `INTERNAL` are registry values, not separate implementations. Core and grouped commands appear on the first help screen. Advanced commands are reachable through `qraft advanced --help`. Legacy aliases are dispatchable and documented in migration help, but omitted from ordinary discovery. Internal routes never appear in public help, completion, examples, or reference docs.

Design choices that differ from the suggested draft:

- `project`, `campaign`, `workflow`, `scientific`, and `remote` move below `advanced`; exposing all five at top level defeats progressive disclosure.
- Current package-management actions under `run` move to `advanced execution`; `run TARGET` is reserved for doing the user's work.
- `plan` becomes `inspect plan`; it is a diagnostic view, not a required lifecycle stage.
- Campaign variant `render` becomes `advanced campaign render`; it materializes implementation-facing inputs and is not normal execution.
- `results` and `examples` are core, but their packaging/import operations remain advanced.

## 4. Core command contracts

Every help page MUST render the headings `SUMMARY`, `USAGE`, `DESCRIPTION`, `EXAMPLES`, `COMMON OPTIONS`, and `NEXT STEPS` in that order. The following records freeze core semantics.

### `qraft init`

| Field | Contract |
|---|---|
| Summary | Create an editable campaign file. |
| Usage | `qraft init [PATH] [--force] [--json]` |
| Description | Writes the current schema-valid minimal CampaignSpec template. Defaults to `campaign.yaml`. It does not choose scientific parameters. |
| Examples | `qraft init`<br>`qraft init campaign.yaml --json` |
| Common options | `--force` permits an explicit overwrite; `--json` emits only the result object. |
| Next steps | `Edit campaign.yaml, then run: qraft check campaign.yaml` |

### `qraft check`

| Field | Contract |
|---|---|
| Summary | Decide whether a target is ready to run. |
| Usage | `qraft check TARGET [execution overrides] [--json]` |
| Description | Runs the applicable existing structural, scientific-consistency, numerical-evidence, and execution-environment checks; reports each dimension independently. It never executes SIESTA or submits work. |
| Examples | `qraft check campaign.yaml`<br>`qraft check campaign.yaml --json` |
| Common options | Current profile/resource/pseudo overrides remain available where accepted; `--json` is machine-only. |
| Next steps | Ready: `qraft run campaign.yaml`; blocked: the emitted fix followed by the same `qraft check` command. |

The complete semantic contract is in section 5.

### `qraft run`

| Field | Contract |
|---|---|
| Summary | Run a checked campaign or calculation. |
| Usage | `qraft run TARGET [execution overrides] [--no-input] [--json]` |
| Description | Dispatches a CampaignSpec or FDF through its existing planner, preflight, launcher, persistence, and evidence path. It MUST perform the same fail-closed preflight as today. Workflow-lock packaging remains `qraft advanced execution prepare`; QRAFT never adds implicit `sbatch`. |
| Examples | `qraft run campaign.yaml --profile local`<br>`qraft run calc.fdf --profile local --json` |
| Common options | Existing profile, launcher, resource, pseudo, run-root, and force-new-attempt options; global output/input flags. |
| Next steps | `qraft status` |

`qraft run prepare ...` remains a legacy route to prepared-package creation and MUST NOT be reinterpreted as `run TARGET`.

### `qraft status`

| Field | Contract |
|---|---|
| Summary | Show progress and the next available action. |
| Usage | `qraft status [TARGET] [--json]` |
| Description | Reads authoritative state/evidence only. With no target, uses the current/default runs root. Target classification delegates to today's single-FDF status, package status, or campaign progress readers without changing them. |
| Examples | `qraft status`<br>`qraft status .qraft-runs --json` |
| Common options | `--runs-root` remains a deprecated spelling for selecting the target; `--json` preserves the complete underlying payload. |
| Next steps | Terminal success: `qraft results`; interrupted/recoverable: `qraft resume`; failure: show the evidence path and remediation. |

### `qraft resume`

| Field | Contract |
|---|---|
| Summary | Continue an interrupted target using its saved recovery contract. |
| Usage | `qraft resume [TARGET] [execution overrides] [--no-input] [--json]` |
| Description | For single-FDF/CampaignSpec sessions, invokes existing idempotent run/recovery semantics. For prepared Slurm packages, preserves today's fail-closed behavior: validate state and print a resubmission plan; never call `sbatch`. The human output MUST state which behavior applies before any action. |
| Examples | `qraft resume`<br>`qraft resume .qraft-runs --json` |
| Common options | Existing resume overrides and `--previous-job-terminal` when the classified target is a prepared package. |
| Next steps | `qraft status TARGET` or the exact externally executed resubmission command when package evidence permits it. |

### `qraft results`

| Field | Contract |
|---|---|
| Summary | Find verified outputs and export supported result tables. |
| Usage | `qraft results [TARGET] [--json]` or `qraft results export TYPE PACKAGE --output DIRECTORY [--dry-run] [--json]` |
| Description | The default form inventories authoritative evidence, human report, and available exporters without scientific interpretation. Export delegates unchanged to existing DOS/PDOS, bands, and optics exporters. |
| Examples | `qraft results .qraft-runs`<br>`qraft results export bands prepared-run --output exported-bands --dry-run` |
| Common options | `--dry-run` for export, `--json` for a single machine payload. |
| Next steps | Show the evidence/export paths; no scientific conclusion is inferred. |

Legacy `qraft results dos-pdos|bands|optics ...` remains dispatchable and maps one-to-one to `results export`.

### `qraft examples`

| Field | Contract |
|---|---|
| Summary | Learn QRAFT through checked, copyable workflows. |
| Usage | V2 launch: `qraft examples [TOPIC] [--json]`; future extension: `qraft examples TOPIC --create DIRECTORY`. |
| Description | Lists topics or prints a short explanation followed by commands using the same public CLI. A future `--create` is allowed only for a topic whose registry record contains a materializer and runnable asset set. |
| Examples | `qraft examples`<br>`qraft examples minimal` |
| Common options | `--json` returns topic metadata. When `--create` ships, it MUST refuse unavailable/non-runnable topics without partial writes. |
| Next steps | The final command in every topic is a valid core command, normally `qraft check ...` or `qraft run ...`. |

## 5. `qraft check` contract

### 5.1 Meaning and status model

`qraft check` answers **“Is this target ready to run under its declared contract?”** It is not a rename of `validate`. It aggregates existing checks and makes absence of evidence explicit.

Each dimension has `PASS`, `REVIEW`, `BLOCKED`, `NOT_APPLICABLE`, or `NOT_EVALUATED` plus stable findings. `NOT_EVALUATED` is never silently promoted to `PASS`.

| Dimension | Existing authority used | Claim and limit |
|---|---|---|
| INPUT / MODEL | CampaignSpec loading/invariants; FDF parser and input validator; pseudo manifest verification when declared/required; project-package validation; workflow compilation and workflow preflight, as applicable | Files are readable, structurally valid, mutually consistent under implemented rules, and required hashes/includes are available. Unknown labels and governed-but-undeclared values retain existing review findings. No claim of physical correctness. |
| SCIENTIFIC CONSISTENCY | Existing `ScientificIdentity` comparisons; campaign protocol preflight; inherited-evidence hash/identity checks; workflow graph/artifact contracts; recipe-specific validators already registered | Declared scientific inputs and handoffs are internally compatible under implemented contracts. QRAFT does not choose XC, U, pseudo suitability, grids, tolerances, spin, or geometry acceptance. |
| NUMERICAL EVIDENCE | Existing convergence observations/reports, convergence evaluators, hash-bound decisions, and approved profiles, but only when referenced by the target | Evidence is valid and its current status is reported (`READY_FOR_HUMAN_REVIEW`, review required, no satisfying candidate, approved/rejected, etc.). A new campaign with no results is normally `NOT_EVALUATED`, not inadequate. No new criterion is invented. |
| EXECUTION ENVIRONMENT | Existing resolution/profile validation and environment inspector: executable, launcher, scheduler, runtime compatibility, workspace/config access, and requested resources where current validators support them | The resolved execution path is available and internally compatible. A remote preview or historical snapshot is not presented as live authorization. `check` never submits. |
| OVERALL READINESS | Deterministic reduction of the four dimensions and target-declared gates | Separately reports `can_run`, `model_consistent`, `numerically_adequate`, and `scientifically_ready`; it does not collapse them into one scientific claim. |

The overall object MUST contain:

```json
{
  "status": "READY|REVIEW_REQUIRED|BLOCKED",
  "can_run": true,
  "model_consistent": true,
  "numerically_adequate": null,
  "scientifically_ready": null,
  "dimensions": {},
  "next_command": "qraft run campaign.yaml"
}
```

Booleans are facts supported by the checks; `null` means not applicable or not evaluated and is accompanied by a reason. Reduction rules are:

1. Any failed mandatory input/model or environment gate makes `can_run=false` and overall `BLOCKED`.
2. An unresolved **target-declared prerequisite** (for example, required approved numerical evidence) makes overall `REVIEW_REQUIRED` or `BLOCKED` according to its existing authority, even if the executable is available.
3. Missing pre-run numerical results that the campaign is intended to produce are `NOT_EVALUATED` and do not by themselves block execution.
4. Non-blocking existing `REVIEW` findings produce `REVIEW_REQUIRED` only when the target marks that review as a prerequisite; otherwise the overall status may be `READY` with warnings.
5. Exit `0` means `READY`; exit `2` means `BLOCKED` or required review. The JSON/text finding states which. This retains a simple readiness predicate for automation.

Human output order is fixed:

```text
QRAFT CHECK — campaign.yaml

INPUT / MODEL            PASS
SCIENTIFIC CONSISTENCY   PASS
NUMERICAL EVIDENCE       NOT EVALUATED — produced by this campaign
EXECUTION ENVIRONMENT    PASS

OVERALL READINESS        READY
CAN RUN                  YES
MODEL CONSISTENT         YES
NUMERICALLY ADEQUATE     NOT EVALUATED
SCIENTIFICALLY READY     NOT CLAIMED

Next: qraft run campaign.yaml
```

Operations that remain advanced and are not automatically broadened into `check`: raw FDF AST inspection, validation-rule catalog listing, workflow graph rendering, scheduler snapshot discovery/import, candidate ranking, live placement selection, remote packaging/import, result export, scientific decision creation, and example packaging/simulation. `check` may consume their already-produced artifacts where current code supports it.

## 6. Help layout

`qraft` and `qraft --help` MUST print the same orientation to stdout and exit `0`. Neither starts the legacy REPL.

```text
QRAFT — run reproducible scientific campaigns

GET STARTED
  init [PATH]       Create an editable campaign file
  check TARGET      Check whether a target is ready to run
  run TARGET        Run a checked campaign or calculation

MONITOR / CONTINUE
  status [TARGET]   Show progress and the next available action
  resume [TARGET]   Continue using saved recovery state

RESULTS
  results [TARGET]  Find verified outputs and export supported tables

LEARN
  examples [TOPIC]  Show copyable workflows

Complete workflow:
  qraft init campaign.yaml
  # edit campaign.yaml
  qraft check campaign.yaml
  qraft run campaign.yaml
  qraft status
  qraft results

Setup and diagnostics:
  qraft setup --help
  qraft inspect --help

Advanced workflows and compatibility:
  qraft advanced --help
  qraft help migration

Use 'qraft COMMAND --help' for examples and options.
```

Help rules:

- The first screen MUST NOT enumerate advanced or legacy leaf commands.
- `qraft setup --help`, `qraft inspect --help`, and `qraft advanced --help` enumerate their own children.
- Legacy invocation help begins with `DEPRECATED` and shows the canonical equivalent, compatibility window, and unchanged-behavior statement.
- Usage errors print compact command help to stderr; explicit `--help` prints to stdout.
- Options are grouped as `Target`, `Execution`, `Output`, and `Safety` where present; internal class names are excluded from summaries.

Example frozen command help:

```text
SUMMARY
  Check whether a target is ready to run.

USAGE
  qraft check TARGET [OPTIONS]

DESCRIPTION
  Evaluates input/model, scientific consistency, numerical evidence, and
  execution environment independently. Does not run SIESTA or submit work.

EXAMPLES
  qraft check campaign.yaml
  qraft check campaign.yaml --json

COMMON OPTIONS
  --profile NAME|PATH   Select an execution profile
  --json                Emit one JSON value and no human text
  --no-color            Disable ANSI styling

NEXT STEPS
  Ready:   qraft run campaign.yaml
  Blocked: apply the reported fix, then rerun qraft check campaign.yaml
```

## 7. Examples policy

Topics are registry records, not prose-only aliases. A topic declares title, maturity, source assets, rendered commands, whether execution is synthetic/real, required external software, and optional materializer.

| Topic | V2 freeze | Basis |
|---|---|---|
| `minimal` | Supported at V2 launch | Existing `examples/generic/minimal_siesta_smoke`; clearly label current `examples run` behavior as synthetic. |
| `convergence` | Supported at V2 launch | Existing minimal mesh series, CampaignSpec convergence protocol, and birnessite reference campaign. Commands MUST distinguish synthetic demonstration from real SIESTA execution. |
| `relaxation` | Documentation topic at V2 launch; no `--create` until curated assets ship | Existing fixed-cell relaxation capability and recipe support the explanation, but there is no standalone curated example package in the current registry. |
| `slurm` | Planned; not advertised as available until curated assets and a safe materializer ship | Execution profiles, discovery, placement, preparation, and remote bundles exist, but no single portable runnable Slurm example can promise site compatibility. |
| `resume` | Documentation topic at V2 launch; no `--create` initially | Existing single-FDF and prepared-package recovery contracts exist; examples must explain their different side effects. |

`qraft examples` lists only installed/available topics first, then `COMING LATER`. `qraft examples TOPIC` is read-only. A future `--create DIRECTORY` MUST create a new directory atomically, refuse overwrite unless an explicit safety option is designed, include every referenced asset, and end with a successful offline structural `qraft check` where external executables are not required. Generated README commands come from the command specification, preventing drift.

Advanced example-management routes retain exact current capabilities:

| Canonical route | Copyable repository example | Next step |
|---|---|---|
| `qraft advanced example inspect NAME` | `qraft advanced example inspect generic/minimal_siesta_smoke --json` | validate the same name |
| `... validate NAME` | `qraft advanced example validate generic/minimal_siesta_smoke --json` | inspect or simulate |
| `... stage NAME` | `qraft advanced example stage generic/minimal_siesta_smoke --pseudo-root pseudos --output staged-minimal --policy copy --dry-run` | rerun without dry-run after review |
| `... package NAME` | `qraft advanced example package generic/minimal_siesta_smoke --output example-bundles --dry-run` | review manifest |
| `... simulate NAME` | `qraft advanced example simulate generic/minimal_siesta_smoke --campaign-id smoke --json` | inspect synthetic evidence |
| `... import-results BUNDLE` | `qraft advanced example import-results results-bundle.zip --output imported-results --dry-run` | verify, then remove dry-run |

## 8. Interactive-mode decision

V2 has **no public REPL**. `qraft` with no arguments prints the top-level help in section 6 and exits `0`.

The current `qraft>` shell is an independent command language (`fdf`, `set`, `np`, `dag`, `paths`, and others) and conflicts with the single-specification requirement. It remains internal for one compatibility cycle only so implementation can reuse/test its application adapter; it is not exposed as `qraft shell` or `qraft interactive`.

A future guided UI MAY be added as `qraft interactive` only if every choice selects a canonical command-spec record, shows the exact equivalent command before execution, and supports a confirm/cancel boundary. It MUST introduce no session-only syntax and MUST never be required for automation.

## 9. Output and error conventions

### 9.1 Streams, formats, and input

| Concern | Contract |
|---|---|
| Normal output | Human-readable result on stdout. Stable for meaning, not for line-by-line parsing. |
| `--json` | Exactly one valid JSON value on stdout; no headings, progress, warnings, or ANSI codes. Existing evidence JSON schemas remain unchanged and may be embedded/referenced rather than rewritten. |
| stdout | Requested result only. |
| stderr | Diagnostics, progress, deprecation notices, warnings, and errors only. In `--json` mode, diagnostics are still non-JSON stderr and MUST NOT corrupt stdout. |
| `--no-input` | Global. Refuses any prompt and fails with an actionable error. Core automation examples SHOULD include it when a future operation could prompt. Current commands remain non-interactive by default. |
| `--no-color` | Global. Disables ANSI styling. |
| `NO_COLOR` | Any present value disables color unless a future explicit `--color` override is supplied. JSON never uses color. Non-TTY stdout defaults to no color. |
| `--dry-run` | Zero filesystem effects where currently promised; never generalized to commands whose backend cannot guarantee this. |

Exit codes freeze existing meanings and add no scientific shortcut: `0` successful/ready, `2` expected invalid input or readiness block, `3` execution completed with non-passing technical validation (existing single-run behavior), and `1` unexpected internal failure. Expected user-correctable failures MUST NOT show a traceback. An opt-in diagnostic mode may include one on stderr for developers.

### 9.2 Error shape

Human errors use four fields and a stable error code:

```text
BLOCKED [PSEUDOPOTENTIAL_NOT_FOUND]: pseudopotential not found

Expected:
  pseudos/O.psml

Why:
  the manifest entry for O resolves to a missing file

Fix:
  add the file or correct the path in pseudos/manifest.yaml

Then run:
  qraft check campaign.yaml
```

JSON-capable errors use one object on stdout only when `--json` was requested:

```json
{
  "status": "BLOCKED",
  "error": {
    "code": "PSEUDOPOTENTIAL_NOT_FOUND",
    "message": "pseudopotential not found",
    "why": "the manifest entry for O resolves to a missing file",
    "fix": "add the file or correct the manifest path",
    "next_command": "qraft check campaign.yaml"
  }
}
```

Unexpected exceptions return `1`, print a short incident message on stderr, and preserve traceback access only through explicit developer diagnostics.

## 10. Current → V2 migration table

No listed route disappears in the first V2 compatibility release. “Alias” below means argument-preserving delegation to the canonical handler; “frozen legacy” means the old handler remains because delegation would change semantics.

| Current top-level | V2 class | Treatment | Canonical V2 route and compatibility rule |
|---|---|---|---|
| `init` | CORE | KEEP | `qraft init`; only its suggested next command changes from `validate` to `check`. |
| `env` | LEGACY_ALIAS | MOVE + ALIAS | `qraft setup env`; preserve options/output during window. |
| `config` | LEGACY_ALIAS | MOVE + ALIAS | `qraft setup config`; preserve resolution precedence. |
| `profile` | LEGACY_ALIAS | MOVE + ALIAS | `qraft setup profile`; preserve `list/show/validate`. |
| `validate` | LEGACY_ALIAS | DEPRECATE, frozen legacy | Continue current FDF/CampaignSpec validation exactly. Do **not** alias to `check`. Migration hint: `qraft check TARGET`; advanced one-layer replacements are `inspect input` or `advanced campaign validate`. |
| `plan` | LEGACY_ALIAS | MOVE + ALIAS | `qraft inspect plan TARGET`; same non-submitting planner. |
| `render` | LEGACY_ALIAS | MOVE + ALIAS | `qraft advanced campaign render TARGET`; same CampaignSpec variant materialization. |
| `run` | CORE | KEEP + SPLIT | `qraft run TARGET` keeps current FDF/CampaignSpec execution. Existing action words `prepare/candidates/discover/resources/placement/snapshot-import/inspect/status/resume` delegate unchanged to `qraft advanced execution ACTION`. |
| `status` | CORE | KEEP | Expanded target classification, delegating to existing readers. No evidence semantics change. |
| `resume` | CORE | KEEP | Expanded target classification; single-run recovery and package resubmission-plan semantics remain distinct and explicit. |
| `project` | LEGACY_ALIAS | MOVE + ALIAS | `qraft advanced project`. |
| `fdf` | LEGACY_ALIAS | MOVE + ALIAS | `qraft inspect fdf`; current `fdf inspect PATH` accepted during window. |
| `input` | LEGACY_ALIAS | MOVE + ALIAS | `qraft inspect input PATH`; `input rules` becomes `qraft inspect rules`. |
| `pseudo` | LEGACY_ALIAS | MOVE + ALIAS | `qraft inspect pseudo MANIFEST`; current `pseudo verify` accepted. |
| `campaign` | LEGACY_ALIAS | MOVE + ALIAS | `qraft advanced campaign`; `campaign status/progress` may recommend core `status` but retains its handler. |
| `workflow` | LEGACY_ALIAS | MOVE + ALIAS | `qraft advanced workflow`; all leaf actions unchanged. |
| `scientific` | LEGACY_ALIAS | MOVE + ALIAS | `qraft advanced scientific`; decisions/approved-profile semantics unchanged. |
| `results` | CORE | KEEP | Default inventory added. Existing `dos-pdos/bands/optics` delegate to `results export TYPE`. |
| `examples` | CORE | KEEP + SPLIT | Topic learning is default. Existing management actions delegate to `qraft advanced example`; existing synthetic `run` is named `simulate` canonically. |
| `remote` | LEGACY_ALIAS | MOVE + ALIAS | `qraft advanced remote`; preview/non-submitting guarantees unchanged. |
| `environment` | LEGACY_ALIAS | DEPRECATE | Preserve historical `environment check` envelope and exit behavior; recommend `qraft setup env`. Do not silently replace its JSON envelope. |
| `_fdf-run` | INTERNAL | INTERNAL | Remains a hidden adapter only while required by dispatch/output compatibility. Never document or emit it. |

New namespace records are `setup` (GROUPED_PUBLIC), `inspect` (GROUPED_PUBLIC), and `advanced` (ADVANCED).

## 11. Compatibility and deprecation policy

1. V2 implementation release N introduces canonical routes and warnings while every current route remains functional.
2. Legacy human invocations write one deprecation notice to stderr. `--json` keeps stdout pure and places the notice on stderr.
3. Aliases pass the original parsed values to the same application/service method. They MUST NOT translate scientific values, defaults, execution placement, recovery state, evidence, or exit status.
4. Frozen-legacy routes (`validate`, `environment check`) keep their current handler/output contract until separately versioned migration is approved.
5. Removal requires at least one documented minor-release compatibility window, usage tests for both spellings, a changelog entry, and an owner-approved major-version boundary. No removal is authorized by this design.
6. Generated evidence records the canonical user-facing invocation while retaining provenance sufficient to audit a legacy invocation; `_fdf-run` is never exposed.
7. Ambiguous `run` parsing remains explicit: known legacy action words select legacy advanced execution; a path selects core run; an ambiguous path/action collision fails and explains `--` or the canonical advanced route.

## 12. Command specification model

`CommandSurface` evolves into an immutable command tree that is the sole presentation authority. Parser handlers remain code, but names, hierarchy, discovery, help, examples, aliases, and capabilities are not duplicated.

Minimum command metadata:

```text
id                         stable namespaced identifier
path                       canonical token tuple
parent_id                  hierarchy edge
classification             CORE | GROUPED_PUBLIC | ADVANCED | LEGACY_ALIAS | INTERNAL
visibility                 PRIMARY | GROUPED | ADVANCED | MIGRATION | HIDDEN
order                      deterministic display order
summary                    one line
description                user-task description and semantic limits
usage                      canonical syntax
examples[]                 argv + purpose + fixture/topic requirements
options[]                  shared option-spec references plus command options
aliases[]                  legacy token tuples, since/until, warning, behavior mode
next_steps[]               condition + canonical command template
target_types[]             accepted validated content kinds
handler_id                 dispatch binding; aliases share or explicitly freeze it
json_supported             boolean and output/evidence contract reference
interactive_supported      false in V2
input_policy               NEVER_PROMPT | OPTIONAL_CONFIRMATION
side_effect                READ_ONLY | WRITE_LOCAL | EXECUTE | PACKAGE_ONLY
exit_codes                 status-to-code mapping
deprecation                optional lifecycle record
```

Option specifications are also authoritative records (`flags`, destination, type/choices, default, help, category, environment support). Command examples MUST be executed in tests against declared fixtures or marked `display_only` with a reason; public leaf commands cannot ship with zero executable examples.

The specification drives:

- parser construction and collision validation;
- top-level, group, command, and migration help;
- shell completion;
- `qraft examples` command rendering;
- CLI/reference documentation generation;
- public-surface, alias-equivalence, stdout/stderr, JSON-purity, and example tests.

CI MUST fail on duplicate canonical/alias paths, visible INTERNAL commands, missing required help fields, public commands without examples/next steps, unsupported `--json` claims, or documentation drift. Free-form README command lists are generated regions or links, never a second registry.

### Advanced command example coverage

The following existing leaf groups remain public through `advanced`; each spec record receives at least the shown executable command pattern and the standard help sections. Paths name repository-supported fixtures where available; commands that write use `--dry-run` unless the existing operation has no writes.

| Canonical family | Leaf coverage and examples |
|---|---|
| `advanced project` | `validate examples/generic/minimal_siesta_smoke --json`; `inspect` and `load` use the same package; `init` uses its explicit FDF/structure/manifest inputs and `--dry-run`. |
| `advanced campaign` | `validate examples/generic/minimal_siesta_smoke/campaigns/smoke.yaml --dry-run --json`; `simulate` uses that campaign; `create` uses the minimal project and `--dry-run`; `render` uses `examples/generic/minimal_siesta_smoke/campaigns/mesh_series.yaml`; `worker/progress/watch` use a generated controller package fixture and are labeled operator-only. |
| `advanced workflow` | `validate examples/workflows/restart_chain_compile_only/workflow.json --json`; `plan` and `graph` use the same definition; `compile ... --output workflow.lock.json --dry-run`; `recipes` is argument-free; `recipe` uses an ID returned by `recipes`; `create/compose/preflight` use versioned intent/FDF fixtures declared in their spec records. |
| `advanced scientific` | `decide` and `profile` use a versioned convergence-report fixture plus matching approval fixture. Help states that `READY_FOR_HUMAN_REVIEW` is not approval. |
| `advanced execution` | `inspect/status/resume` use `tests/fixtures/phase3/yoltla_job_781100`; `prepare` uses its workflow lock/profile with `--dry-run`; snapshot/candidate operations use versioned scheduler fixtures; `resources/placement/discover` are labeled live-cluster commands and examples include `--json` without claiming submission. |
| `advanced remote` | `controller-package` and `package` use repository campaign fixtures with `--dry-run`; result/environment imports use immutable bundle fixtures with `--dry-run`; help repeats `PREVIEW`, `REMOTE_EVIDENCE_PENDING`, and non-submitting limits. |

Before implementation closes, missing intent, approval, scheduler, controller-package, and bundle fixtures MUST be added as test fixtures or those leaf records remain advanced-but-unreleased. Placeholder paths such as `/path/to/...` are forbidden in shipped help.

## 13. Acceptance criteria

| ID | Verifiable V2 criterion |
|---|---|
| A | `qraft` and `qraft --help` show the full `init → check → run → status → results` example and exit without prompting. |
| B | First-screen task vocabulary is the seven core commands; setup/inspection are two secondary groups, not twenty peers. |
| C | `qraft advanced --help` discovers every supported advanced family; legacy help shows canonical replacements. |
| D | `check` emits all five dimensions, independent claim fields, deterministic reduction, and no invented scientific check. |
| E | Every released public leaf spec has all six help sections and at least one fixture-backed, CI-executed example. |
| F | Golden tests prove human output readability, JSON-only stdout, diagnostic stderr, `--no-input`, `--no-color`, and `NO_COLOR`. |
| G | Every current top-level route in section 10 has an alias/frozen/internal test and no silent semantic change. |
| H | Parser, help, examples, completion, tests, and generated CLI reference consume the same command specification. |
| I | Scientific/runtime/evidence regression suites are unchanged except invocation-path fixtures; no algorithm or schema diff is required. |
| J | Expected user errors contain code, what/why/fix/next command and no traceback. |

## 14. Implementation phases

1. **Specification foundation.** Expand `CommandSurface` into the immutable tree, model shared options/aliases, validate collisions, and generate existing parser/help without behavior changes.
2. **Output foundation.** Add global output/input/color policy and structured expected-error rendering; lock stream and exit-code tests before route movement.
3. **Canonical grouping.** Introduce `setup`, `inspect`, and `advanced`; bind them to current handlers. Add legacy equivalence tests and deprecation diagnostics.
4. **Core orientation.** Replace no-argument REPL entry with frozen top-level help; update `init` next step; add target classifier shared by `check/status/resume/results`.
5. **Readiness aggregation.** Implement `check` as orchestration over current validators/evidence readers/environment inspector, with dimension fixtures and fail-closed reduction. Do not change those authorities.
6. **Core status/results/examples.** Add read-only target views, result inventory/export routing, topic registry, and fixture-backed learning output.
7. **Documentation generation and migration.** Generate CLI reference/help snapshots, update guides, retain compatibility routes, and run full scientific/runtime regression suites.
8. **Later cleanup.** Only at an owner-approved version boundary and after telemetry/user feedback may deprecated aliases or the internal REPL be considered for removal.

## Freeze verdict and owner decisions

**CLI_UX_V2_DESIGN_READY**

No project-owner decision blocks implementation. This freeze explicitly decides the two previously ambiguous product points: no-argument invocation becomes orientation rather than a REPL, and `validate` remains frozen legacy behavior rather than an alias for the broader `check` contract. Any future removal of deprecated routes, addition of a public guided interactive mode, or relaxation of readiness gates requires a separate owner decision; none is required to begin V2 implementation.
