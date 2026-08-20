# M1 test matrix

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
