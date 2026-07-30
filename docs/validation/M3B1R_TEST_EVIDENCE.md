# M3B1R correction evidence

Date: 2026-07-21

The V1 clean-extraction failure was reproduced before implementation: its
manifest stored a Windows absolute geometry source and the POSIX verifier used
that value as a packaged filename. The initial M3B1R regression run reported
14 failures. V2 uses only validated `packaged_path` values for file access and
keeps repository-relative provenance separately.

The corrected package is inert. Login discovery writes a hashed
`runtime_candidates.json`; `prepare_smoke_job.py` consumes only that evidence
and blocks absent, ambiguous, unobserved, non-`srun`, or non-MPI selections.
Only a confirmed MPI SIESTA plus observed `srun` can generate the 20-task,
10-minute Yoltla SLURM file. USR1 is trapped before the worker and records the
signal without declaring success or voluntarily terminating the job.

The result summarizer bundles and reuses `SiestaOutputParser`. It distinguishes
normal converged, normal nonconverged, input, pseudopotential, MPI, filesystem,
time-limit, and unknown termination; exit code zero alone is not success.

Verification results:

- Full suite: `221 passed`, `0 failed` in 37.12 seconds.
- M3B1R subset: `23 passed`, `0 failed` in 5.24 seconds.
- Clean ZIP extraction with the verifier launched from `/tmp` under Linux
  (WSL, Python 3.12.3), outside the source repository: exit code 0 and
  `CLEAN_LINUX_EXTRACTION_VERIFICATION_PASS`.
- Reproducibility: two independent builds were byte-identical.
- Distributed absolute-path scan: zero occurrences of the forbidden host-path
  prefixes.
- ZIP entries: 22; preselected SLURM entries: 0.

Preserved scientific hashes:

- Geometry: `870d92a224662755c3d10ad9d45c4b212a6b4c23f3966558c05cd929cea5c9fb`
- C.psml: `ce0f6a7fd43e70d44018e94286d934e9caadc005e95da87500d85fbe501d4c41`
- smoke.fdf: `386c83e2f0a9cb3cfb0b0f5de0d02626af9e594bd353c295af1d571f7887aa1e`

Artifact:

- `remote_validation/M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE_V2_UPLOAD.zip`
- SHA-256: `f031fa2c3201ced34d2da7c95a1188e687a27a9c9ae29fb8d85300b511027921`
- Size: 45,740 bytes

No SSH, remote SIESTA, SLURM, or `sbatch` action was performed. The permitted
workflow stops after review of the generated SLURM file.
