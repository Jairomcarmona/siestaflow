# Developer guide

Add a new project by creating an external schema `1.0` package; do not edit Python. Use JSON-compatible YAML when no PyYAML dependency is desired. All paths must be relative, and every campaign references declared systems, authorizations, and policies.

For a new generic feature, preserve dry-run zero effects, refuse overwrite, record hashes/provenance, and keep synthetic/real evidence separate. Public classes include `ProjectPackageLoader`, `SiestaCampaignFactory`, `PseudopotentialStager`, `GateRegistry`, `ExampleRegistry`, and `ExampleService`.

New engines, validators, launchers, artifact processors, schedulers, and
postprocessors must depend on `qraft.contracts`. Register capabilities
explicitly through `CapabilityRegistry`; do not add import-time global
registration. Use namespaced identifiers and declare input/output contract
versions. Integration adapters belong outside `qraft.contracts`.

Contract changes follow `docs/design/CORE_CONTRACTS_1_0.md`. A new software
implementation version does not imply a new contract version.

Run:

```powershell
python -m pytest -q
python -m qraft.cli --help
python -m qraft.cli examples validate generic/minimal_siesta_smoke --json
```

Follow the documentation update policy in `CONTRIBUTING.md` before declaring a milestone complete.
