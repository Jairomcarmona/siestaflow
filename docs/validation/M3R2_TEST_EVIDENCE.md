# M3R2 test evidence

The M3R2 suite covers all four valid `sacctmgr` forms, missing-account diagnostics, default-marker normalization, `scontrol` restriction kinds, unique/multiple/no-default outcomes, DOWN partitions, account/QoS rejection, node and walltime incompatibility, valid and unsupported human selection, and the sanitized remote fixture.

The runtime path parses that fixture, resolves the unique default, writes `scheduler_selection.json`, validates Bash and embedded Python, executes the generated non-scientific script with local SLURM environment stubs, and reads its scheduler summary. Required markers: `ACCOUNT_WIDE_ASSOCIATION_RUNTIME_PASS`, `DEFAULT_PARTITION_RESOLUTION_RUNTIME_PASS`, and `GENERATED_SLURM_RUNTIME_PASS`.

Final local evidence on 2026-07-21, using the established milestone accounting: M0 11/11, M1 63/63, M2 39/39, M3 15/15, M3G 9/9, M3R 32/32, M3R2 18/18; combined 187 passed, 0 failed, 0 errors. The clean-extracted V3 verifier emitted all three package verification markers. The context corpus matched all 642 ZIP members byte-for-byte.
