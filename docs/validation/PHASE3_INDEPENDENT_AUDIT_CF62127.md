# Independent Phase 3 audit — commit cf62127

Status: `CONDITIONALLY_APPROVED / REMEDIATIONS_EVIDENCED`.

An independent ChatGPT session audited the archive built from commit
`cf621278d994d0896b9882033b3aea8a0307078c`, the complete post-execution
evidence ZIP for job `781100`, the prepared technical matrix package for
`781102`, sanitized `781102` fixtures, governance documents and the exact
`cf62127` patch.

## Dictamen

The audit found sufficient evidence to advance to a human decision on the
Phase 3 transition, but not to register an unconditional acceptance. It found
no change to scientific inputs, workflow locks, runtime, resource profiles,
contracts, version or tags in `cf62127`.

## Verified evidence

- Job `781100` verifies the canonical Yoltla path: parent completion, produced
  DM, SHA-256-bound transfer, successful SIESTA DM read, child completion and
  Slurm `COMPLETED 0:0`.
- Job `781102` verifies Slurm `COMPLETED 0:0` and PASS results for failed
  parent, absent DM, altered transfer hash, injected controller interruption
  recovery and controller host-set non-overlap.
- The retained local prepared ZIP for `781100` recalculates to
  `e372601a5320012ae42ff5ead5776d5ec657c1013ccf02e3db31180a9b36f9e3`.
- The `781100` post-execution evidence ZIP recalculates to
  `b7935e870798bf69d258596bb2a978b44e4ab8210d8d685813eb3d367a2faa1c`.

## Conditions and disposition

| Finding | Disposition |
| --- | --- |
| No raw immutable post-execution ZIP for `781102` | Superseded for acceptance coverage by raw matrix archive `781106`, with `OUT`, `ERROR`, state, case evidence, accounting and hash manifest. |
| Interruption was injected and resumed inside one allocation | Supplemented by real `SIGUSR1` job `781111` and resume in distinct allocation `781113`. |
| Disjoint hosts used ScriptedLauncher | Supplemented by concurrent physical `srun` steps in job `781115`. |
| Original `781100` prepared ZIP was absent from the first audit archive | Retained local prepared ZIP located and hash recalculated; absent remote-upload checksum remains explicit. |
| `781102` stderr-empty assertion lacked a fixture | Assertion removed. |

The full audit recommends an identified human decision only after these limits
are read and accepted. It does not establish scientific validity.

The remediation evidence is recorded in
[`PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md`](PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md).

## Remaining gate

The sole Phase 3 transition gate is now the investigator's identified,
informed acceptance or rejection. Any acceptance must retain the distinction
between technical engineering evidence and scientific validation; it must not
change the version or create a tag by itself.
