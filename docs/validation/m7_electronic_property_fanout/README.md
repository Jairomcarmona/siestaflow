# M7 Electronic Property Fan-out Final Validation

## Validated production

- Validated SHA: `891ad7ae3fa18027bbf13e8bd2800227f896c9c8`

## Architecture

- M6 `qraft.electronic-state` → BANDS / DOS / PDOS.
- Three independent sibling tasks.
- Generic `CompiledWorkflowRuntime`.
- No new execution authority.
- No core changes.
- No contracts changes.
- No generic runtime changes.
- No effective-FDF changes.

## Scientific correctness hotfix

- R1 BandLines first-row semantics: `PASS`.
- R2 EF/ABSOLUTE executable semantics: `PASS`.
- R3A native SIESTA `.bands` parsing: `PASS`.
- R3B native SIESTA XML PDOS parsing: `PASS`.
- R4 exact M6 scientific-identity continuity: `PASS`.

## Native validation

Focused M7 suite:

- `9 passed`
- `0 failed`
- `2.27 s`
- Exit `0`

Full regression suite:

- `612 passed`
- `1 skipped`
- `0 failed`
- pytest elapsed: `136.94 s`
- PowerShell measured elapsed: `137.7672005 s`
- Exit `0`

Previous Codex sandbox pytest failures:

- Classification: `ENVIRONMENT_SETUP / TOOLING_OS`.
- Reason: Windows sandbox `PermissionError [WinError 5]`.
- Product defect: `NO`.

## Formal status

- M0: `CLOSED`
- M1: `CLOSED`
- M2: `CLOSED`
- M3: `CLOSED`
- M4: `CLOSED`
- M5: `CLOSED`
- M6: `CLOSED`
- M7: `CLOSED`
- M8: `NOT_STARTED`
- M8 development gate: `CLEARED`

During final validation, production, test, and configuration changes were `NONE`.
