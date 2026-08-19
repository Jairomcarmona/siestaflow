# Architecture

```text
core contracts (engine/cluster independent)
  -> generic kernel services
  -> SIESTA engine adapter
  -> generic campaign primitives
  -> allocation-local controller (DAG + transfers + gates)
  -> launcher adapter (srun | Hydra | direct gate)
  -> external ProjectPackage
  -> external ExamplePackage
```

`contracts` is the innermost dependency boundary. It defines versioning,
canonical envelopes, validation, artifacts, execution, events, and explicit
plugin capabilities. It imports no engine, launcher, cluster, subprocess, or
storage implementation. `contract_adapters.py` is the compatibility boundary
for gradual adoption.

`models`, `authorization`, `campaign`, `gates`, `hpc`, `workspace`, and
storage/filesystem modules form the existing kernel services.
`engines/siesta` parses, validates, renders controlled variants, audits
arbitrary pseudopotentials, and parses output. `project_packages.py` owns
schema/path validation. `siesta_campaigns.py` interprets external declarations.
`examples.py` exposes discovery, staging, reproducible packaging, simulation,
and result import. Remote modules create inert previews and conservatively
import evidence.

Dependency direction is inward toward generic contracts; reference examples may import the runtime, while runtime code never imports examples or reference projects.

The public extension and compatibility policy is specified in
`docs/design/CORE_CONTRACTS_1_0.md`.
Project scope, stable vocabulary, construction phases and acceptance
invariants are governed by `docs/design/QRAFT_BACKBONE.md`.

## Controller schema 2.0

A scientific task declares immutable inputs, resources, required outputs,
dependencies and optional parent transfers. A transfer is accepted only when
the parent task is `COMPLETED`, its result manifest hash still matches, and the
artifact hash agrees with that manifest. A failed parent blocks descendants.

Transferred artifacts are staged through two distinct representations:

1. an immutable, hash-bound evidence copy that records exactly what the child
   received;
2. a working copy exposed to SIESTA, which may legitimately be replaced during
   execution (for example, a restart `.DM`).

The working copy is verified immediately before launch. After execution its
hash is recorded as an output rather than compared with the original input
hash. For a SIESTA DM handoff, completion also requires runtime evidence that
the restart file was successfully read.

Gate tasks are small hash-bound commands executed directly by the controller.
They exist for deterministic operations such as convergence selection or
choosing which validated parent artifact to pass forward. They do not receive
authority to modify scientific policy.

```text
protected inputs
  -> SIESTA task through srun/Hydra
  -> result manifest + required artifact hashes
  -> immutable transfer evidence + mutable working copy
  -> gate task or dependent SIESTA task
  -> independently hashed final artifacts
```

The controller process is never launched through MPI. Only scientific SIESTA
steps use the configured MPI launcher.
