# QRAFT DAG acceptance matrix v1

Status vocabulary: `READY`, `READY_WITH_FIXTURE`, `PARTIAL`, `NOT_IMPLEMENTED`, `BLOCKED_BY_PROTOCOL`.
`VALIDATED_NOW=yes` means the current audit has executable evidence for the claim; static code inspection alone never qualifies.

## Functional requirements

| ID | Requirement | Represented | Compiled | Executed | Recovered | Status | Validated now |
|---|---|---|---|---|---|---|---|
| F01 | Single-point SCF | yes | yes | yes, WSL real | yes | READY | yes |
| F02 | One-parameter convergence | yes | yes, protocol DAG | yes, WSL real | yes, immutable reuse | READY | yes |
| F03 | Chained convergence | partial, one scan only | partial | no | no | BLOCKED_BY_PROTOCOL | no |
| F04 | Early-stop convergence | partial, decision node only | partial | no early stop; all points loop | no | BLOCKED_BY_PROTOCOL | no |
| F05 | Vacuum/structural transform | no CampaignSpec node | no | no | no | NOT_IMPLEMENTED | no |
| F06 | Fixed-cell relaxation | no CampaignSpec runtime | no | no | no | BLOCKED_BY_PROTOCOL | no |
| F07 | Variable-cell relaxation | no | no | no | no | NOT_IMPLEMENTED | no |
| F08 | Staged relaxation | no | no | no | no | NOT_IMPLEMENTED | no |
| F09 | Convergence to relaxation | no cross-protocol handoff | no | no | no | BLOCKED_BY_PROTOCOL | no |
| F10 | Relaxation to final SCF | no GeometryArtifact transition | no | no | no | BLOCKED_BY_PROTOCOL | no |
| F11 | Final SCF to DOS | partial, legacy exporter/tests | no CampaignSpec DAG node | no | no | BLOCKED_BY_PROTOCOL | no |
| F12 | Final SCF to PDOS | partial, legacy exporter/tests | no CampaignSpec DAG node | no | no | BLOCKED_BY_PROTOCOL | no |
| F13 | Final SCF to bands | partial, legacy exporter/tests | no CampaignSpec DAG node | no | no | BLOCKED_BY_PROTOCOL | no |
| F14 | Electronic fan-out | partial, legacy paths | no unified fan-out authority | no | no | BLOCKED_BY_PROTOCOL | no |
| F15 | Collinear spin SCF | parser/FDF fixture support | no real CampaignSpec spin run | fixture only | no | READY_WITH_FIXTURE | no |
| F16 | Magnetic-state fan-out/select | partial legacy observations | no CampaignSpec fan-out | no | no | BLOCKED_BY_PROTOCOL | no |
| F17 | Noncollinear/SOC | no CampaignSpec protocol | no | no | no | NOT_IMPLEMENTED | no |

F01 and F02 use the preserved WSL evidence under `docs/validation/wsl_n4_campaign_spec_v1/` and the focused tests recorded in `evidence/test_results.json`.

## Adversarial requirements

| ID | Scenario | Status | Validated now | Evidence |
|---|---|---|---|---|
| A01 | SCF non-convergence blocks dependent work | PARTIAL | no | parser fixture and controller blocking are tested separately; combined CampaignSpec path is not |
| A02 | Truncated output is not success | READY_WITH_FIXTURE | yes | parser fixture plus incomplete-output controller test |
| A03 | Missing required artifact is incomplete | READY_WITH_FIXTURE | yes | `test_truncated_output_and_missing_required_artifact_are_incomplete` |
| A04 | Artifact/input hash mismatch prevents launch/reuse | READY_WITH_FIXTURE | yes | hash-bound transfer and protected-input tests |
| A05 | Isolated fan-out failure does not stop independent work | READY_WITH_FIXTURE | yes | `test_failure_does_not_stop_independent_task` |
| A06 | Interruption and retry/recovery create controlled continuation | READY_WITH_FIXTURE | yes | signal shutdown and new-job recovery tests |
| A07 | Valid immutable attempts are reused, tampered attempts are rejected | READY | yes | WSL recovery evidence and single-FDF recovery tests |
| A08 | Allocation rollover preserves campaign state | READY_WITH_FIXTURE | yes | `test_new_job_id_resumes_incomplete_campaign_without_fake_allocation` |

## DAG authority conclusion

| Path | Represented | Compiled | Executed by that DAG | Recovered by that DAG | Finding |
|---|---|---|---|---|---|
| `single_fdf` | yes | fixed protocol DAG | yes | yes | validated vertical |
| `convergence` / `CampaignSpec` | yes | protocol plan | yes, through a direct protocol loop | yes, attempt reuse | runtime works, but not through the general compiler/controller |
| `workflow` / `WorkflowCompiler` | yes | yes | no general executor connection | no | compiler is an execution plan, not the runtime authority |
| `AllocationController` | yes, separate campaign schema | yes in controller inputs | yes for its own schema | yes for its own schema | not connected to CampaignSpec v1 |

Overall DAG authority: `PARTIAL`. QRAFT has working verticals and robust tested primitives, but one authoritative DAG does not yet govern the complete FDF → execution specification → compiled DAG → allocation controller → SIESTA → evidence chain.

## Decision

`PARTIAL_BASELINE`: evidence is recorded and the current limits are explicit. This is not a failure of the existing WSL vertical; it is a boundary statement about cross-protocol DAG authority.
