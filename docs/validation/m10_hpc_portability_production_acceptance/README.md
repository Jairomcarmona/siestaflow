# M10 HPC Portability / Production Acceptance

Status: `IN_PROGRESS`. This is a manual Yoltla acceptance package, not a new
scientific campaign. Its fixed scientific smoke input is classified as
`NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE` and `ENERGY_INTERPRETATION_FORBIDDEN`.

Build the bundle locally from the repository root:

```powershell
python tools/build_yoltla_m10_acceptance.py --output .\qraft-m10-yoltla-bundle
```

The known historical baseline is `tt2d-64p`: two nodes, 64 ranks, 32 ranks per
node. The remote preflight—not this repository—is authoritative for current
partition, module, executable and placement availability.

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
