# QRAFT WSL N=4 CampaignSpec v1 Evidence

This directory preserves the reproducible evidence for the completed local WSL
acceptance of QRAFT CampaignSpec v1.

WSL validates CampaignSpec and ParameterSpec handling, preflight, FDF render,
DAG construction, real SIESTA execution through local SLURM, OpenMPI with four
ranks, technical validation, convergence metrics, the scientific decision,
recovery, and separation of ScientificIdentity from ExecutionSpec.

It does not validate institutional multinode placement, Hydra/Intel MPI,
Yoltla modules, or an institutional shared filesystem. Those remain pending for
the Yoltla acceptance.

The campaign is the accepted two-point MgO mesh smoke (`80` and `100 Ry`).
`campaign.yaml` is the executed CampaignSpec. `rendered/` contains the exact
materialized FDFs and pseudopotentials used by the attempts; the `.gitattributes`
entry preserves the fixed-column PSF format without changing its bytes.
`results/` holds the human-readable QRAFT report and convergence CSV.
`evidence/` holds the persisted attempt manifests and derived, traceable
decision summaries.

The source runtime is commit `3264c7beca29860e2fb4fb4f0f79a243ac5eac38` on
`feat/qraft-campaign-spec-v1`.
