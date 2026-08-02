# Changelog

## Unreleased — governance and roadmap

- Incorporated raw Yoltla evidence archives for jobs `781106`, `781111`,
  `781113` and `781115`: full adversarial provenance, real Slurm `SIGUSR1`
  recovery across allocations, and physical disjoint concurrent `srun`
  placement. The remaining Phase 3 gate is human transition acceptance.
- Recorded the independent audit of `cf62127` as `CONDITIONALLY_APPROVED`,
  narrowed the documented scope of the `781102` interruption and host-set
  checks, and distinguished retained local package identity from an unavailable
  remote-upload checksum record.
- Incorporated sanitized real Yoltla evidence for job `781102`, which completed
  all five remote adversarial cases with exit `0:0`; remote Phase 3 engineering
  evidence is complete while formal independent audit and human transition
  acceptance remain pending.
- Incorporated sanitized real Yoltla evidence for job `781100`, which completed
  the canonical four-node parent → SHA-256-bound DM transfer → verified restart
  child path with exit `0:0`; Phase 3 remains open for its remote adversarial
  matrix and formal transition audit.
- Formalized one source tree and the canonical
  `WorkflowDefinition → workflow.lock.json → run prepare → AllocationController`
  route while classifying older campaign, preview, smoke and evidence paths.
- Added proportional Git/review/testing governance, ADR policy, phase acceptance
  records, traceability requirements and explicit dirty-tree handling.
- Added the product roadmap and Phase 8 distribution/adoption gate without
  changing version 0.2.0 or the pending Yoltla Phase 3 status.

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
- Added the Phase 1 typed workflow DAG contract and deterministic compiler,
  including fail-closed schema/graph/artifact/resource validation, external
  input hashes, topological planning, text/Mermaid graphs, and canonical
  `workflow.lock.json` envelopes.
- Added the `workflow validate`, `workflow plan`, `workflow graph`, and
  `workflow compile` CLI commands. Compilation explicitly does not authorize
  execution.
- Corrected the Yoltla-observed restart-DM false negative: transferred inputs
  now have an immutable pre-execution evidence copy, while the working copy may
  be legitimately replaced by SIESTA and is recorded as a separate output.
- Added explicit parsing of successful DM restart consumption, allowlisted the
  SIESTA 5.4.2 `BASIS_ENTHALPY` deprecation warning, and made recovery
  re-evaluate incomplete historical attempts without repeating valid work.
- Added the Phase 2 researcher CLI vertical: read-only environment checks,
  idempotent preparation-only project initialization, and explainable
  Core-Contract input validation with optional pseudopotential verification.
- Added a real WSL/Slurm integration sandbox and recorded local acceptance
  evidence without treating it as Yoltla or scientific validation.
- Added the initial Phase 6 SIESTA 5.4.2 validation foundation: a versioned,
  manual-backed rule catalog, strict researcher context profiles, contextual
  FDF checks, and a Core Contracts rule-provider capability.
- Added read-only `input rules` and `workflow preflight` commands and extended
  `input validate` with engine version, context profile, and explainable
  output controls. Heuristics remain review-only and never authorize runs.
- Declared the SIESTA JSON registries as wheel package data so installed
  distributions carry the same keyword and validation catalogs as source
  checkouts.
- Added the initial Phase 3 prepared-run adapter and
  `siestaflow.run-lock@1.0`: workflow locks plus strict external Slurm
  profiles now produce self-contained controller packages with exact input
  destinations and hash-bound DAG transfers.
- Added read-only `run inspect`, `run status`, and `run resume` planning.
  These commands verify cross-contract identity and never invoke `sbatch`.
- Added optional output tracking and explicit source-to-destination staging to
  the allocation controller while retaining schema-1 package compatibility.

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
