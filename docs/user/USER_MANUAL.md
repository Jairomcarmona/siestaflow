# User manual

## Evidence vocabulary

`LOCAL` means a local parser, validator, renderer, or filesystem action. `SIMULATED` means a synthetic launcher produced test evidence. `PREVIEW` is inert output requiring configuration and human authorization. `REMOTE_EVIDENCE_PENDING` means no acceptable remote bundle has been imported. `REMOTE_VERIFIED` is reserved for a real, complete, hash-valid environment bundle. `SCIENTIFICALLY_AUTHORIZED` requires a separate explicit authorization and is not implied by any technical pass.

## Project packages

A package can live anywhere and contains `project.yaml`, `systems/`, `structures/`, `pseudopotentials/manifest.yaml`, `campaigns/`, `policies/`, `authorizations/`, and `expected_contracts/`. Schema `1.0` accepts arbitrary species strings. Paths are package-relative and traversal is rejected.

Create one from explicit existing inputs:

```powershell
python -m siestaflow.cli project init projects/my_package `
  --project-id my_package `
  --title "My package" `
  --system-id system_01 `
  --fdf source/system.fdf `
  --structure source/system.xyz `
  --pseudo-manifest source/manifest.yaml `
  --dry-run --json
```

Initialization validates before writing, preserves source bytes and records
their hashes. A matching rerun is idempotent; a different request against the
same destination is rejected. The generated campaign is preparation-only and
cannot authorize real execution. Structure chemistry still requires explicit
researcher review.

## Environment and explainable input checks

```powershell
python -m siestaflow.cli environment check --siesta siesta --launcher auto --json
python -m siestaflow.cli input validate source/system.fdf `
  --pseudo-manifest source/manifest.yaml --require-pseudos `
  --profile source/validation-profile.json --explain --json
python -m siestaflow.cli input rules --engine-version 5.4.2
python -m siestaflow.cli workflow preflight source/workflow.json `
  --profile source/validation-profile.json --json
```

Both commands use the Core Contracts validation report. Findings expose stable
rule identifiers, severity, scope, evidence and remediation. Environment
checking is operational only: it does not validate the chemistry, numerical
settings, scalability or scientific suitability of a calculation.

The SIESTA 5.4.2 contextual validator distinguishes deterministic failures
from physical or cost reviews. A strict external profile declares periodicity,
required Bader output and project review limits; no such choice is inferred.
See `SIESTA_VALIDATION_GUIDE.md` for the profile schema, registered rule
families and explicit scientific limits.

## Allocation-controller campaigns

Schema `2.0` is the real execution contract. It declares the selected SLURM
profile, launcher, immutable inputs, resources, tasks, dependency edges,
parent transfers and required outputs.

A `gate` task is a one-process, hash-bound decision program. It can consume
verified parent artifacts and emit a required decision artifact. This is the
extension point for project-specific convergence and routing logic.

Package without submission:

```powershell
python -m siestaflow.cli remote controller-package campaign/campaign.json --output packages --json
```

Inspect locally or on Yoltla:

```bash
python3 verify_package.py
./progress.sh
```

```powershell
python -m siestaflow.cli project inspect projects/my_package --json
python -m siestaflow.cli project validate projects/my_package --json
python -m siestaflow.cli project load projects/my_package --json
```

## Declarative campaigns

Campaign files declare a system, task type, optional FDF parameter, any authorized value list, policy, authorization, mode, and `synthetic_only`. Create and run a local definition:

```powershell
python -m siestaflow.cli --workspace .work campaign create --project projects/my_package --campaign-id cutoff_sweep --dry-run --json
python -m siestaflow.cli --workspace .work campaign create --project projects/my_package --campaign-id cutoff_sweep --json
python -m siestaflow.cli --workspace .work campaign validate cutoff_sweep --json
python -m siestaflow.cli --workspace .work campaign simulate cutoff_sweep --json
python -m siestaflow.cli --workspace .work campaign status cutoff_sweep --json
```

Dry-run creates no files. Simulation is synthetic and stops on non-pass gates.

## Pseudopotentials and examples

Manifest entries provide species, filename, format, optional SHA-256, provenance, and distribution state. Staging searches recursively, requires one readable file per entry, checks format/hash, and uses the explicit `copy` or `link` policy. It never downloads or substitutes files.

```powershell
python -m siestaflow.cli examples stage generic/minimal_siesta_smoke --pseudo-root pseudos --output .work/pseudos --policy copy --dry-run --json
python -m siestaflow.cli examples package generic/minimal_siesta_smoke --output .work\archives --dry-run --json
```

See `QUICK_START.md` for a complete executable local example and `REMOTE_VALIDATION_WORKFLOW.md` for preview/import boundaries.

## M3 remote probe revision

Only package revision V2 is usable. V1 was never executed remotely, but local M3 tests previously checked Bash syntax and hashes without compiling nested Python; two rendered heredocs were therefore invalid. V2 validates direct Python, Bash, SLURM and every Python heredoc before use, then executes generated artifacts in local stub integration tests. Before transfer, verify the canonical package:

```powershell
python remote_validation\M3_YOLTLA_ENVIRONMENT_PROBE\verify_local_package.py
```

Expected output is exactly the three `M3_PACKAGE_*_VERIFIED` markers. It is not a remote-execution pass.
