# Phase 3 prepared-run vertical acceptance

Status: `LOCAL_VERTICAL_PASS_REMOTE_ACCEPTANCE_PENDING`.

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

Not yet accepted:

- real Yoltla execution of a package generated directly by `run prepare`;
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

The feature remains within version `0.2.0`. Remote evidence is required before
declaring this phase complete or changing the package version.
