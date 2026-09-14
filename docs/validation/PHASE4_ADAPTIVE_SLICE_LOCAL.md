# Phase 4.1 local canonical adaptive-DAG evidence

Status: `LOCAL_CANONICAL_ADAPTIVE_SLICE / REMOTE_AND_SCIENTIFIC_ACCEPTANCE_PENDING`.

This record covers the first deliberately small Phase 4 vertical. It does not
close Phase 4 and does not claim a converged scientific parameter.

## Verified local path

```text
sweep_alpha ─┐
sweep_beta  ─┼→ select_best → consume_best
sweep_gamma ─┘
```

- The three `sweep` nodes are concrete before compilation and deterministic in
  `workflow.lock.json`; there is no hidden runtime expansion.
- The minimum selector consumes two or three hash-bound JSON metric artifacts,
  records every candidate, and breaks equal values by `variant_id`.
- `run prepare` maps these narrow capabilities to controller `gate` tasks. The
  package includes the gate script as a protected, SHA-256-bound input.
- A local allocation-controller execution completes all five tasks. Its final
  output identifies `beta`, the deterministic winner of the tied minimum.

## Focused test cut

`python -m pytest -q tests/unit/test_adaptive_gate.py tests/runs/test_adaptive_prepared_run.py`

Result: `24 passed`.

The tests cover canonical metric serialization; finite-value checks; minimum
and maximum selection; deterministic ties; malformed, duplicate and
identity-mismatched inputs; decision tampering; static fan-out/fan-in;
hash-bound package generation; local controller execution; and fail-closed
invalid adaptive contracts.

## Remaining Phase 4 work

- Map real, authorized SIESTA sweep parameters to materialized variants.
- Define criteria with units and consecutive-stability semantics.
- Implement and validate the canonical `converge_then_relax` path.
- Run a separately approved remote Yoltla acceptance after the local scientific
  workflow contract is specified.
