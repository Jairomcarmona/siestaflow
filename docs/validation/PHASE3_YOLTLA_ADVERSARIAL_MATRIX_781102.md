# Phase 3 Yoltla remote adversarial matrix — job 781102

Status: `REMOTE_ADVERSARIAL_MATRIX_PASS / CONDITIONALLY_APPROVED`.

This record incorporates sanitized real Yoltla evidence for the technical
adversarial matrix that complements the canonical positive acceptance recorded
for job `781100`. It does not perform a scientific calculation and does not by
itself close Phase 3.

```yaml
phase: "PHASE_3"
status: "DRAFT"
source_commit: "594e0e549b64284dba8ea05573215543930e4c22"
source_tree_dirty: false
remote_tests:
  status: "PASS"
  commands:
    - "python3 verify_package.py"
    - "bash -n submit.slurm"
    - "sbatch --test-only submit.slurm"
    - "sbatch submit.slurm"
    - "sacct -j 781102"
  summary: "Job 781102 completed 0:0 in three seconds on tt[30-33]; all five adversarial cases passed."
cluster: "Yoltla / tt2d-80p / four nodes / Python technical harness"
job_ids: [781102]
package_sha256: "2c0b98923a2720a635ef3c365e6a1ac9e8498ad4dd97a4dd50c24e4e2f376201"
audit_status: "CONDITIONALLY_APPROVED"
known_limitations:
  - "This technical matrix complements, but does not replace, the canonical scientific-engine execution of job 781100."
  - "The remote post-execution directory was not retained as a raw immutable ZIP; this record is based on operator-provided sanitized accounting, stdout and structured result fixtures."
  - "Interruption recovery is an injected controller shutdown and resume within one allocation, not a Slurm-signal or cross-allocation continuation test."
  - "Disjoint hosts are verified in controller StepLaunchSpec allocation with ScriptedLauncher, not by concurrent physical MPI steps."
  - "Identified human acceptance of the Phase 3 transition remains pending."
accepted_by: "NOT_YET_ACCEPTED"
date: "2026-08-01"
```

## Verified cases

- Failed parent: the child remained `BLOCKED` and was never launched.
- Missing DM: the parent was classified `INCOMPLETE` and the child was never
  launched.
- Altered transfer hash: the child was rejected as `FAILED_BEFORE_LAUNCH`.
- Recoverable controller interruption: an injected shutdown made the first
  attempt `INTERRUPTED`; a second controller invocation in the same allocation
  completed, with two attempts recorded. This is not a Slurm-signal or
  cross-allocation continuation claim.
- Independent technical tasks: concurrent ScriptedLauncher tasks received
  disjoint controller host sets `tt30,tt31` and `tt32,tt33`. This is not a
  physical MPI-placement claim.

Slurm job `781102` and its batch step both report `COMPLETED`, exit `0:0`, on
`tt[30-33]`. The package verifier ran inside the allocation and the result identifies itself as
`REAL_REMOTE_TECHNICAL_ADVERSARIAL_EVIDENCE` with
`scientific_calculation_performed=false`.

## Evidence identity

The executed package ZIP has SHA-256
`2c0b98923a2720a635ef3c365e6a1ac9e8498ad4dd97a4dd50c24e4e2f376201`.
The repository retains the operator-provided accounting, package stdout and
structured matrix result under
[`tests/fixtures/phase3/yoltla_job_781102/`](../../tests/fixtures/phase3/yoltla_job_781102/).
The original post-execution remote directory, including raw `OUT`, `ERROR`,
case-state and event files, was not retained as an immutable evidence ZIP.
Job `781106` subsequently repeated the matrix with a complete raw immutable
post-job archive; see
[`PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md`](PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md).

Together, jobs `781100` and `781102` provide the positive and adversarial
remote engineering evidence, conditionally approved by the independent audit
of `cf62127`. The phase transition still requires identified human acceptance
under development governance.
