# Effective FDF closure correctness hotfix

- Baseline: `e582bdc4a92344d505b057c31ff3a68a5923b218`
- Branch: `fix/qraft-effective-fdf-closure-correctness`
- Production scope: `engines/siesta` effective closure, closure staging, campaign materialization, and M5/M6 consumers only.
- Design: a single lossless-parser-adjacent authority expands `%include` lexically, follows nested includes, applies normalized-label first appearance, resolves scalar/block redirects, clones the closure, mutates the authoritative occurrence, and re-verifies the rendered closure.
- Species/pseudos and `ScientificIdentity` now use the first effective `ChemicalSpeciesLabel` while the complete closure remains hash-bound.
- F02/F03, M5, and M6 consume the same materializer/effective resolver; no generic runtime, core schema, or execution authority changed.

Validation:

- Baseline focused: `52 passed`.
- Targeted effective-FDF, F03, M5, M6, and single-FDF: `36 passed`.
- Final focused: `79 passed`.
- Full suite: invoked once with `python -m pytest -q`; the execution channel ended after progress at 12% without an exit status or completion summary. It must not be represented as passing.

Gate status: EFDF-01–EFDF-50, EFDF-52, and EFDF-53 passed from the verified focused evidence. EFDF-51 is not passed because the required one-time full-suite result could not be observed. Therefore milestones are unchanged and M7 remains `NOT_STARTED`.

- `NEW_EXECUTION_AUTHORITY = NO`
- `RUNTIME_SPECIAL_CASE = NO`
- `CORE_SCHEMA_CHANGE = NO`
