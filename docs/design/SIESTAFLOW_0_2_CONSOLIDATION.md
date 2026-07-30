# SIESTAFLOW 0.2 consolidation

Date: 2026-07-29

## Verdict

The generic kernel and the birnessite campaign drivers now share one
operational model:

```text
one manual sbatch
  -> controller inside the allocation
  -> bounded MPI calculations
  -> technical/scientific gate
  -> immutable state and evidence
  -> next task, controlled stop, or resubmission
```

Version 0.2 moves reusable mechanisms into the kernel. It does not copy
project-specific scientific choices into core code.

## Capabilities consolidated

| Capability | 0.2 implementation |
|---|---|
| Yoltla MPI | Hydra, SSH bootstrap, explicit hosts/ppn, fabric UUID |
| One allocation | allocation-local controller; no login-node daemon |
| Parallel waves | CPU pool plus exclusive host assignment |
| Chaining | dependency DAG |
| Geometry/DM handoff | hash-bound artifact transfers |
| Mathematical selection | hash-bound gate task extension point |
| Resume | state and result-manifest revalidation |
| Monitoring | `campaign progress`, `campaign watch`, `progress.sh` |
| Distribution | deterministic `remote controller-package` ZIP |

## Birnessite migration boundary

Generic mechanisms migrated from the current campaigns include ordered stages,
independent convergence calculations, multinode placement, parent
`STRUCT_OUT`/DM transfer, persisted attempts and progress reporting.

Mesh/k-grid thresholds, magnetic selection, relaxation tolerances, geometry
acceptance and linear-response \(U\) policy remain project plugins. They are
represented as hash-bound gate tasks and never become core defaults. Existing
standalone packages remain authoritative for jobs already submitted and are
not rewritten in place.

## Acceptance criterion

The engineering milestone closes when a clean CLI-generated package:

1. passes local and Yoltla verification;
2. runs two dependent SIESTA tasks through Hydra;
3. transfers a required parent artifact;
4. survives controlled interruption and resubmission;
5. preserves completed-task hashes after recovery.

Until then the status is `V0_2_CONSOLIDATION_ALPHA`, not a production release.
