# QRAFT Core Contracts 1.0

Status: `IMPLEMENTED / INTERNAL ADOPTION IN PROGRESS`

Software version and contract version are independent. QRAFT remains
`0.2.0`; the first public extension boundary is `Core Contracts 1.0`.

## Purpose

The contract kernel defines the data and behavior that may cross module,
plugin, CLI, worker, and future API/UI boundaries. It contains no SIESTA,
Slurm, filesystem, subprocess, project, or cluster implementation.

```text
CLI / API / UI
      |
orchestration services
      |
engine, validator, launcher and postprocessing plugins
      |
QRAFT CORE CONTRACTS 1.0
```

Dependency arrows point inward. Code under `qraft.contracts` must not
import an engine, launcher, cluster profile, reference project, subprocess, or
storage implementation.

## Contract families

| Contract | Stable responsibility |
|---|---|
| `siestaflow.validation-report@1.0` | Findings, evidence class, scope and aggregate decision |
| `siestaflow.artifact-reference@1.0` | Content identity, role, path safety and producer identity |
| `siestaflow.execution-request@1.0` | Engine-neutral task and exact resource placement |
| `siestaflow.execution-evidence@1.0` | Exit evidence, failure class, artifacts and metrics |
| `siestaflow.workflow-event@1.0` | Append-only monitoring/API/UI event |
| `siestaflow.workflow-lock@1.0` | Resolved, topologically ordered scientific DAG |
| `siestaflow.run-lock@1.0` | Hash-bound workflow, execution profile, controller campaign, and task identity |
| `siestaflow.plugin-descriptor@1.0` | Explicit plugin and capability declaration |
| `siestaflow.scientific-intent@1.0` | User-selected recipe, parameters, resources and metadata |
| `siestaflow.workflow-definition@1.0` | Canonical pre-lock workflow document |
| `siestaflow.scientific-artifact@1.0` | Extensible typed scientific artifact with content and provenance hashes |
| `siestaflow.numerical-profile@1.0` | Numerical settings with provisional or approved authority |
| `siestaflow.scientific-approval@1.0` | Human decision bound to exact subject and evidence hashes |

`PASS`, `REVIEW`, `BLOCKED`, and `FAIL` are never replaced by booleans.

## Version compatibility

Contract versions use `MAJOR.MINOR`.

- Same major and newer provider minor is backward compatible.
- A different major is incompatible.
- A provider at `1.0` cannot satisfy a consumer requiring `1.1`.
- Implementation patch versions do not change the wire contract.
- Unknown top-level envelope fields are rejected.
- Optional additions belong under a lowercase namespaced extension key such as
  `org.example.rule-metadata`.

Breaking changes require a new major contract and an explicit adapter or
migration. Existing persisted schemas are not silently reinterpreted.

## Integrity and paths

Contract envelopes are immutable and hash the contract reference, producer,
payload, and extensions using canonical UTF-8 JSON and SHA-256.

Artifacts and execution paths are relative POSIX paths. Absolute paths,
drive-qualified paths, and `..` are rejected at the boundary. Artifact
transfers carry an expected SHA-256 rather than trusting a filename.

A transfer hash identifies the input at the handoff boundary; it does not
require the executable's working copy to remain byte-identical after launch.
Runtimes preserve immutable transfer evidence and register a modified working
copy as a new output artifact with its own digest.

## Validation policy

A finding declares:

- stable rule identifier and version;
- code and message;
- `PASS`, `REVIEW`, `BLOCKED`, or `FAIL`;
- scope: syntax, structure, pseudopotential, numerical, physical, execution,
  provenance, or policy;
- evidence class;
- subject and optional location;
- optional remediation hint and structured evidence.

Evidence classes distinguish mathematical consistency, engine manuals,
pseudopotential metadata, project policy, literature, runtime evidence,
heuristics, and human decisions. A heuristic must not masquerade as a
deterministic error.

The report status is derived from its findings. Callers cannot declare a
passing report that contains a blocking or failing finding.

## Plugin policy

Plugins register explicitly during application composition. Importing a module
must not mutate a global registry.

A plugin declares:

- namespaced plugin ID and implementation version;
- minimum core-contract version;
- namespaced capability IDs;
- capability kind;
- input and output contracts;
- provider and non-authoritative metadata.

The registry rejects duplicate capabilities, missing required methods, unknown
contracts, and plugins requiring a newer core. It can be frozen after startup
so runtime behavior cannot change through late registration.

Future entry-point discovery, configuration loading, and dependency resolution
belong outside the kernel.

## Migration

Current public imports from `qraft.models` remain valid. Their status
enums now originate in the contract kernel and are re-exported for
compatibility.

`qraft.contract_adapters` maps current:

- SIESTA input-validation results to validation reports;
- SIESTA artifact descriptors to artifact references;
- execution requests to the existing launcher specification;
- launcher outcomes to execution evidence.

Existing controllers and packages therefore continue working while services
adopt the new contracts incrementally. No bulk rewrite is required.

## Change policy

Every contract change must include:

1. compatibility classification;
2. contract tests;
3. canonical serialization/hash tests when applicable;
4. dependency-direction test;
5. adapter or migration for existing persisted data;
6. documentation and changelog entry.

No contract version is raised merely because an implementation changes.

Adding a new contract family to the catalog is additive. It does not reinterpret
an existing envelope or change the schema of persisted workflow and run locks.
