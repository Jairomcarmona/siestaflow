# Scientific governance

Technical readiness is not scientific approval. The statuses are deliberately distinct:

- `LOCAL`: inspected or validated locally.
- `SIMULATED`: synthetic launcher only.
- `PREVIEW`: inert package or renderer output.
- `REMOTE_EVIDENCE_PENDING`: acceptable remote evidence is absent.
- `REMOTE_VERIFIED`: real environment evidence passed identity, checksum, completeness, and terminal-evidence checks.
- `SCIENTIFICALLY_AUTHORIZED`: a separate human authorization permits the specified scientific operation.

No current M3G example is `SCIENTIFICALLY_AUTHORIZED`. Reference-package policies may describe project gates, but the generic gate engine does not implement or infer project science. Unknown warnings, incomplete series, missing artifacts, absent SCF convergence, and missing human review fail or block according to explicit evidence.

Every new state or gate must update this document and `CHANGELOG.md`.
