# Phase 3 prepared-run vertical acceptance

Status: `REMOTE_RUNTIME_DEBT_REMEDIATED_HUMAN_DECISION_PENDING`.

The implemented slice connects the deterministic workflow DAG to the existing
persistent-allocation controller without granting execution authority.

Accepted locally:

- strict loading and checksum verification of `workflow.lock.json`;
- strict, external, cluster-specific Slurm execution profile;
- external artifact size and SHA-256 verification;
- fail-closed SIESTA FDF preflight;
- allocation-fit and MPI-placement checks;
- exact preservation of declared input destinations;
- compilation of artifact edges into hash-bound controller transfers;
- deterministic `siestaflow.run-lock@1.0` provenance;
- self-contained directory and ZIP generation;
- immutable package inspection and identity cross-checks;
- validated read-only status and resubmission planning;
- no `sbatch`, SSH, or login-node daemon invocation during preparation,
  inspection, status, or resume planning.
- capability snapshots from read-only Slurm discovery or imported evidence;
- deterministic candidates, explicit manual overrides, and human confirmation
  persisted in the compatible run-lock metadata;
- coherence verification across the resolution, resolved profile, campaign and
  generated `submit.slurm`.

Accepted remotely:

- canonical `run prepare` package execution on Yoltla as job `781100`;
- Hydra MPI placement across `tt[30-33]` with one rank per node;
- parent normal termination and SCF convergence;
- parent DM production and immutable SHA-256-bound transfer evidence;
- child restart with `dm_read_attempted=true` and `dm_read_succeeded=true`;
- child normal termination and SCF convergence;
- final reconciliation as `COMPLETED`, `2/2`, with Slurm exit `0:0`.

The primary record is
[`PHASE3_YOLTLA_REMOTE_ACCEPTANCE_781100.md`](PHASE3_YOLTLA_REMOTE_ACCEPTANCE_781100.md).

Remote adversarial acceptance:

- job `781102` completed `0:0` on `tt[30-33]`;
- failed parent and absent DM blocked the child without launching it;
- an altered transfer hash failed before child launch;
- an interrupted controller attempt resumed and completed within the same
  allocation after an injected shutdown request;
- independent concurrent technical tasks received disjoint two-node host sets;
- the technical harness performed no scientific calculation.

The adversarial record is
[`PHASE3_YOLTLA_ADVERSARIAL_MATRIX_781102.md`](PHASE3_YOLTLA_ADVERSARIAL_MATRIX_781102.md).
Its independent audit is
[`PHASE3_INDEPENDENT_AUDIT_CF62127.md`](PHASE3_INDEPENDENT_AUDIT_CF62127.md).
The remediation record is
[`PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md`](PHASE3_YOLTLA_AUDIT_REMEDIATIONS_781106_781115.md).

Not yet accepted:

- formal Phase 3 transition pending identified human acceptance of the
  remediated technical evidence;
- execution adapters for non-SIESTA task capabilities;
- automatic scheduler submission or queue selection;
- automatic scientific parameter selection;
- scientific validity inferred from normal termination.

For flexible resources, use only the canonical bridge. The selection is never
stored in `workflow.lock.json`:

```bash
siestaflow run snapshot-import --cluster-id <cluster> --sjstat sjstat-c.txt \
  --output cluster-snapshot.json --json
siestaflow run candidates --workflow workflow.lock.json \
  --profile execution-profile.json --snapshot cluster-snapshot.json --json
siestaflow run prepare workflow.lock.json --source-root source \
  --profile execution-profile.json --snapshot cluster-snapshot.json \
  --candidate <candidate-id> --confirm --output package --run-id <run-id> --json
```

`--partition`, `--nodes`, `--ranks-per-node`, `--account`, `--qos` and
`--walltime` provide a fully explicit alternative, also requiring `--confirm`.
Neither mode executes `sbatch`; unknown authorization stays visible for remote
`sbatch --test-only` review.

The feature remains within version `0.2.0`. Positive and adversarial remote
engineering evidence have remediated their identified runtime debt; the
complete phase remains open until human phase-transition acceptance is
recorded.
