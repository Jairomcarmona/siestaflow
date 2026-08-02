# Phase 3 Yoltla remote two-stage acceptance — job 781100

Status at incorporation: `REMOTE_TWO_STAGE_ACCEPTANCE_PASS / ADVERSARIAL_MATRIX_PENDING`.
Current companion status: job `781102` subsequently completed the adversarial
matrix; the formal phase transition remains pending.

This record incorporates sanitized real Yoltla evidence for the canonical
`workflow.lock.json → run prepare → run.lock.json → self-contained package`
path. It accepts the positive parent-to-DM-restart path only. The later
adversarial record is
[`PHASE3_YOLTLA_ADVERSARIAL_MATRIX_781102.md`](PHASE3_YOLTLA_ADVERSARIAL_MATRIX_781102.md);
neither record alone closes Phase 3.

```yaml
phase: "PHASE_3"
status: "DRAFT"
source_commit: "0a51e51e74decfba6de11a740c47c5770f45770a"
source_tree_dirty: false
release_candidate: "NOT_APPLICABLE"
local_tests:
  status: "PASS"
  commands:
    - "python -m compileall -q src"
    - "python -m pytest -q"
    - "git diff --check"
  summary: "352 tests passed before package generation; 353 passed after adding the deterministic remote-evidence regression."
remote_tests:
  status: "PASS"
  commands:
    - "python3 verify_package.py"
    - "sbatch --test-only submit.slurm"
    - "sbatch submit.slurm"
    - "sacct -j 781100"
    - "bash progress.sh"
  summary: "Job 781100 completed 0:0 on tt[30-33]; both tasks completed on their first attempt."
cluster: "Yoltla / tt2d-80p / ttv3,mem128 / siesta/5.4.2 / Hydra"
job_ids: [781058, 781100]
package_sha256: "e372601a5320012ae42ff5ead5776d5ec657c1013ccf02e3db31180a9b36f9e3"
workflow_lock_sha256: "bdd26b75f5a719069232499b2172fe3d1ff592a54df71d0234144a88e0e63f70"
run_lock_sha256: "5cf56deed1a3685e6292aeb9b194935bbd6937c1cea804f231b0eebc0c1beedc"
execution_profile_sha256: "0232801ef3957dcc2a296f6e89f0af24075da94fbc3aebc9d6f2716a14a8d948"
audit_status: "CONDITIONALLY_APPROVED"
known_limitations:
  - "The remote adversarial matrix for failed parent, altered hash, absent DM, recoverable interruption and independent-task non-overlap remains pending."
  - "This is technical execution acceptance, not scientific validation."
accepted_by: "NOT_YET_ACCEPTED"
date: "2026-08-01"
```

## Verified chain

- Slurm job `781100` and its batch step both report `COMPLETED`, exit `0:0`.
- The allocation used four `ttv3,mem128` nodes, `tt[30-33]`, with one MPI rank
  per node. The earlier 64-rank attempts are failure evidence showing that the
  technical fixture is too small for 64 SIESTA processes; no FDF or
  pseudopotential was changed.
- `01_parent` converged normally and produced `phase3_acceptance.DM`.
- The controller retained immutable transfer evidence and verified the source,
  evidence and pre-execution destination SHA-256 as
  `e9ef987afddcbe4ce76b8548919c5792e9214328f0dd27b0a0380d86181eed0a`.
- `02_restart_from_parent_dm` records both `dm_read_attempted=true` and
  `dm_read_succeeded=true`; SIESTA emitted
  `Attempting to read DM from file... Succeeded...`.
- Both result manifests report exit zero, normal termination, SCF convergence,
  verified artifacts and no controller termination.
- Package verification emitted `SIESTAFLOW_CONTROLLER_PACKAGE_VERIFIED` and
  `NO_LOGIN_PERSISTENT_PROCESS_REQUIRED`.

## Evidence identity

The operator-provided evidence ZIP has SHA-256
`b7935e870798bf69d258596bb2a978b44e4ab8210d8d685813eb3d367a2faa1c`.
The repository retains a sanitized, reviewable subset under
[`tests/fixtures/phase3/yoltla_job_781100/`](../../tests/fixtures/phase3/yoltla_job_781100/).
It includes both locks, the resolved profile, compatibility evidence,
accounting, campaign summary, result manifests, DM hashes, package verifier
markers and the restart-reading excerpt. Personal absolute paths are redacted;
the original ZIP remains outside Git.

This acceptance proves engineering behavior only. It makes no claim about the
scientific validity or publishability of the technical carbon fixture.
