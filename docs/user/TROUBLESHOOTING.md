# Troubleshooting

- Exit `2` with `MISSING_DIRECTORY` or `MISSING_*`: fix the external package path or manifest; no partial package is loaded.
- `EXAMPLE_BLOCKED_MISSING_PSEUDOS`: provide exactly one matching filename below `--pseudo-root`.
- `EXAMPLE_BLOCKED_HASH_MISMATCH`: do not replace or download automatically; verify provenance and update only the authorized external manifest.
- `EXAMPLE_BLOCKED_INVALID_MANIFEST`: correct format, readability, schema, or path-safety findings.
- Campaign authorization mismatch: ensure its file includes the declared task type and system target.
- Existing destination: choose a clean workspace; the tools refuse overwrite.
- Remote import review: synthetic evidence, missing terminal accounting, and unknown warnings intentionally prevent acceptance.

All errors are printed as `SIESTAFLOW_ERROR: ...`. Re-run with `--json` where available for machine-readable findings.

- Any V1 probe directory or ZIP is unusable. Rename/delete it and transfer V2 as a complete unit; never patch or mix individual files.
- `EMBEDDED_PYTHON_SYNTAX_ERROR`: use the reported file/start/error line; do not bypass the validator.
- `GENERATED_SCHEDULER_SCRIPT_INVALID`: the temporary candidate was removed; preserve diagnostics and do not submit.
- Empty `squeue` with no main-job `sacct` row is incomplete evidence, never success.
- `PACKAGE_SECRET_FAILURE` reports the exact file/line. Remove the credential from the source environment and regenerate; do not edit checksums manually.
# M3R2 scheduler selection messages

- `SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS`: more than one compatible default; provide an evidence-backed human selection after review.
- `SCHEDULER_PROBE_REQUIRES_HUMAN_SELECTION`: candidates exist but no unique default exists.
- `SCHEDULER_PROBE_BLOCKED_NO_COMPATIBLE_PARTITION`: visible/policy/resource evidence yields no candidate.
- `USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE`: at least one supplied account/partition/QoS value does not match a candidate exactly.
