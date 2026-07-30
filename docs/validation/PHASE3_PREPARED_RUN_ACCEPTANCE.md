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

Not yet accepted:

- real Yoltla execution of a package generated directly by `run prepare`;
- execution adapters for non-SIESTA task capabilities;
- automatic scheduler submission or queue selection;
- automatic scientific parameter selection;
- scientific validity inferred from normal termination.

The feature remains within version `0.2.0`. Remote evidence is required before
declaring this phase complete or changing the package version.
