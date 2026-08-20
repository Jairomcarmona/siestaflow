# M1 test matrix

## Checkpoint `4964e9c` matrix (preserved)

Command keys:

- `FOCUSED`: final 80-test M1 matrix recorded in `evidence/commands.txt`.
- `FULL`: final repository suite recorded in `evidence/commands.txt`.
- `BUILD`: final build/wheel smoke recorded in `evidence/commands.txt`.

| ID | Property | Status | Evidence type | Exact pytest node/test | Command | Result | Notes |
|---|---|---|---|---|---|---|---|
| T01 | Registry execution | PASS | Synthetic fixture | `test_registry_executes_synthetic_compiled_node_with_one_attempt` | FOCUSED | PASS | One persisted `attempt-0001` |
| T02 | Unknown capability | PASS | Synthetic fixture | `test_unknown_capability_blocks_before_attempt_or_launch` | FOCUSED | PASS | No attempt or launch |
| T03 | Contract incompatibility | PASS | Synthetic fixture | `test_contract_incompatibility_blocks_before_attempt_or_launch` | FOCUSED | PASS | Core contract check fails closed |
| T04 | Synthetic engine-neutral proof | PASS | Synthetic fixture | `test_registry_executes_synthetic_compiled_node_with_one_attempt` | FOCUSED | PASS | Release gate |
| T05 | Capability-owned parsing/classification | PASS | Synthetic fixture | `test_capability_classification_controls_opaque_failure_and_sibling_continues` | FOCUSED | PASS | Runtime cannot interpret opaque token |
| T06 | Failure blocks descendants | PASS | Synthetic fixture | same test | FOCUSED | PASS | B blocked, never launched |
| T07 | Independent sibling continues | PASS | Synthetic fixture | same test | FOCUSED | PASS | C completes after A fails |
| T08 | Required artifact missing | PASS | Synthetic fixture | `test_missing_required_artifact_fails_and_blocks_consumer` | FOCUSED | PASS | Producer technical FAIL |
| T09 | Artifact hash mismatch | PASS | Synthetic fixture | `test_tampered_parent_artifact_prevents_consumer_launch` | FOCUSED | PASS | Consumer not launched |
| T10 | Interrupted attempt retry | PASS | Synthetic fixture | `test_interrupted_attempt_retries_without_overwriting` | FOCUSED | PASS | `attempt-0002`; first preserved |
| T11 | Recovery/reuse | PASS | Synthetic fixture | `test_valid_attempt_is_reused_without_relaunch` | FOCUSED | PASS | No second launch |
| T12 | Tampered evidence prevents reuse | PASS | Synthetic fixtures | `test_tampered_attempt_artifact_is_not_reused`; `test_tampered_parser_evidence_is_not_reused` | FOCUSED | PASS | New attempt required |
| T13 | Scientific vs execution identity | PASS | Contract test | `test_execution_resources_do_not_contaminate_scientific_identity` | FOCUSED | PASS | Same science, different execution fingerprint |
| T14 | SIESTA adapter through generic path | PASS | Synthetic SIESTA fixture | `test_siesta_adapter_executes_through_registered_generic_path` | FOCUSED | PASS | Adapter parser/classifier observed |
| T15 | Existing single-FDF regression | PASS | Existing regression | `tests/runtime_v1/test_single_fdf_vertical.py` | FOCUSED | PASS | Public behavior unchanged |
| T16 | Existing convergence regression | PASS | Existing regression | `tests/campaigns/test_campaign_spec_v1.py`; full convergence coverage | FOCUSED + FULL | PASS | Execution loop intentionally unchanged |
| T17 | Existing controller recovery/artifact regression | PASS | Existing regression | `tests/m4/test_allocation_controller.py` | FOCUSED | PASS | Compatibility path preserved |
| T18 | Full suite | PASS | Full executable suite | `tests/` | FULL | 537 passed, 1 skipped | No new failures |

Package acceptance: BUILD passed and the wheel contains/imports the generic
runtime, explicit SIESTA composition helper, stable controller facade and
legacy compatibility module.

## Runtime convergence closure matrix

Command keys for this table:

- `CLOSURE_FOCUSED`: 101-test closure/regression matrix.
- `CLOSURE_FULL`: final repository suite.
- `CLOSURE_BUILD`: final sdist/wheel/inventory/import smoke.

| ID | Property | Status | Exact evidence | Command |
|---|---|---|---|---|
| C01 | Synthetic registered capability through canonical runtime | PASS | original `test_registry_executes_synthetic_compiled_node_with_one_attempt` | CLOSURE_FOCUSED |
| C02 | SIESTA fixture through same runtime | PASS | original `test_siesta_adapter_executes_through_registered_generic_path` | CLOSURE_FOCUSED |
| C03 | Runtime/coordinator engine-neutral | PASS | closure architecture static test | CLOSURE_FOCUSED |
| C04 | Bounded independent-node concurrency | PASS | `test_ready_tree_runs_with_exact_bounded_concurrency` | CLOSURE_FOCUSED |
| C05 | CPU budget never exceeded | PASS | `test_cpu_budget_waits_and_releases_without_overallocation` | CLOSURE_FOCUSED |
| C06 | Host/node policy and release | PASS | `test_host_leases_are_exclusive_and_released` | CLOSURE_FOCUSED |
| C07 | Unsafe walltime launch prevented | PASS | `test_walltime_stop_is_resumable_and_completed_work_reuses` | CLOSURE_FOCUSED |
| C08 | Controlled interruption is `INTERRUPTED` | PASS | `test_controlled_interruption_resumes_only_unfinished_attempt` | CLOSURE_FOCUSED |
| C09 | Allocation continuation/reuse | PASS | walltime and controlled-interruption recovery fixtures | CLOSURE_FOCUSED |
| C10 | Tampered work rejected | PASS | original artifact/parser evidence tamper fixtures | CLOSURE_FOCUSED |
| C11 | Failed parent blocks descendant | PASS | original opaque failure fixture | CLOSURE_FOCUSED |
| C12 | Independent sibling completes | PASS | original opaque failure fixture | CLOSURE_FOCUSED |
| C13 | Explicit multi-input selection | PASS | parameterized lexical-order reversal fixture | CLOSURE_FOCUSED |
| C14 | Second engine, zero runtime edits | PASS | source-hash-bound second-engine fixture | CLOSURE_FOCUSED |
| C15 | Legacy config translation | PASS | schema translation fixture | CLOSURE_FOCUSED |
| C16 | New package canonical default | PASS | generated worker/manifest and self-contained import | CLOSURE_FOCUSED |
| C17 | Historical recovery supported | PASS | unchanged legacy suite and explicit facade boundary | CLOSURE_FOCUSED |
| C18 | Scientific/execution identity separation | PASS | original identity test and single-FDF regression | CLOSURE_FOCUSED |
| C19 | `single_fdf` regression | PASS | `tests/runtime_v1/test_single_fdf_vertical.py` | CLOSURE_FOCUSED |
| C20 | Convergence unchanged | PASS | `tests/campaigns/test_campaign_spec_v1.py`; no source diff | CLOSURE_FOCUSED + CLOSURE_FULL |
| C21 | Legacy controller regression | PASS | `tests/m4/test_allocation_controller.py` | CLOSURE_FOCUSED |
| C22 | Full suite | PASS | 549 passed, 1 skipped | CLOSURE_FULL |
| C23 | Build/wheel/install smoke | PASS | final sdist/wheel and both wheel/self-contained imports | CLOSURE_BUILD |
| C24 | No second default production runtime | PASS | CLI/package static call-graph audit | CLOSURE_FOCUSED |
