# M3R runtime defect audit

Scope: all ten requested V1 script surfaces plus the new embedded-Python validator and their generator source in `src/siestaflow/remote_environment.py`.

Defect A was reproduced: V1 `inspect_probe_job.sh` split `+'\n'` into an unterminated Python string. Defect B was reproduced at the nested-render boundary: the outer Python string consumed the newline escape before writing the generated SLURM heredoc. Both were source-generation defects; editing V1 alone would not have fixed regeneration.

Corrections follow `source → regenerate → compile → stub runtime → evidence validation`:

- The inspector emits valid UTF-8 JSON, explicitly selects the exact main job row and ignores `.batch`/`.extern` as decision rows.
- Terminal `sacct` states are COMPLETED, FAILED, CANCELLED, TIMEOUT, NODE_FAIL, OUT_OF_MEMORY, PREEMPTED, BOOT_FAIL and DEADLINE. Unknown states set `review_required=true`; empty `squeue` never means success.
- The generator writes a temporary candidate, runs `bash -n` and compile-only heredoc validation, and atomically publishes only a valid artifact. Failure reports `GENERATED_SCHEDULER_SCRIPT_INVALID` and removes the candidate.
- The package verifier checks checksums, manifest/hash/coverage, required files, safe relative paths, symlinks, obvious secret assignments/private-key blocks, direct Python, Bash, SLURM and embedded Python.
- The collector requires summaries and both log channels, rejects symlinks/traversal/overwrite, normalizes uid/gid/mtime and gzip mtime, and removes staging after success.
- The pseudo verifier distinguishes missing, mismatch, review and verified without copying or changing a pseudopotential.

Audit totals: 2 confirmed runtime defects and 16 additional non-style findings (5 security, 2 portability, 4 observability; categories overlap). All non-style findings were corrected. One dense-formatting finding remains `STYLE_ONLY`. The per-component evidence and tests are machine-readable in `M3R_RUNTIME_DEFECT_AUDIT.json`.
