# Changelog

## Unreleased — core contracts

- Added engine- and cluster-neutral Core Contracts 1.0 for validation reports,
  artifact references and transfers, execution requests/evidence, workflow
  events, and plugin descriptors.
- Added canonical immutable SHA-256 envelopes, explicit major/minor
  compatibility, namespaced extensions, strict relative paths, and exact
  multinode resource invariants.
- Added an explicit, freezable capability registry for engines, validation
  rules, launchers, artifact processors, postprocessors, and schedulers.
- Moved shared task/decision/failure vocabularies into the contract kernel
  while preserving imports from `siestaflow.models`.
- Added compatibility adapters for current SIESTA validation/artifact models
  and allocation-local launcher models.
- Corrected the Yoltla-observed restart-DM false negative: transferred inputs
  now have an immutable pre-execution evidence copy, while the working copy may
  be legitimately replaced by SIESTA and is recorded as a separate output.
- Added explicit parsing of successful DM restart consumption, allowlisted the
  SIESTA 5.4.2 `BASIS_ENTHALPY` deprecation warning, and made recovery
  re-evaluate incomplete historical attempts without repeating valid work.

## 0.2.0 consolidation alpha (2026-07-29)

- Added the Yoltla Hydra launcher with explicit hosts, ranks-per-node and a
  unique `FI_PSM3_UUID` per scientific step.
- Extended the real allocation controller with dependency DAGs, failed-parent
  blocking, exclusive host allocation and hash-bound parent artifact transfer.
- Added bounded, hash-bound gate tasks so numerical selectors and geometry
  routing can run inside the allocation without consuming an MPI launcher.
- Added `campaign progress`, `campaign watch`, and a standard read-only package
  progress script.
- Added the generic deterministic `remote controller-package` builder.
- Recorded the observed Yoltla SIESTA 5.4.2/Hydra runtime and queue profiles
  with evidence-strength labels instead of treating every scheduler-accepted
  profile as runtime validated.
- Preserved schema 1.0 controller compatibility while adding schema 2.0.

## M3B1 — first real SIESTA technical-smoke package (2026-07-21)

- Corrected executable SLURM scripts to derive the package root exclusively from `SLURM_SUBMIT_DIR`, validate `package_manifest.json`, and confine writes to `evidence/`, `results/`, and `work/`.
- Added a generic real-smoke packager and an external graphene reference package containing the byte-identical validated C50 geometry, approved FDF seed, and audited carbon PSML.
- Generated and independently verified the human-operated M3B1 upload ZIP. No remote command or scientific calculation was executed locally.

## M3R2 — account-wide SLURM association resolution (2026-07-21)

- Preserved empty-partition `sacctmgr` rows as account-wide associations with diagnostics and provenance.
- Added structured `sinfo`/`scontrol` parsing, compatibility filtering, unique-default selection, and evidence-bound human selection.
- Added the sanitized real-evidence fixture, runtime coverage, `scheduler_selection.json`, and reproducible M3 probe package V3.

## Unreleased — M3R

- Disclosed and corrected two pre-execution runtime defects in M3 V1: invalid embedded Python in `inspect_probe_job.sh` and newline escaping in the generated SLURM heredoc.
- Added compile-only multi-heredoc validation and package-wide direct Python, Bash and SLURM validation.
- Added executed stub tests for generated SLURM, login discovery, `inspect_probe_job.sh`, terminal `sacct` classification, pseudopotentials and bundle collection.
- Hardened association values, paths, symlinks, overwrite behavior, secret detection, command observability and deterministic tar/ZIP output.
- Regenerated `M3_STATIC_V2` (`package_revision: 2`, supersedes V1). V1 is `SUPERSEDED_DO_NOT_USE`.

## Unreleased — M3G

- Added versioned external `ProjectPackage` loading and validation.
- Added declarative arbitrary-value SIESTA campaigns and extensible evidence gates.
- Added arbitrary-species pseudopotential verification and explicit copy/link staging.
- Added the `ExamplePackage` API and `examples` CLI family.
- Added generic X/Y and isolated Birnessite Mn/O reference examples.
- Removed project species, hashes, snapshot paths, campaign IDs, and fixed convergence series from `src/siestaflow/`.
- Generalized remote preview and environment-probe pseudopotential requirements.
- Added end-to-end generalization, hardcoding, examples, and documentation tests.
- Public CLI change: campaign creation now requires `--project` and `--campaign-id`; snapshot-specific templates were removed.

## M3

- Added a deterministic, human-operated Yoltla environment probe and conservative evidence importer. Remote evidence remains pending.
