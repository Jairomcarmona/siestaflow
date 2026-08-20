# M2 F02 Canonical DAG validation

Baseline: `d7827ed700a884eeaf797882bc225b2e301a557e`.

The convergence protocol renders its points, writes
`rendered/convergence-workflow.json`, compiles it through `WorkflowCompiler`,
and executes the independent point nodes through `CompiledWorkflowRuntime`.

M2-01 through M2-08 passed: the legacy execution authority is absent; the
compiled point DAG and identities are deterministic; golden energies,
technical PASS results, recovery/reuse, forced immutable attempts, and public
result artifacts are preserved.

Final full suite: `563 passed`.

Closing commit: `feat: route F02 convergence through canonical DAG`.
