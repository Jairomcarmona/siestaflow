# QRAFT DAG acceptance baseline v1

This dossier records the DAG acceptance audit for commit `8def70ea80ffbed203e451a81f0cdd0c86dbd37e` on branch `feat/qraft-campaign-spec-v1`.

It is an evidence baseline, not a protocol implementation. It deliberately separates:

- DAG represented: a graph or dependency contract exists in code or output.
- DAG compiled: the graph is validated and materialized as a deterministic plan.
- DAG executed: the same graph controls the runtime launch and terminal state.
- DAG recovered: the same execution authority resumes or reuses immutable attempts.

The WSL N=4 campaign is reused by reference from `docs/validation/wsl_n4_campaign_spec_v1/`; its raw output is not duplicated here.

## Scope

Validated now: the existing single-FDF vertical, the existing two-point `CampaignSpec` convergence path, parser fixtures, and focused controller/recovery tests.

Not claimed: a unified CampaignSpec-to-WorkflowCompiler-to-AllocationController execution path, chained protocols, relaxation, electronic fan-out, or scientific Hubbard/LR-U protocols. DFT+U and LR-U are explicitly deferred by project decision.

The complete matrix is in `DAG_ACCEPTANCE_MATRIX_V1.md`. Current implementation limits are in `CURRENT_LIMITS.md`. Machine-readable provenance is in `evidence/`.
