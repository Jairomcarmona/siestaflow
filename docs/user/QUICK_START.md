# Quick start

Check the local execution environment without submitting anything:

```powershell
python -m qraft.cli environment check --siesta siesta --launcher auto --json
```

Inspect the versioned SIESTA rules and validate an input without editing it:

```powershell
python -m qraft.cli input rules --engine-version 5.4.2
python -m qraft.cli input validate inputs/system.fdf --explain
python -m qraft.cli workflow preflight inputs/workflow.json --json
```

`REVIEW` is an alert for researcher judgment; only `FAIL` or `BLOCKED`
returns exit `2`. None of these commands runs SIESTA or submits a job.

Preview a project package from explicit scientific inputs:

```powershell
python -m qraft.cli project init .work\my_project `
  --project-id my_project `
  --title "My SIESTA project" `
  --system-id my_system `
  --fdf inputs/system.fdf `
  --structure inputs/system.xyz `
  --pseudo-manifest inputs/manifest.yaml `
  --dry-run --json
```

Remove `--dry-run` only after reviewing the findings. Initialization never
chooses scientific parameters and the generated campaign remains
preparation-only.

Inspect, validate, and simulate the generic example locally:

```powershell
python -m qraft.cli examples list --json
python -m qraft.cli examples inspect generic/minimal_siesta_smoke --json
python -m qraft.cli examples validate generic/minimal_siesta_smoke --json
python -m qraft.cli --workspace .work examples run generic/minimal_siesta_smoke --campaign-id smoke --json
```

Expected exit code is `0`; the final decision is `PASS`, `synthetic` is true, and there is no real-execution claim. Remove `.work` only when you no longer need its local evidence.
