# M3R limitations

- `REMOTE_EVIDENCE_PENDING`: all runtime execution was local and synthetic; V2 has not run on Yoltla.
- No audited Mn/O files are present locally. The verifier's positive runtime test used explicitly synthetic content/hashes; the audited reference hashes were preserved unchanged in the reference package and embedded V2 requirements.
- The engineering donor was inspected read-only and was not executed; no compatibility with its QE workflows is claimed.
- Secret detection intentionally targets obvious assignments and private-key blocks. It is not a general credential classifier.
- `run_optional` is bounded by GNU `timeout` when available; on a Linux host without that command it preserves the exit code but cannot impose the same external bound.
- Unknown future SLURM states remain nonterminal and require review until an explicit documented policy is added.
- The stub runtime proves rendering, control flow and evidence contracts, not scheduler/MPI behavior or cluster suitability.
- V1 is preserved locally only as `V1_SUPERSEDED_DO_NOT_USE` for traceability. It must be manually removed or renamed on Yoltla and never mixed with V2.
- Scientific authorization, M3B and M4 remain outside this milestone.
