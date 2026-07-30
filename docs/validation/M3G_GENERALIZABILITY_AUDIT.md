# M3G generalizability audit

Date: 2026-07-20. Scope: `src/siestaflow/`, external package boundaries, examples, CLI, and generated-preview compatibility. No real engine, MPI, SSH, scheduler, or submission command was run.

| Coupling found | Initial class | Resolution | Final class |
|---|---|---|---|
| Snapshot path and M1 template defaults in CLI | BLOCKING_HARDCODING | Replaced by `--project` plus declarative campaign ID | CONFIGURATION_ONLY |
| Fixed campaign IDs, target, species manifest, and convergence series | BLOCKING_HARDCODING | Moved into the reference ProjectPackage | REFERENCE_EXAMPLE_ONLY |
| Fixed Mesh/k-grid value registries in the variant generator | REFACTOR_REQUIRED | Values now come exclusively from signed authorization data; syntax only is generic | CONFIGURATION_ONLY |
| Packaged Mn/O pseudopotential manifest under the adapter | BLOCKING_HARDCODING | Deleted; audited data is in the reference example | REFERENCE_EXAMPLE_ONLY |
| Fixed remote-preview pseudo hashes and shell checks | REFACTOR_REQUIRED | Rendered from an optional arbitrary manifest | CONFIGURATION_ONLY |
| Fixed environment-probe species, evaluator fields, statuses, and script | BLOCKING_HARDCODING | Replaced with an arbitrary filename/hash mapping and `entries` evidence | CONFIGURATION_ONLY |
| Registry prose declaring one mandatory numerical series | REFACTOR_REQUIRED | Reworded as project-authorization policy | CONFIGURATION_ONLY |
| Regression fixtures importing project-specific factory constants | REFACTOR_REQUIRED | Tests load the reference package through the public schema | REFERENCE_EXAMPLE_ONLY |

All eight coupling areas were corrected. Remaining project strings and audited hashes are data/documentation/reference artifacts, not imported central logic. The static test parses Python AST constants/default collections and scans source/data for project identifiers, audited hashes, snapshot paths, and the rigid four-value series.

Acceptance evidence:

```text
CORE_PROJECT_AGNOSTIC
ENGINE_ADAPTER_PROJECT_AGNOSTIC
ARBITRARY_SPECIES_MANIFEST_PASS
EXTERNAL_PROJECT_PACKAGE_PASS
DECLARATIVE_CAMPAIGN_PASS
EXTENSIBLE_GATES_PASS
REFERENCE_PROJECT_ISOLATED
NO_PROJECT_SPECIFIC_HARDCODING
```

Regression record: M0 `11 passed`; M1 `63 passed`; M2 `39 passed`; M3 `15 passed`; M3G `9 passed`; combined `137 passed`. The archive comparison test confirmed `context/` remains exactly 642/642 byte-identical files. Failed tests: 0. Real SIESTA executions: 0.
