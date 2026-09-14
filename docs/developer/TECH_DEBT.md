# Verified technical debt

## P0

None identified for the installed single-FDF product boundary.

The following productization findings were resolved in the boundary closure:

- **HPC defaults:** `single_fdf` no longer manufactures a partition, launcher,
  or SIESTA executable. Placement now must originate in a profile,
  configuration layer, or explicit override; MPI without a launcher fails
  before a plan or attempt is created.
- **CLI boundary:** the installed help exposes only the product commands.
  Historical command families are retained as hidden legacy compatibility
  routes and are not advertised as an installed product contract.
- **Environment inspection:** `qraft env` is the public interface. The legacy
  `environment check` spelling delegates to the same inspector.
- **Repository-root lookup:** public commands do not depend on `_repo_root()`.
  Legacy packaging commands use the caller's working directory explicitly.
- **Versioning:** distribution metadata is the only maintained version value;
  Python and CLI obtain it through installed package metadata.
- **Distribution documentation:** README links target stable repository URLs
  instead of files presumed to be present in a wheel.

## P1

- Public registry release metadata lacks a confirmed license, author and
  maintainer declaration. Do not invent them; resolve before PyPI publication.
- `single_fdf.py` remains a tested legacy runtime path beside the M1 compiled-
  workflow capability runtime. M2 must migrate convergence first; consolidate
  legacy attempt views incrementally without breaking persisted evidence.
- `campaign_spec.py` and `protocols/convergence.py` are each approximately
  400 lines after CampaignSpec v1. Their current size is acceptable, but new
  protocols must reuse their typed contracts and extract cohesive services
  rather than extending either module into a protocol catch-all.
- The schema 1/2 allocation controller remains SIESTA-shaped only at its
  explicit historical persisted-state boundary. New CLI and package workers
  translate accepted configs into `CompiledWorkflow`/`ExecutionSpec` and use
  `CompiledWorkflowRuntime`; `HistoricalAllocationController` is retained for
  nondestructive recovery of old `campaign_state.json`. Do not add new
  production authoring or scientific semantics to that compatibility path.
- Persisted Attempt representations are not yet repository-wide unified. All
  new canonical production execution has one immutable Attempt lifecycle;
  historical controller evidence retains deterministic compatibility views
  and is never destructively migrated.
- Convergence runtime migration → M2. `ConvergenceProtocol` deliberately keeps
  its existing sequential `execute_fdf_plan()` loop during M1.
- Native persistent REPL history is not implemented; v1 history is per session.
- Legacy packaging commands still need a checked-out source tree containing
  their historical assets. They remain hidden from installed CLI help until
  their assets are deliberately packaged or the compatibility surface is
  retired.

## P2

- Resource scheduling closure is proven by deterministic synthetic fixtures
  and self-contained package/build gates, not a real cluster acceptance run.
  Real Slurm/Hydra capacity and signal acceptance remains deployment evidence,
  not a second runtime implementation.
- Historical standalone packaging duplicates selected runtime files. It remains
  a tested deployment fallback but increases release maintenance.
- Optional verbose/details presentation over persisted evidence is not yet
  implemented. This is a UX improvement, not an evidence or reproducibility
  gap.
- Vendored standalone controller runtimes have no installed distribution
  metadata, so their derived package version is `0+unknown`. Inject release
  provenance at bundle-build time before treating that display as release
  evidence.
- Uppercase legacy user manuals overlap the concise installed-mode manuals.
  Consolidate links gradually; do not rewrite accepted historical evidence.
- Public API stability is alpha (`0.2`) and must be reassessed before 1.0.
