# Phase 3 technical transition acceptance — 2026-08-01

This is the new phase-acceptance record required by governance. It does not
rewrite the historical positive-run, adversarial, or audit-remediation records.

```yaml
phase: "PHASE_3"
status: "ACCEPTED"
source_commit: "17630d924e6fc58d26f5dd5ae4d6f66724a777f7"
source_tree_dirty: false
release_candidate: "NOT_APPLICABLE"
local_tests:
  status: "PASS"
  commands:
    - "git diff --check"
    - "python -m compileall -q src"
    - "python -m pytest -q"
  summary: "355 passed at the evidence-remediation cut."
remote_tests:
  status: "PASS"
  commands:
    - "canonical run prepare package; sbatch submit.slurm; sacct -j 781100; bash progress.sh"
    - "adversarial evidence package; sbatch; sacct -j 781106"
    - "scancel --signal=USR1 --batch 781111; resume in fresh allocation 781113"
    - "physical concurrent srun placement; sacct -j 781115"
  summary: "Positive parent-to-DM-to-child execution, five adversarial cases, real Slurm signal/recovery, and physical disjoint placement all passed on Yoltla."
cluster: "Yoltla / tt2d-80p / ttv3,mem128 / siesta/5.4.2"
job_ids: [781058, 781100, 781106, 781111, 781113, 781115]
package_sha256: "e372601a5320012ae42ff5ead5776d5ec657c1013ccf02e3db31180a9b36f9e3"
workflow_lock_sha256: "bdd26b75f5a719069232499b2172fe3d1ff592a54df71d0234144a88e0e63f70"
run_lock_sha256: "5cf56deed1a3685e6292aeb9b194935bbd6937c1cea804f231b0eebc0c1beedc"
execution_profile_sha256: "0232801ef3957dcc2a296f6e89f0af24075da94fbc3aebc9d6f2716a14a8d948"
audit_status: "CONDITIONALLY_APPROVED; RUNTIME_REMEDIATIONS_EVIDENCED"
known_limitations:
  - "This is engineering acceptance only; it does not validate scientific results or publishability of the carbon fixture."
  - "The retained local prepared ZIP recalculates to package_sha256, but a primary sha256sum made on the remote upload immediately before job 781100 was not retained."
accepted_by: "Jairo Carmona (human acceptance declared in Codex on 2026-08-01)"
date: "2026-08-01"
```

## Acceptance basis

- Job `781100` completed the canonical four-node `workflow.lock.json → run
  prepare → run.lock.json → package` path. The parent produced the DM, the
  controller verified its SHA-256 transfer, and the child confirmed SIESTA
  restart-DM reading before completing.
- Job `781106` retained raw remote evidence for all five adversarial cases:
  failed-parent blocking, absent-DM prevention, altered-hash prevention,
  logical disjoint host allocation, and interruption recovery.
- Jobs `781111` and `781113` demonstrated a real Slurm `SIGUSR1` shutdown and
  recovery in a separate allocation.
- Job `781115` demonstrated physical concurrent `srun` placement on disjoint
  host sets.

The evidence archives and their manifest checks are retained under
[`tests/fixtures/phase3/yoltla_audit_remediations/`](../../tests/fixtures/phase3/yoltla_audit_remediations/).
The detailed source records remain
[`PHASE3_YOLTLA_REMOTE_ACCEPTANCE_781100.md`](PHASE3_YOLTLA_REMOTE_ACCEPTANCE_781100.md),
[`PHASE3_YOLTLA_ADVERSARIAL_MATRIX_781102.md`](PHASE3_YOLTLA_ADVERSARIAL_MATRIX_781102.md),
and
[`PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md`](PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md).

## Scope statement

Phase 3 is closed as the Backbone's technical executor phase. The acceptance
does not promote the repository version, create a tag, send a push, or close
the separate scientific-validation work. The next technical phase is the
canonical adaptive-DAG work of Phase 4.
