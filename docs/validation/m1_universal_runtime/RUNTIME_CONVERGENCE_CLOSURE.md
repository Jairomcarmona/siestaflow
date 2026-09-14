# M1 runtime convergence closure

## Audited defect

At checkpoint `4964e9c`, `CompiledWorkflowRuntime` was engine-neutral and
recoverable but sequential. New allocation packages still launched
`allocation_controller_compat.AllocationController`, leaving two writable
production execution authorities. The runtime also selected a multi-input
primary alphabetically.

## New-production call graph

```text
qraft campaign worker / generated controller package / M4 package
  → CanonicalController
  → legacy schema compatibility translation (when applicable)
  → CompiledWorkflow + per-node ExecutionSpec
  → CompiledWorkflowRuntime
  → ResourceCoordinator lease
  → CapabilityRegistry
  → SiestaEngineAdapter or another executable capability
  → composed StepLauncher
  → runtime-finalized immutable Attempt and persistent DAG state
```

There is no equivalent new-package edge to the independent historical
`AllocationController` scheduler.

## Ownership

| Concern | Authority |
|---|---|
| DAG readiness and dependency blocking | `CompiledWorkflowRuntime` |
| Attempt creation/finalization | `CompiledWorkflowRuntime` |
| Recovery/reuse and tamper rejection | `CompiledWorkflowRuntime` |
| Artifact routing and evidence | `CompiledWorkflowRuntime` |
| CPU/host/walltime coordination | `ResourceCoordinator` under runtime control |
| Engine input, parsing and classification | registered capability |
| Launcher placement mechanism | composed launcher adapter |
| Scientific decision | protocol/rule outside M1 |

## Historical policy

`allocation_controller_compat.py` remains unchanged as the historical schema
1/2 recovery implementation. `allocation_controller.py` exports it under the
explicit `HistoricalAllocationController` name and retains the old alias for
import compatibility. Existing `campaign_state.json` evidence is neither
rewritten nor deleted. New CLI/package workers use `CanonicalController` and
write canonical `workflow_runtime.json` state.

## Final adversarial answers

```text
Can new workflow execute without independent legacy scheduler? YES
Can independent nodes run concurrently under bounded resources? YES
Can a new engine be registered without runtime edits? YES
Does canonical runtime contain SIESTA parser semantics? NO
Does runtime choose scientific input alphabetically? NO
Can valid completed work be reused? YES
Is tampered work rejected? YES
Do new packages default to legacy runtime? NO
Was convergence migrated? NO
```
