# Quick start

Check the local execution environment without submitting anything:

```powershell
python -m siestaflow.cli environment check --siesta siesta --launcher auto --json
```

Preview a project package from explicit scientific inputs:

```powershell
python -m siestaflow.cli project init .work\my_project `
  --project-id my_project `
  --title "My SIESTA project" `
  --system-id my_system `
  --fdf C:\inputs\system.fdf `
  --structure C:\inputs\system.xyz `
  --pseudo-manifest C:\inputs\manifest.yaml `
  --dry-run --json
```

Remove `--dry-run` only after reviewing the findings. Initialization never
chooses scientific parameters and the generated campaign remains
preparation-only.

Inspect, validate, and simulate the generic example locally:

```powershell
python -m siestaflow.cli examples list --json
python -m siestaflow.cli examples inspect generic/minimal_siesta_smoke --json
python -m siestaflow.cli examples validate generic/minimal_siesta_smoke --json
python -m siestaflow.cli --workspace .work examples run generic/minimal_siesta_smoke --campaign-id smoke --json
```

Expected exit code is `0`; the final decision is `PASS`, `synthetic` is true, and there is no real-execution claim. Remove `.work` only when you no longer need its local evidence.
