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
- `single_fdf.py` owns planning, staging, launch, validation, persistence and
  output assembly. Its behavior is tested, but responsibilities should be
  separated before adding more engines/protocols.
- `allocation_controller.py` remains large and combines orchestration with
  evidence/output concerns. Refactor only behind existing behavioral tests.
- Native persistent REPL history is not implemented; v1 history is per session.
- Legacy packaging commands still need a checked-out source tree containing
  their historical assets. They remain hidden from installed CLI help until
  their assets are deliberately packaged or the compatibility surface is
  retired.

## P2

- Historical standalone packaging duplicates selected runtime files. It remains
  a tested deployment fallback but increases release maintenance.
- Vendored standalone controller runtimes have no installed distribution
  metadata, so their derived package version is `0+unknown`. Inject release
  provenance at bundle-build time before treating that display as release
  evidence.
- Uppercase legacy user manuals overlap the concise installed-mode manuals.
  Consolidate links gradually; do not rewrite accepted historical evidence.
- Public API stability is alpha (`0.2`) and must be reassessed before 1.0.
