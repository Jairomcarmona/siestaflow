# Testing

The suite covers characterization contracts (M0), generic kernel (M1), SIESTA vertical slice (M2), remote environment acceptance (M3), and generalization/examples/docs (M3G).

```powershell
python -m pytest tests/characterization tests/unit tests/integration tests/smoke -q
python -m pytest tests/m2 -q
python -m pytest tests/m3 -q
python -m pytest tests/generalization tests/examples -q
python -m pytest tests/m3r -q
python -m pytest -q
```

Tests must use synthetic launchers and fixtures only. Generalization requires distinct arbitrary-species packages, staging, campaign generation, simulation, remote preview, and conservative import. The static audit scans central source/data for reference-only identifiers, hashes, snapshot paths, and fixed series.

Version 0.2 additionally requires tests for explicit Hydra placement, CPU and
exclusive-node packing, DAG ordering, failed-parent blocking, transfer
manifests, hash-bound gate tasks, deterministic clean-extraction packages and
read-only progress inspection.

M3R adds executed artifact tests: quoted/unquoted multi-heredoc compilation, generated SLURM execution with controlled stubs, `sacct` main-row classification, empty-queue rejection, deterministic bundle collection, pseudo-state coverage, secret/path failures and V2 reproducibility. Passing only `bash -n` is insufficient.
# M3R2 tests

Run `python -m pytest -q tests/m3r2` for parser, policy, ambiguity, human-selection, sanitized-evidence, generated-Bash, embedded-Python, and stub-runtime coverage. The full regression is `python -m pytest -q`. Real scheduler commands are deliberately excluded from local tests.

Run `python -m pytest -q -s tests/m3b1` for the `SLURM_SUBMIT_DIR` spool regression, the corrected environment-probe generator, geometry/pseudopotential identity, adapter-rendered single-point FDF, deterministic package, mutable evidence-tree handling, and ZIP tests. Final M3B1 evidence: 11 passed; full suite: 198 passed, 0 failed, 0 errors.
