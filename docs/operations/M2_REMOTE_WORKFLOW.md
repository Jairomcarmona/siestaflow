# M2 remote preview (historical capability, current CLI)

Create a campaign definition from any external package, then render an inert remote preview:

```powershell
python -m siestaflow.cli --workspace .work campaign create --project C:\projects\package --campaign-id smoke --json
python -m siestaflow.cli --workspace .work remote package smoke --output .work\remote --dry-run --json
```

The package contains no pseudopotential binary and never invokes `sbatch`. It preserves manifest-declared external filename/hash requirements, null cluster fields, input hash, preflight, SLURM preview, inspection/collection scripts, and checksums. A human must configure and authorize every remote action.

`remote results import` validates identity, files, and checksums, preserves the original bundle, and parses output. Synthetic bundles always retain `real_evidence_promoted: false`. See `REMOTE_VALIDATION_WORKFLOW.md` for the maintained workflow.
