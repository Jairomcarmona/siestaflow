# Installation

Requirements: Python 3.11+, a writable local workspace, and PowerShell or a POSIX shell for the shown commands. No SIESTA, MPI, SSH, or scheduler installation is needed for local tests.

```powershell
cd PATH_TO_SIESTAFLOW
python -m pip install -e .
python -m siestaflow.cli --help
python -m pytest -q
```

Expected: installation succeeds, help exits `0`, and tests report no failures. Without installation, prefix commands with `$env:PYTHONPATH="src"` in PowerShell.
