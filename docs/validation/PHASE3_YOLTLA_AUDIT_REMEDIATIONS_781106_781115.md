# Phase 3 Yoltla audit remediations — jobs 781106 to 781115

Status: `REMOTE_RUNTIME_DEBT_REMEDIATED / HUMAN_DECISION_PENDING`.

This record incorporates three immutable, operator-supplied post-job archives
that address the runtime and provenance limits identified by the independent
audit of `cf62127`. These are technical validation jobs; none performs a
scientific SIESTA calculation or changes the canonical `781100` acceptance.

| Validation | Jobs | Result | Evidence ZIP SHA-256 |
| --- | --- | --- | --- |
| Complete adversarial record | `781106` | `COMPLETED 0:0`; five cases PASS | `e5cadf9d20efd8df31807a1ad194e5fda3a8d8daba00975edf627f89c9f9055e` |
| Real Slurm signal and new-allocation resume | `781111`, `781113` | both `COMPLETED 0:0`; `SIGUSR1` then two attempts | `a094c30505783763969e4bc6f148a9a35ccb456cfc5495716687ed857556bc8e` |
| Physical concurrent placement | `781115` | batch and two `srun` steps `COMPLETED 0:0` | `cea352bd517b3d0e3b890f7574c265b5760dcb8023933d3ceec68778c73aa1f0` |

## Verified remediation

- `781106` retains raw `OUT`, `ERROR`, Slurm accounting, structured matrix
  result, all case state/events/work evidence, and an internal SHA-256
  manifest. Failed parent, missing DM, altered transfer hash, interruption
  recovery and logical host-set non-overlap all report `PASS`.
- `781111` records the real Slurm-delivered `SIGUSR1` as `SHUTDOWN_SIGNAL` and
  leaves the controller `INTERRUPTED`. `781113` runs in a second allocation,
  recovers and completes the same task on attempt two.
- `781115` launches two concurrent physical `srun` steps. Slurm records steps
  `781115.0` on `tt[32-33]` and `781115.1` on `tt[30-31]`; their observed
  hostnames are exactly `tt30,tt31` and `tt32,tt33`, with no overlap.

The archives are retained under
[`tests/fixtures/phase3/yoltla_audit_remediations/`](../../tests/fixtures/phase3/yoltla_audit_remediations/)
and are hash-verified by `test_phase3_remote_evidence.py`.

## Remaining boundary

The historic lack of a primary remote-upload `sha256sum` for the original
`781100` prepared ZIP cannot be reconstructed retrospectively; the retained
local prepared ZIP and the executed package manifest remain the available
identity evidence. This is a provenance limitation, not an untested runtime
behavior. The only transition gate is now the investigator's identified human
acceptance or rejection of Phase 3 technical engineering evidence.
