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
| Full suite | PASS | 537 passed, 1 skipped | Executable regression |
| Build and wheel inventory/import | PASS | standard `python -m build`; wheel imports `CompiledWorkflowRuntime` | Package smoke |

The Windows global Python initially lacked PyYAML and sandboxed pytest could not
access its temporary directory. The repository's configured build environment,
executed outside that sandbox restriction, established a trustworthy baseline
of 524 passed and 1 skipped and a final result of 537 passed and 1 skipped.
WSL focused validation also passed; no HPC environment was used.
