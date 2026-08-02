# Remote CLI electronic-analysis integration -- Phase 4

Status: `REMOTE_TECHNICAL_ELECTRONIC_ANALYSIS_INTEGRATION_VALIDATED`.

This record documents a remote technical acceptance of the generic recipe
`siestaflow.recipe.siesta.ground-state-to-electronic-analysis`. It does not
interpret the results as scientific validation and does not close Phase 4.

## Verified execution

| Field | Value |
|---|---|
| Slurm job | `781132` |
| Slurm state | `COMPLETED`, `ExitCode=0:0` |
| Elapsed | `00:02:46` |
| Nodes | `tt[20-21,24,26]` |
| Partition | `tt2d-80p` |
| Account / QoS | `vini` / `normal` |
| Resolution | 4 nodes, 4 ranks, 1 rank per node, 1 CPU per rank |
| Selected traits | `ttv3,mem128` |
| Runtime | `siesta/5.4.2`, Hydra, `python/3.12` |
| Source commit | `4abf2910c97d1ec30101a3eba1fa13710326c580` |
| Workflow lock content | `fb80bfcb7b43590a22bd703a71ed6c5a63e891eba6ef8e508a435b1039686647` |
| Live snapshot | `083e9ad08136caec868b8b21b9464f231fadc0b36a1c17dbee89763b17814911` |
| Evidence ZIP | `75b90fc5ee875999c00ad246a1b59dd496f2ce2632752ae5b7abf8c0aefeca9b` |

The capacity capture used to resolve resources was observed at
`2026-08-02T08:10:53Z`. Variant `tt2d-80p:2` reported 15 free nodes and the
exact constraint `MinNodes=MaxNodes=4`.

## DAG and density-matrix transfer

```text
ground_state  COMPLETED
|- bands      COMPLETED, DM read
|- dos_pdos   COMPLETED, DM read
`- optics     COMPLETED, DM read
```

All four tasks terminated normally, converged SCF, and used one attempt. The
parent produced `phase4_ground_state.DM` with SHA-256
`a4cf1edcca4caf82336a3c53ccc8aea31961b0b9ac24432f6c3840ab2f49ab82`.
Each child recorded this same SHA-256 before execution and in its transfer
evidence, and linked the parent result manifest
`2fb023a8aa3f3697263a962f7a42661fa8cdf04b747078107d22243e56835c3c`.
The three child manifests record `dm_read_attempted: true` and
`dm_read_succeeded: true`.

## Scope and limits

- This validates the canonical CLI route: `workflow.lock.json` -> live Slurm
  resolution -> `run prepare` -> `run.lock.json` -> self-contained package ->
  remote multinode execution.
- It validates the dependent fan-out from one ground state, hash-bound DM
  transfer, and SIESTA DM reading for bands, DOS/PDOS, and optics.
- Classification: `TECHNICAL_CLI_INTEGRATION_ACCEPTANCE`.
  Scientific interpretation: `NOT_PERFORMED`.
- Phase 4 remains open: it still requires a scientific campaign with an
  approved convergence/selection criterion propagated into staged relaxation.
