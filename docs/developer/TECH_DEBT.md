# Verified technical debt

## P0

None identified for installed single-FDF productization.

## P1

- Public registry release metadata lacks a confirmed license, author and
  maintainer declaration. Do not invent them; resolve before PyPI publication.
- `single_fdf.py` owns planning, staging, launch, validation, persistence and
  output assembly. Its behavior is tested, but responsibilities should be
  separated before adding more engines/protocols.
- `allocation_controller.py` remains large and combines orchestration with
  evidence/output concerns. Refactor only behind existing behavioral tests.
- Native persistent REPL history is not implemented; v1 history is per session.

## P2

- Historical standalone packaging duplicates selected runtime files. It remains
  a tested deployment fallback but increases release maintenance.
- Uppercase legacy user manuals overlap the concise installed-mode manuals.
  Consolidate links gradually; do not rewrite accepted historical evidence.
- Public API stability is alpha (`0.2`) and must be reassessed before 1.0.
