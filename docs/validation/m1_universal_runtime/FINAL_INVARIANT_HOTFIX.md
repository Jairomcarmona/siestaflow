# M1 final invariant hotfix

Source closure: `ae794f12a631849a155a1a03c3db07dd5730d2d9`.

Its dossier manifest is preserved as
`evidence/checkpoint_ae794f1_hashes.sha256`; the earlier `4964e9c` checkpoint
manifest remains preserved independently.

The final M1 hotfix closes three narrowly scoped correctness gaps without
changing the global `ScientificIdentity` contract, `CompiledWorkflow`, the
historical controller, convergence execution, or the canonical production
entry path.

## Closed invariants

- **I01:** legacy translation derives `ScientificIdentity` only from protected
  scientific/computational content. Task labels and execution placement do not
  affect its fingerprint; protected-input mutation does.
- **I02:** every generic resource lease owns CPUs and nodes. The coordinator
  exposes and enforces `used_nodes`/`peak_nodes` independently of host placement
  and releases all three resource dimensions.
- **I03:** each staged input has a hash-bound immutable copy under
  `.qraft/input-evidence/`. Non-mutable working inputs remain hash-checked;
  capability-declared mutable working copies may change. Current parent/source
  evidence must still match, and the capability must return successful
  consumption validation before technical completion.

SIESTA `.DM` classification and `dm_restart_attempted`/
`dm_restart_succeeded` interpretation remain entirely in
`SiestaEngineAdapter` and `SiestaOutputParser`. The generic runtime contains no
SIESTA or density-matrix parsing branch.

## Executable result

- baseline focused: 45 passed
- baseline full: 549 passed, 1 skipped
- final combined M1 focused: 55 passed
- final full: 559 passed, 1 skipped
- final sdist/wheel and engine-neutral/canonical imports: PASS

M1 remains `CLOSED`; M2 remains `NOT_STARTED`.
