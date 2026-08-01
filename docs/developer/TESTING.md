# Testing

The default regression is scheduler-independent and must pass from the
repository root:

```bash
python -m pytest -q
```

Use focused suites while iterating, then run the full regression before
integration:

```bash
python -m pytest -q tests/contracts tests/workflows tests/runs
python -m pytest -q tests/characterization tests/unit tests/integration
python -m pytest -q tests/m2 tests/m3 tests/m3r tests/m3r2
python -m pytest -q tests/m3b1 tests/m3b1r tests/m4
python -m pytest -q tests/generalization tests/examples tests/smoke
```

Tests use synthetic launchers and sanitized fixtures unless a suite explicitly
declares an external layer. Generated Bash/Slurm packages require more than
syntax checks: execute controlled stubs, validate embedded Python, verify
manifests and test unsafe paths, hashes, terminal states and reproducibility.

Historical acceptance files may contain the test count observed at their own
cut. Do not update those records merely because the suite grows and do not use
their count as current evidence.

## Optional real local Slurm layer

The opt-in WSL2 sandbox under `integration/local_slurm/` exercises a real
single-node Slurm installation:

```powershell
wsl -d Ubuntu -u root --exec bash integration/local_slurm/bootstrap_wsl.sh
wsl -d Ubuntu --exec bash integration/local_slurm/run_acceptance.sh
powershell -ExecutionPolicy Bypass -File `
  integration/local_slurm/run_controller_acceptance.ps1
```

Only bootstrap changes the WSL installation. A successful run is
`LOCAL_SLURM_INTEGRATION_PASS`, not Yoltla acceptance or scientific validation.
See
[`LOCAL_SLURM_WSL_ACCEPTANCE.md`](../validation/LOCAL_SLURM_WSL_ACCEPTANCE.md)
for the recorded scope and limitations.

## Reporting

Classify every required check as `PASS`, `FAIL`, `SKIPPED` or
`BLOCKED_BY_EXTERNAL_CONTEXT`. Record the command, exit code, relevant version
and numeric summary. A phase-closing run uses
[`PHASE_ACCEPTANCE_TEMPLATE.md`](../validation/PHASE_ACCEPTANCE_TEMPLATE.md).
