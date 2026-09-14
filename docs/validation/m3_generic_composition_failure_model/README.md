# M3 generic composition and failure model validation

Baseline: `dcb8dfd6fe316087595588da22d9ee548c25d7aa`.

The principal proof composes typed `WorkflowFragment` values with
`WorkflowComposer`, writes a WorkflowDefinition, compiles it with
`WorkflowCompiler`, and runs it through `CompiledWorkflowRuntime`.

M3-01 through M3-10 passed. The principal DAG terminal states are ROOT,
A, C and JOIN `COMPLETED`; B `FAILED`; and B_CHILD `BLOCKED`. The M3 fan-in
evidence micro-hotfix additionally proves that JOIN receives hash-bound A/C
artifacts and that the JOIN capability explicitly consumes both `left` and
`right` inputs. Allocation rollover from `alloc-001`
to `alloc-002` reused ROOT and continued WORK as `attempt-0002`.

Post-suite test-only fan-in regression: `39 passed`. The prior final full
suite remains `566 passed` and was not rerun.

Closing commit: `test: strengthen M3 fan-in consumption evidence`.
