# M3R test evidence

Local M3R suite: `32 passed`, `0 failed`, `0 errors`.

Covered gates:

- direct Python compilation and package `py_compile` execution;
- Bash and SLURM `bash -n`;
- quoted/unquoted multiple Python heredocs, valid and invalid;
- generated SLURM execution with stubs and JSON assertions;
- inspector execution for RUNNING, COMPLETED, FAILED, missing, TIMEOUT, NODE_FAIL and unknown states;
- exact main-job selection ahead of `.batch`/`.extern` and all nine terminal states;
- complete/incomplete/preexisting bundle paths and normalized archive metadata;
- correct/missing/mismatched/invalid/duplicate/nonexistent/unreadable pseudo fixtures;
- obvious secret and checksum traversal rejection;
- V2 reproducibility and manifest revision;
- full synthetic local runtime demonstration.

Canonical V2 package verification output:

```text
M3_PACKAGE_HASHES_VERIFIED
M3_PACKAGE_RUNTIME_SYNTAX_VERIFIED
M3_PACKAGE_STRUCTURE_VERIFIED
```

Artifacts:

- Package manifest: `remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE/probe_manifest.json`
- Manifest SHA-256: `df2fac529a10b653b3ae816c02e69e63c64057df19d2a46fbded49c5fb87e1c4`
- Root checksum-manifest SHA-256: `bb6d4bf0f90740c4c99bcb2b3f8cd9bbfe2eaf7cfa2cb967cc31873a4d6ff429`
- Upload ZIP SHA-256: `f69cd9011e81d04747519e098e777f56031ea272ff475fd2eb73b27e36c6c12a`
- ZIP reproducibility check: byte-identical regeneration PASS.

Regression record:

```text
M0: 11 passed
M1: 63 passed
M2: 39 passed
M3: 15 passed
M3G: 9 passed
M3R: 32 passed
COMBINED: 169 passed
FAILED: 0
ERRORS: 0
CONTEXT: 642/642 byte-identical files
```
