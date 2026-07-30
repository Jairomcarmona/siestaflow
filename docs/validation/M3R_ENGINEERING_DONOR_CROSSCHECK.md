# M3R engineering donor cross-check

Donor reviewed read-only: `context/donor/qe-postprocess-framework`. It was treated as `ENGINEERING_DONOR`, never as architectural/scientific authority, copy source, or runtime dependency. No donor file or command was modified or executed.

| SIESTAFLOW component | Donor component | Classification | Final decision |
|---|---|---|---|
| `prepare_scheduler_probe.py` | `slurm.py`, `generate_deploy_kit.py` | REWRITE | Keep render/inspect separation; reject QE commands, fixed cluster data and direct writes |
| `inspect_probe_job.sh` | legacy convergence-controller queue monitoring | DISCARD | Empty `squeue` inference is incompatible; require exact main `sacct` row |
| `verify_local_package.py` | `validation_runner.py`, `qe_validator.py` | REFACTOR | Retain pre-use gate; replace QE semantics with package/runtime checks |
| `run_login_probe.sh` | `slurm_advisor_v5.py`, registry discovery | REFACTOR | Retain discovery separation; remove automatic recommendation/fallbacks |
| `collect_probe_results.sh` | Harvester phase | REWRITE | Retain explicit phase only; no QE/scientific parsing |
| `scripts/collect_bundle.py` | project manifest/deploy kit | REFACTOR | Retain manifest-first kit with deterministic and safe evidence rules |
| `scripts/probe_common.sh` | `SafeCommandRunner` | PORT | Port timeout/exit/capture pattern without submission retries or dependency |
| embedded-Python validator | none | NO_EQUIVALENT_FOUND | New compile-only implementation |

Counts: PORT 1, REFACTOR 3, REWRITE 2, DISCARD 1, NO_EQUIVALENT_FOUND 1. The complete input/output, error, exit-code, stdout/stderr, validation, executed-test, accepted/rejected-pattern and adaptation record is in `M3R_ENGINEERING_DONOR_CROSSCHECK.json`.

Explicitly rejected: Quantum ESPRESSO executables/parsers, scientific fixtures, pseudo guidance, cluster accounts/partitions/QoS, automatic `sbatch`, retry dispatch, automatic resource advice, and empty-queue completion assumptions.
