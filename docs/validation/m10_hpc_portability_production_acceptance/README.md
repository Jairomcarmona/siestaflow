# M10 HPC Portability / Production Acceptance

Status: `IN_PROGRESS`. This is a manual Yoltla acceptance package, not a new
scientific campaign. Its fixed scientific smoke input is classified as
`NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE` and `ENERGY_INTERPRETATION_FORBIDDEN`.

Build an unresolved discovery bundle locally from the repository root:

```powershell
python tools/build_yoltla_m10_acceptance.py --output .\qraft-m10-discovery
```

The bundle contains the fixed M10 shape (2 nodes, 64 ranks, 32 ranks/node),
the smoke fixture, and a self-contained login-node discovery workflow. It
copies the M3 read-only probe and resolver plus an M10 adapter that verifies
the current partition has at least two visible nodes, 32 CPUs/node, and an
observed memory value. It contains no scientific submit script. `tt2d-64p` /
`vini` / `normal` are `HISTORICAL_ONLY_NOT_CURRENT_AUTHORITY` hints, never
defaults.

After current Yoltla evidence has produced and a human has reviewed a
`scheduler_selection.json` that demonstrates the exact M10 shape, render the
resolved bundle:

```powershell
python tools/build_yoltla_m10_acceptance.py --output .\qraft-m10-resolved --scheduler-selection .\scheduler_selection.json
```

The selection supplies account, partition, optional QoS, memory and structured
provenance. A selection that does not demonstrate the M10 resource shape fails
closed as `M10_REMOTE_PROFILE_UNRESOLVED`.

| GATE | LOCAL_PRECHECK | YOLTLA_EVIDENCE | STATUS |
| --- | --- | --- | --- |
| A. Yoltla preflight | bundle manifest | `evidence/preflight.<job>.txt` | `PENDING_REMOTE` |
| B. Shared filesystem | script has a two-node marker/hash check | both host records, same path and hashes | `PENDING_REMOTE` |
| C. Multinode Hydra + SIESTA | package verification and equivalence JSON | canonical HYDRA worker results | `PENDING_REMOTE` |
| D. Multinode Srun + SIESTA | package verification and equivalence JSON | canonical SRUN worker results | `PENDING_REMOTE` |
| E. Backend equivalence | same workflow/science; different execution specs | both backend summaries | `PENDING_REMOTE` |
| F. Allocation continuation | deterministic `STAGE_A -> STAGE_B` package | two job IDs; reuse of A; B completes second job | `PENDING_REMOTE` |

See [RUNBOOK.md](RUNBOOK.md) for the exact manual sequence. No SSH automation,
credentials, or background agent is included.
