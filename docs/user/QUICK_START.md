# Quick start

Inspect, validate, and simulate the generic example locally:

```powershell
python -m siestaflow.cli examples list --json
python -m siestaflow.cli examples inspect generic/minimal_siesta_smoke --json
python -m siestaflow.cli examples validate generic/minimal_siesta_smoke --json
python -m siestaflow.cli --workspace .work examples run generic/minimal_siesta_smoke --campaign-id smoke --json
```

Expected exit code is `0`; the final decision is `PASS`, `synthetic` is true, and there is no real-execution claim. Remove `.work` only when you no longer need its local evidence.
