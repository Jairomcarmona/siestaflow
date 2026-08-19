# QRAFT Architecture Contracts v1

Status: **normative for v1 runtime work**.

QRAFT is simple when possible, explicit when necessary, strict where
correctness requires it, and inspectable everywhere.

## ScientificIdentity

`ScientificIdentity` is the content identity of the effective FDF, geometry,
species mapping, pseudopotentials, charge/spin, basis, XC, k-grid,
`MeshCutoff`, DFT+U/projectors, and every included scientific file. A change to
any of those inputs creates a new identity. Results from a different identity
MUST NOT be reused as equivalent. A legitimate change creates a new identity;
it does not by itself block a campaign.

Hashes that protect scientific inputs, required recovery artifacts, or result
manifests are blocking on mismatch. Documentation, branding, regenerable
reports, and non-critical metadata hashes are informative warnings only.

## ExecutionSpec

`ExecutionSpec` is separate from `ScientificIdentity` and records partition,
nodes, MPI ranks, CPUs per rank, memory, launcher, SIESTA executable, walltime,
launcher arguments, and execution environment. Resolution order is:

1. HPC profile defaults;
2. project or campaign configuration;
3. recipe;
4. CLI override.

Changing partition or MPI ranks creates a new `ExecutionSpec` but MUST NOT
change `ScientificIdentity` or rebuild the scientific DAG. Cluster resources
MUST NOT be hardcoded in scientific DAG nodes. The resolved spec MUST be
inspectable before execution.

## Attempt

Every launch has an immutable `node_id` and `attempt_id`, binds exact scientific
and execution fingerprints, and records timestamps, stdout, stderr, exit code,
artifacts, and technical result. Attempt directories and final manifests MUST
be created exclusively and MUST NOT overwrite prior attempts.

## NodeResult

`NodeResult` keeps three independent dimensions:

- `execution_state` — what happened to the process;
- `technical_validation` — whether exit status, parser evidence, stderr, and
  required artifacts prove a valid engine result;
- `scientific_decision` — explicit scientific acceptance or rejection.

Exit code zero or process completion alone MUST NOT imply technical validity or
scientific acceptance.

## DAG and resources

The DAG expresses scientific and technical dependencies. The minimal FDF
vertical is `validate_input -> run_siesta -> technical_validate`. Resource
overrides flow through `ExecutionSpec` to the resource scheduler and launcher.
The scheduler/controller recalculates placement and concurrency from the final
execution specification without modifying the scientific DAG.

## Events, state, and recovery

The controller is the single writer of global state. Workers or launchers write
attempt evidence only. Recovery is **at-least-once execution plus immutable
attempts plus idempotent commit/recovery**; QRAFT does not promise exactly-once
execution. A technically validated attempt bound to the same
`ScientificIdentity` is reusable after its artifact hashes are verified. An
incomplete attempt may produce a new attempt and is never overwritten.

Automatic retry is bounded and only valid for transient node, MPI, launcher,
allocation, or safely restartable walltime failures. Invalid FDF, missing
pseudopotentials, SCF non-convergence, NaN/numerical instability, scientific
rejection, or unknown parser state MUST NOT be blindly retried. Changing a
scientific or numerical parameter creates a new variant and identity, not a
retry.

## EngineAdapter boundary

Engine-neutral identities, execution specifications, attempts, and node
results live under `qraft.core`. SIESTA parsing, FDF semantics, pseudo discovery,
and output classification live under `qraft.engines.siesta`. Research protocols
compose both under `qraft.protocols`. Existing modules may migrate toward this
boundary incrementally; a mass refactor is not required for v1.

## Minimal executable interface

```text
qraft plan calc.fdf --np 100 --partition tt2d-100p
qraft run calc.fdf --np 100 --partition tt2d-100p
```

`plan` is read-only and exposes the FDF, engine, partition, nodes, MPI ranks,
launcher, configuration provenance, scientific identity, and generated DAG.
`run` executes inside the selected environment and persists immutable evidence.
