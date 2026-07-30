# Developer guide

Add a new project by creating an external schema `1.0` package; do not edit Python. Use JSON-compatible YAML when no PyYAML dependency is desired. All paths must be relative, and every campaign references declared systems, authorizations, and policies.

For a new generic feature, preserve dry-run zero effects, refuse overwrite, record hashes/provenance, and keep synthetic/real evidence separate. Public classes include `ProjectPackageLoader`, `SiestaCampaignFactory`, `PseudopotentialStager`, `GateRegistry`, `ExampleRegistry`, and `ExampleService`.

Run:

```powershell
python -m pytest -q
python -m siestaflow.cli --help
python -m siestaflow.cli examples validate generic/minimal_siesta_smoke --json
```

Follow the documentation update policy in `CONTRIBUTING.md` before declaring a milestone complete.
