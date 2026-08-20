# QRAFT M1 — Universal Runtime Authority

## Objective

M1 establishes one engine-neutral execution authority for new compiled
workflows:

```text
CompiledWorkflow → CompiledWorkflowRuntime → CapabilityRegistry
→ registered ENGINE capability → launcher → TechnicalValidation
→ NodeResult → immutable Attempt → DAG state/recovery
```

Baseline: `aaa68abb427642c4e99172bd56d13ada3eb98579`.

Branch: `feat/qraft-m1-universal-runtime`.

Final commit: the commit containing this dossier, with subject
`feat: establish universal capability runtime`.

## Architecture before and after

Before M1, `CompiledWorkflow` was deterministic but had no execution authority;
the allocation controller consumed a different SIESTA-shaped schema, and
convergence executed its points through a protocol-owned loop.

After M1, `CompiledWorkflowRuntime` resolves each node's `capability_id` through
the frozen canonical `CapabilityRegistry`. It owns readiness, dependency
blocking, immutable attempts, evidence, artifact hashes, retry entry,
recovery/reuse and tamper rejection. The selected capability owns inspection,
input validation, preparation, command construction, parsing, artifact
discovery and classification. Synthetic non-SIESTA and SIESTA fixtures execute
through this same path.

The accepted schema 1/2 allocation controller remains available without
behavior changes. Its SIESTA-shaped schema/parser/restart behavior is isolated
in `allocation_controller_compat.py`; `allocation_controller.py` is a stable
compatibility facade and contains no engine parsing or state-machine branch.

## Material files

- `src/qraft/execution/capability_runtime.py`
- `src/qraft/execution/capability_plugins.py`
- `src/qraft/execution/allocation_controller.py`
- `src/qraft/execution/allocation_controller_compat.py`
- `src/qraft/engines/siesta/adapter.py`
- `tests/execution/test_capability_runtime.py`
- targeted controller-package inventory updates
- `docs/design/QRAFT_EXECUTION_MILESTONES_V1.md`
- `docs/developer/TECH_DEBT.md`

## Explicit non-goals

M1 does not migrate convergence, change `CampaignSpec`, add a CLI command,
implement relaxation, DOS, PDOS, bands, magnetism, SOC, DFT+U/LR-U, screening,
or change `ScientificIdentity` semantics. No Yoltla access or real DFT run was
used.

## Remaining debt

- Convergence retains its direct sequential execution loop until M2.
- `single_fdf` remains a tested legacy runtime path.
- Legacy controller schemas and historical Attempt representations remain
  compatibility surfaces; new compiled workflows have one authoritative M1
  Attempt lifecycle.
- Artifact contract vocabulary can be extended by later capabilities without
  adding engine semantics to the runtime.

Prior controller/recovery evidence remains referenced from
[`dag_execution_unification_v1`](../dag_execution_unification_v1/) and is not
duplicated here.
