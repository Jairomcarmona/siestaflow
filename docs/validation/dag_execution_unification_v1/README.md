# QRAFT DAG execution unification v1

This record is the conservative closure of the execution-authority seam at baseline `80f3d04`.

The audit does not claim a global unification. It records **LEVEL C** because the smallest safe bridge is not present: `WorkflowCompiler` produces an execution-disabled `CompiledWorkflow`, `AllocationController` consumes a different persisted campaign schema, and `ConvergenceProtocol` owns the scientific attempt/validation path through `execute_fdf_plan`.

The characterization test makes the current split explicit so a future adapter cannot be mistaken for a cosmetic rename. Existing controller tests validate the reusable DAG behaviors needed by that adapter: readiness from dependencies, fan-out, sibling isolation, descendant blocking, artifact transfer, and recovery.

No SIESTA calculation, HPC campaign, schema migration, CLI change, or Hubbard/LR-U work was performed.
