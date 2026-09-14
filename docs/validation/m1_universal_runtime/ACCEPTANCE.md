# M1 acceptance

| Release gate | Status | Evidence | Type |
|---|---|---|---|
| Compiled node resolves and executes registered capability | PASS | `test_registry_executes_synthetic_compiled_node_with_one_attempt` | Executable synthetic fixture |
| Non-SIESTA capability uses generic path | PASS | same test; no capability-specific runtime branch | Executable + static boundary test |
| Capability owns parsing/classification | PASS | `test_capability_classification_controls_opaque_failure_and_sibling_continues` | Executable synthetic fixture |
| Failed dependency blocks descendants | PASS | same test | Executable synthetic fixture |
| Independent sibling continues | PASS | same test | Executable synthetic fixture |
| Required artifact and hashes enforced | PASS | missing/tampered artifact tests | Executable synthetic fixture |
| Retry creates immutable attempt | PASS | `test_interrupted_attempt_retries_without_overwriting` | Executable synthetic fixture |
| Valid completion reused | PASS | `test_valid_attempt_is_reused_without_relaunch` | Executable synthetic fixture |
| Tampered completion rejected | PASS | artifact and parser-evidence tamper tests | Executable synthetic fixture |
| Scientific and execution identity remain separate | PASS | `test_execution_resources_do_not_contaminate_scientific_identity` plus existing single-FDF regression | Executable contract tests |
| SIESTA uses registered generic path | PASS | `test_siesta_adapter_executes_through_registered_generic_path` | Synthetic SIESTA output fixture |
| Generic runtime/controller has no direct SIESTA semantics | PASS | `test_generic_runtime_modules_have_no_engine_specific_execution_logic` | Static boundary test |
| Existing allocation recovery/artifact behavior preserved | PASS | `tests/m4/test_allocation_controller.py` | Executable regression |
| Existing single-FDF and convergence behavior preserved | PASS | focused matrix and full suite | Executable regression |
| Checkpoint full suite | PASS | 537 passed, 1 skipped | Executable regression |
| Build and wheel inventory/import | PASS | standard `python -m build`; wheel imports `CompiledWorkflowRuntime` | Package smoke |

The Windows global Python initially lacked PyYAML and sandboxed pytest could not
access its temporary directory. The repository's configured build environment,
executed outside that sandbox restriction, established a trustworthy baseline
of 524 passed and 1 skipped and a final result of 537 passed and 1 skipped.
WSL focused validation also passed; no HPC environment was used.

## Runtime convergence closure

| Closure gate | Status | Evidence |
|---|---|---|
| One canonical default production runtime | PASS | CLI and generated package workers select `CanonicalController` |
| Bounded ready-node concurrency | PASS | `test_ready_tree_runs_with_exact_bounded_concurrency` |
| CPU capacity and wait semantics | PASS | `test_cpu_budget_waits_and_releases_without_overallocation` |
| Generic exclusive host allocation/release | PASS | `test_host_leases_are_exclusive_and_released` |
| Walltime launch stop remains resumable | PASS | `test_walltime_stop_is_resumable_and_completed_work_reuses` |
| Controlled interruption is never false completion | PASS | `test_controlled_interruption_resumes_only_unfinished_attempt` |
| Completed work reused; unfinished work resumes | PASS | same recovery fixture plus original M1 reuse/tamper fixtures |
| Multi-input primary is capability-owned | PASS | parameterized explicit-input fixture with reversed lexical names |
| Second engine registration needs no runtime edit | PASS | `test_second_engine_registration_requires_no_runtime_edit` |
| Legacy schema translates to canonical contracts | PASS | `test_legacy_config_translates_to_compiled_workflow_and_execution_spec` |
| New packages target canonical runtime | PASS | package worker/manifest and self-contained import fixture |
| Historical state compatibility remains explicit | PASS | unchanged legacy controller suite; facade alias assertion |
| Engine-neutral architecture audit | PASS | no SIESTA/parser/scientific-operation branch in runtime/coordinator |
| Final focused matrix | PASS | 101 passed |
| Final full suite | PASS | 549 passed, 1 skipped |
| Final sdist/wheel/import | PASS | final build and wheel inventory/import smoke |

The closure used deterministic local fixtures rather than real HPC or DFT.
M2 convergence execution was not migrated or modified.

## Final invariant hotfix

| Invariant gate | Status | Evidence |
|---|---|---|
| Task rename leaves translated scientific identity unchanged | PASS | `test_legacy_scientific_identity_ignores_task_rename` |
| Execution placement changes only `ExecutionSpec` | PASS | `test_legacy_execution_changes_do_not_change_scientific_identity` |
| Protected scientific-input mutation changes identity | PASS | `test_legacy_scientific_identity_changes_with_protected_input` |
| Generic node capacity prevents over-allocation | PASS | `test_node_capacity_prevents_overallocation_and_releases` |
| Valid node concurrency reaches allocated capacity | PASS | `test_valid_node_concurrency_reaches_allocated_node_capacity` |
| CPU and node limits are independently enforced | PASS | `test_cpu_and_node_limits_are_independently_enforced` |
| Mutable working restart retains immutable evidence and reuses | PASS | `test_mutable_restart_keeps_immutable_evidence_and_reuses` |
| Immutable-input and parent-source tamper reject reuse | PASS | parameterized `test_mutable_restart_tamper_rejects_reuse` |
| SIESTA owns restart declaration and consumption confirmation | PASS | `test_siesta_capability_rejects_unconfirmed_restart_consumption` |
| Generic runtime remains free of SIESTA/DM semantics | PASS | architecture static assertion and source audit |
| Final focused regression | PASS | 55 passed |
| Final full suite | PASS | 559 passed, 1 skipped |
| Final build/wheel/import | PASS | one build; neutral and canonical wheel imports |

No global identity schema, convergence source, historical controller, DAG
contract, or production entry point changed.
