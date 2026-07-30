# M3G examples test evidence

The public `ExamplePackage` surface discovers two schema `1.0` packages: `generic/minimal_siesta_smoke` and `reference_projects/birnessite_mn_o`. Both inspect and validate. Reproducible ZIP packaging fixes timestamps and ordering; dry-run writes nothing.

The parametrized end-to-end test creates two additional external packages at runtime:

| Project | Species | Authorized series | Result |
|---|---|---|---|
| PROJECT_ALPHA (`ALPHA_XY`) | X/Y | 175, 265 Ry | load, validate, stage, render variants/preview, simulate, gate, import: PASS |
| PROJECT_BETA (`BETA_ABC`) | A/B/C | 140, 220, 410 Ry | load, validate, stage, render variants/preview, simulate, gate, import: PASS |

Each project uses separately hashed synthetic PSML fixtures, exactly one simulated allocation, arbitrary task counts, and a synthetic result bundle that remains explicitly non-real. No source change occurs between cases.

Staging evidence covers `EXAMPLE_READY`, missing files, wrong hashes, clean destination, explicit copy policy, format/readability, and final `staging_manifest.json`. Example tests also prove missing/hash failure and dry-run zero effects.

Command:

```powershell
python -m pytest tests/generalization tests/examples -q
```

Recorded result: `9 passed`; no failures.
