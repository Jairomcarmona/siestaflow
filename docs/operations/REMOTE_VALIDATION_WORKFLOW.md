# Remote validation workflow

The implemented sequence is `LOCAL definition → PREVIEW package → human transfer/configuration/authorization → remote action outside Codex → hashed bundle → LOCAL conservative import`. QRAFT itself does not call SSH or submit jobs.

For the M3 environment probe, package revision V2 is mandatory. Its verifier additionally compiles nested Python and validates structure/secrets/paths. V1 must be discarded because hash and `bash -n` checks alone did not detect its invalid heredocs.

```powershell
python -m qraft.cli --workspace .work remote package cutoff_sweep --output .work\remote --dry-run --json
python -m qraft.cli --workspace .work remote results import evidence/results --campaign-id cutoff_sweep --output .work/imports/cutoff_sweep --dry-run --json
```

Expected package state is `PREVIEW_WITH_UNVERIFIED_PROFILE`. A synthetic result can validate parser/gate behavior but always records `SYNTHETIC_BUNDLE_NOT_REAL_EVIDENCE`. Scientific authorization is independent.
# M3R2 evidence-bound scheduler selection

The V3 flow is `association → visible partitions → partition policy → compatible candidates → unique default or human review`. `AllowAccounts=ALL` only removes a partition restriction for an already observed account; it does not establish an association. Missing/N/A policy evidence is conservatively incompatible. Re-running the login probe in a clean V3 directory is the preferred reuse path; do not manually copy evidence between revisions.
