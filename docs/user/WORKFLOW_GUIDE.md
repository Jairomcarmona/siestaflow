# Workflow definitions

QRAFT workflow schema 1.0 describes a scientific DAG without executing
it. The Phase 1 compiler validates the definition, resolves artifact
dependencies, orders tasks, hashes external inputs, and produces an immutable
`workflow.lock.json`.

## Minimal structure

```yaml
schema_version: "1.0"
workflow_id: relaxation-chain
project_id: thesis-project
description: Parent relaxation followed by a restart
metadata: {}
tasks:
  - task_id: parent
    kind: calculation
    capability: siestaflow.engine.siesta
    inputs:
      - name: fdf
        source: inputs/parent.fdf
        destination: input.fdf
        media_type: text/x-siesta-fdf
    outputs:
      - name: density_matrix
        path: system.DM
        artifact_type: siesta.density-matrix
        media_type: application/x-siesta-dm
        required: true
    resources:
      nodes: 2
      mpi_processes: 64
      processes_per_node: 32
      cpus_per_process: 1
      walltime_seconds: 3600

  - task_id: restart
    kind: calculation
    capability: siestaflow.engine.siesta
    inputs:
      - name: fdf
        source: inputs/restart.fdf
        destination: input.fdf
        media_type: text/x-siesta-fdf
      - name: parent_dm
        from:
          task: parent
          output: density_matrix
        destination: system.DM
    outputs: []
    resources:
      nodes: 2
      mpi_processes: 64
      processes_per_node: 32
      cpus_per_process: 1
      walltime_seconds: 1800
```

JSON is always supported. YAML requires PyYAML in the local preparation
environment. The compiled lock uses canonical JSON and does not require YAML
support on the cluster.

## Task kinds

Schema 1.0 recognizes:

```text
calculation  transformation  validation  sweep  selection
checkpoint   postprocess     comparison  export external
```

A `capability` is a namespaced identifier. The compiler records it but Phase 1
does not yet resolve or execute a plugin.

## Inputs and outputs

An input has exactly one source:

- `source`: relative external file beside the workflow definition;
- `from`: output port of another task.

Artifact inputs infer their producer dependency. `depends_on` remains
available for control-only dependencies.

External inputs are confined to the workflow directory and included in the
lock with path, size, media type, and SHA-256. An optional declared `sha256`
must agree with the observed file.

Output paths are relative to the future task working directory. Output
`artifact_type` values are namespaced identifiers such as
`siesta.density-matrix`.

## Commands

```bash
qraft workflow validate workflow.yaml
qraft workflow plan workflow.yaml
qraft workflow graph workflow.yaml
qraft workflow graph workflow.yaml --format mermaid
qraft workflow compile workflow.yaml --output workflow.lock.json
```

`validate`, `plan`, and `graph` never write files. `compile --dry-run` reports
the predicted lock hash without writing. Existing lock files are protected
unless `--force` is supplied.

All commands in this phase leave `execution_authorized` as `false`.

## Fail-closed checks

Compilation is blocked by:

- unknown schema fields;
- duplicate tasks or ports;
- missing or unsafe external inputs;
- declared hash mismatches;
- unknown tasks or output ports;
- cycles and self-dependencies;
- incompatible artifact media types;
- invalid or inconsistent resource placement;
- noncanonical settings or metadata.

The compiled contract independently rechecks task ordering, graph edges,
ports, external artifacts, and dependency agreement. A plugin cannot bypass
these invariants by constructing a lock directly.

## Current boundary

Phase 1 compilation still does not submit, schedule, or execute tasks. The
initial Phase 3 adapter can convert the lock to a controller package only when
every executable task is a `calculation` using
`siestaflow.engine.siesta`, has one external FDF input, declares the exact
five resource fields shown above, and fits the external execution profile.
Non-SIESTA capabilities and nonempty engine settings fail closed until their
adapters exist.

Preparation requires the original workflow source root because lock artifacts
are verified again by size and SHA-256. Cluster details live in a separate
execution-profile file rather than the workflow. A template is available at
`examples/execution_profiles/slurm_hydra.example.json`.

```bash
qraft run prepare workflow.lock.json \
  --source-root PATH_TO_WORKFLOW_ROOT \
  --profile execution-profile.json \
  --output packages \
  --run-id relaxation-run-001
```

The command writes a transferable package and ZIP but does not run
`sbatch`. Successful compilation or preparation must not be interpreted as
scientific validity or execution authorization.

See the compilation-only example under
`examples/workflows/restart_chain_compile_only`.
