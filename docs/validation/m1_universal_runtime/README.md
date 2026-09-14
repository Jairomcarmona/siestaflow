# QRAFT M1 — Universal Runtime Authority

## Objective

M1 now establishes one resource-aware, engine-neutral production authority:

```text
CLI / package / recipe
→ CompiledWorkflow
→ CompiledWorkflowRuntime
→ ResourceCoordinator
→ CapabilityRegistry
→ registered executable capability
→ launcher
→ TechnicalValidation / NodeResult / immutable Attempt
```

Original M1 baseline: `aaa68abb427642c4e99172bd56d13ada3eb98579`.

M1 checkpoint: `4964e9c44fffb671224279665ccfd651766c13a3`.

Corrective branch: `fix/qraft-m1-runtime-convergence-closure`.

Closure commit: the commit containing this dossier, with subject
`fix: close M1 runtime convergence gap`.

Final invariant hotfix source: `ae794f12a631849a155a1a03c3db07dd5730d2d9`.

Final invariant hotfix: the commit containing this dossier, with subject
`fix: enforce final M1 runtime invariants`.

## Checkpoint and closure

Checkpoint `4964e9c` introduced `CompiledWorkflowRuntime`, registry dispatch,
immutable attempts, recovery/reuse, evidence hashes and SIESTA capability
ownership. It still executed ready nodes sequentially while generated HPC
packages invoked an independent SIESTA-shaped allocation controller.

The corrective closure reuses the accepted controller scheduling policy in
the generic `ResourceCoordinator`: bounded ready-node concurrency, CPU leases,
exclusive host leases where launchers require them, release, walltime launch
gates and controlled shutdown. `CompiledWorkflowRuntime` remains the only
creator/finalizer of new canonical Attempt records and persists allocation
continuation history.

`CanonicalController` translates the accepted schema 1/2 package configuration
to `CompiledWorkflow`, `ExecutionSpec` and capability composition. The public
campaign worker and both generated package workers select this path. The old
`AllocationController` implementation remains available only as the explicit
`HistoricalAllocationController` compatibility surface for historical state
and its accepted regression suite; it is not the default for new production
execution.

The final invariant hotfix removes task labels and placement metadata from
legacy-translated scientific identity, adds explicit generic node capacity to
resource leases, and separates immutable staged-input evidence from
capability-declared mutable working inputs. Parent/source provenance and
non-mutable inputs remain hash-checked during reuse. SIESTA alone identifies
transferred `.DM` inputs and validates parser-owned restart-consumption
evidence.

## Input and capability authority

The runtime no longer selects `inputs[sorted(inputs)[0]]`. A single input is
unambiguous; multi-input execution requires capability-owned selection.
`SiestaEngineAdapter` chooses the declared/typed FDF and the generic command
capability requires explicit `primary_input` metadata.

Executable dispatch is contract/method based. `CapabilityKind.EXECUTABLE`
supports infrastructure commands without engine or scientific-operation
branches. A second engine capability is registered and executed in tests with
zero runtime source edits.

## Material files

- `src/qraft/execution/capability_runtime.py`
- `src/qraft/execution/resource_coordinator.py`
- `src/qraft/execution/canonical_controller.py`
- `src/qraft/execution/legacy_translation.py`
- `src/qraft/execution/command_capability.py`
- `src/qraft/execution/capability_plugins.py`
- `src/qraft/execution/allocation_controller.py`
- `src/qraft/execution/allocation_controller_compat.py`
- `src/qraft/engines/siesta/adapter.py`
- `tests/execution/test_capability_runtime.py`
- `tests/execution/test_runtime_convergence_closure.py`
- `docs/validation/m1_universal_runtime/FINAL_INVARIANT_HOTFIX.md`
- generated controller-package inventory and entry-point updates

## Explicit non-goals

This closure does not migrate or change convergence, and does not implement
relaxation, DOS, PDOS, bands, magnetism, SOC, DFT+U/LR-U or screening. It does
not change `ScientificIdentity` semantics, destructively migrate historical
evidence, use Yoltla or perform a real DFT/HPC run.

## Remaining debt

- Convergence retains its accepted execution loop until M2.
- `single_fdf` remains a tested legacy runtime path.
- Historical schema 1/2 controller evidence retains explicit compatibility
  recovery; new packages do not write that state by default.
- Real-cluster resource acceptance remains future validation; deterministic
  synthetic scheduling and package/build gates close M1 software authority.

The original checkpoint evidence hashes are preserved in
`evidence/checkpoint_4964e9c_hashes.sha256`; the runtime-convergence closure
hashes are preserved in `evidence/checkpoint_ae794f1_hashes.sha256`. Prior controller evidence remains
referenced from [`dag_execution_unification_v1`](../dag_execution_unification_v1/).
