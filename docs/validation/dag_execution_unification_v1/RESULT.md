# QRAFT DAG execution unification v1 result

## LEVEL ACHIEVED

`C`

## DAG AUTHORITY

Before:

- `single_fdf`: independent runtime authority with its own fixed protocol DAG.
- `convergence`: protocol-owned direct execution loop over rendered points.
- `workflow/controller`: separate compiler/controller authority; compiled plans are not execution-authorized and the controller consumes its own campaign schema.

After:

- `single_fdf`: unchanged and preserved.
- `convergence`: unchanged; the split is now characterized by an executable test and this seam record.
- `workflow/controller`: unchanged and preserved; no third executor was introduced.

## F02

- unchanged scientific behavior: yes; no convergence source or scientific contract changed.
- DAG-governed execution: no; LEVEL A was not claimed.
- recovery preserved: yes, by the existing F02 and single-FDF recovery paths; no recovery implementation was changed.

## ADVERSARIAL

- dependency ordering: PASS — `test_sequential_steps_use_one_slot`.
- fan-out: PASS — `test_two_steps_run_together_but_cpu_pool_limits_next_wave`.
- branch isolation: PASS — `test_failure_does_not_stop_independent_task`.
- dependent blocking: PASS — `test_failed_dependency_blocks_child_without_launch`.
- artifact handoff: PASS — `test_dependency_artifact_is_hash_bound_and_transferred`.
- recovery: PASS — `test_new_job_id_resumes_incomplete_campaign_without_fake_allocation`.

These are reusable controller guarantees, not proof that CampaignSpec F02 already calls the controller.

## CODE

- files changed: `tests/workflows/test_dag_execution_unification.py`.
- architecture added: none.
- architecture reused: `WorkflowCompiler`, `CompiledWorkflow`, `AllocationController`, existing attempt/artifact/recovery tests; only the seam was characterized.

## REMAINING SPLIT

There is no safe adapter from `CompiledWorkflow` to `AllocationController` that preserves both contracts. The compiled workflow uses capability/input/output/resource objects; the controller requires hash-bound `ControllerTask` records, launcher/allocation configuration, controller attempt manifests, and its own persisted state. F02 additionally requires `execute_fdf_plan`'s scientific identity, technical validation, result manifest, and reuse semantics. Wrapping one inside the other without a mapping contract would duplicate attempts/evidence and make recovery ambiguous.

## NEXT MINIMUM STEP

Define and test one explicit adapter contract for a single F02 point: `CompiledWorkflow task → controller task/action`, including input/artifact hashes, node result mapping, technical validation ownership, and recovery identity. Then migrate one controlled F02 fixture through that adapter before changing the real convergence path.
