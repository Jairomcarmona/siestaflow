# Architecture

```text
generic kernel
  -> SIESTA engine adapter
  -> generic campaign primitives
  -> allocation-local controller (DAG + transfers + gates)
  -> launcher adapter (srun | Hydra | direct gate)
  -> external ProjectPackage
  -> external ExamplePackage
```

`models`, `authorization`, `campaign`, `gates`, `hpc`, `workspace`, and storage/filesystem modules form the kernel. `engines/siesta` parses, validates, renders controlled variants, audits arbitrary pseudopotentials, and parses output. `project_packages.py` owns schema/path validation. `siesta_campaigns.py` interprets external declarations. `examples.py` exposes discovery, staging, reproducible packaging, simulation, and result import. Remote modules create inert previews and conservatively import evidence.

Dependency direction is inward toward generic contracts; reference examples may import the runtime, while runtime code never imports examples or reference projects.

## Controller schema 2.0

A scientific task declares immutable inputs, resources, required outputs,
dependencies and optional parent transfers. A transfer is accepted only when
the parent task is `COMPLETED`, its result manifest hash still matches, and the
artifact hash agrees with that manifest. A failed parent blocks descendants.

Gate tasks are small hash-bound commands executed directly by the controller.
They exist for deterministic operations such as convergence selection or
choosing which validated parent artifact to pass forward. They do not receive
authority to modify scientific policy.

```text
protected inputs
  -> SIESTA task through srun/Hydra
  -> result manifest + required artifact hashes
  -> gate task or dependent SIESTA task
  -> verified transfer into new immutable attempt
```

The controller process is never launched through MPI. Only scientific SIESTA
steps use the configured MPI launcher.
