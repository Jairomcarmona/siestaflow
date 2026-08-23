# M6 ground-state chain

- Baseline SHA: `d25a51d8b05dbeb305187f9716eb70122da25657`.
- Final SHA: final branch HEAD, recorded in the delivery report.
- Production files: `src/qraft/protocols/ground_state.py`, `src/qraft/engines/siesta/ground_state.py`, `src/qraft/engines/siesta/campaign_adapter.py`, and `src/qraft/protocols/__init__.py`.
- Orchestration: F03 verifies and publishes the numerical profile; M6 verifies it, renders the relaxation handoff, invokes `RelaxationProtocol`, verifies the produced geometry, renders the final SCF handoff, and invokes the canonical SIESTA workflow/runtime for final SCF.

## Scientific evidence

- Numerical profile: exact producer file and envelope-content hashes are verified before profile selections are consumed. The M6 fixture preserves `basis_energy_shift = 300 meV`, `mesh_cutoff = 350 Ry`, and `kpoints = [4, 4, 2]`.
- Relaxation handoff: immutable evidence binds template SHA, numerical-profile file/content SHA, and rendered FDF SHA.
- Final-SCF handoff: immutable evidence binds template SHA, numerical-profile file/content SHA, relaxed-geometry file/content SHA, and rendered FDF SHA.
- Final SCF: uses the existing SIESTA capability through `WorkflowCompiler → CompiledWorkflowRuntime → CapabilityRegistry`; it requires started/converged SCF and `ground.DM`.
- Electronic state: `electronic-state.json` is a `SCIENTIFIC_ARTIFACT` envelope of type `qraft.electronic-state`, binding profile hashes, geometry hashes, final FDF SHA, final `ScientificIdentity` fingerprint, final DM SHA, and task/attempt provenance.
- Blocking coverage: profile/geometry replacement, upstream convergence failure, final SCF non-convergence, and missing DM all prevent state publication. Identical final-SCF input reuses the canonical runtime attempt.

## Test record

- Baseline focused: `49 passed`.
- M6 targeted: `2 passed`.
- Final focused: `51 passed`.
- Full suite (once): `593 passed, 1 skipped in 139.28s`.

`NEW_EXECUTION_AUTHORITY = NO`

`RUNTIME_SPECIAL_CASE = NO`

`CORE_SCHEMA_CHANGE = NO`

| Gate | Result |
| --- | --- |
| M6-01 | PASS |
| M6-02 | PASS |
| M6-03 | PASS |
| M6-04 | PASS |
| M6-05 | PASS |
| M6-06 | PASS |
| M6-07 | PASS |
| M6-08 | PASS |
| M6-09 | PASS |
| M6-10 | PASS |
| M6-11 | PASS |
| M6-12 | PASS |
| M6-13 | PASS |
| M6-14 | PASS |
| M6-15 | PASS |
| M6-16 | PASS |
| M6-17 | PASS |
| M6-18 | PASS |
| M6-19 | PASS |
| M6-20 | PASS |
| M6-21 | PASS |
| M6-22 | PASS |
| M6-23 | PASS |
| M6-24 | PASS |
| M6-25 | PASS |
| M6-26 | PASS |
| M6-27 | PASS |
| M6-28 | PASS |
| M6-29 | PASS |
| M6-30 | PASS |
| M6-31 | PASS |
| M6-32 | PASS |
| M6-33 | PASS |
| M6-34 | PASS |
| M6-35 | PASS |
| M6-36 | PASS |
| M6-37 | PASS |
| M6-38 | PASS |
| M6-39 | PASS |
| M6-40 | PASS |

M6 is `CLOSED`; M7 remains `NOT_STARTED` and is ready to start.
