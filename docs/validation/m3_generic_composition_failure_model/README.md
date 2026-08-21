# M3 generic composition and failure model validation

Baseline: `dcb8dfd6fe316087595588da22d9ee548c25d7aa`.

The principal proof composes typed `WorkflowFragment` values with
`WorkflowComposer`, writes a WorkflowDefinition, compiles it with
`WorkflowCompiler`, and runs it through `CompiledWorkflowRuntime`.

M3-01 through M3-10 passed. The principal DAG terminal states are ROOT,
A, C and JOIN `COMPLETED`; B `FAILED`; and B_CHILD `BLOCKED`. JOIN consumed
the hash-bound artifacts from A and C. Allocation rollover from `alloc-001`
to `alloc-002` reused ROOT and continued WORK as `attempt-0002`.

Focused regression: `51 passed`. Final full suite: `566 passed`.

Closing commit: `test: close M3 generic composition failure model`.
