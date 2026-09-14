# Phase 4: Local real SIESTA observation producer

The canonical producer turns completed, immutable SIESTA artifacts into the
strict JSON observations consumed by the Mesh.Cutoff and k-grid convergence
rules. It is a postprocessor, not a scientific authoring or execution path.

```text
completed SIESTA FDF + stdout + FORCE_STRESS + pseudo manifest
  -> observation-production intent
  -> WorkflowDefinition -> workflow.lock.json -> run prepare
  -> observation.json -> convergence evaluator -> human review
```

The producer requires all of the following evidence: a final `E_KS(eV)`, an
`InitMesh: MESH` record, `SCF cycle converged`, `Job completed`, and one complete
atomic-force block in `FORCE_STRESS`. Missing evidence is a hard failure.

It records canonical hashes for the invariant FDF content (with only the
selected swept axis excluded), the structural identity, and the pseudopotential
manifest. It does not claim that a result is scientifically accepted. A
convergence evaluator may only produce `READY_FOR_HUMAN_REVIEW`.

Local validation uses the installed WSL SIESTA 5.4.2 H2O tutorial assets as a
technical fixture. Those artifacts are not a reference-project calculation,
are not Yoltla evidence, and do not modify the project's reference FDF,
geometry, or pseudopotentials.

The public recipe is `siestaflow.recipe.siesta.observation-production`; the
producer capability is `siestaflow.siesta.observation-producer`.
