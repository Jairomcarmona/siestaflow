# M9 POST-FIX N=500/P=4 scale acceptance

This is the single independent N=500/P=4 run. No recovery, full regression,
SIESTA, MPI, Slurm, Hydra, Yoltla, or M10 execution was performed.

- Candidates: 500; completed: 500; failed/blocked/interrupted: 0/0/0
- Artifact collisions: 0; cross-candidate leakage: 0; propagation: 0
- Ranking mismatches: 0; silent skips: 0
- Peaks: 4 parallel steps, 16 CPUs, 1 physical node
- Summary SHA-256: `1ebd5d127d23bb8afd26562f99f5804e07b7a861e5b297f95fb9adf8fdda833e`
- Lifecycle wall time: 65.029438 s; throughput: 7.6888 candidates/s
- Full snapshots: 2 writes, 186984 bytes
- Journal: 1003 local appends, 391787 bytes; compacted after final snapshot
- Total state persistence: 578771 bytes
- Filesystem: 3502 files, 1468011 bytes; evidence: 305067 bytes
- Process CPU and peak RSS were not persisted by the driver (`unavailable`;
  no value is inferred).

The per-candidate summary was generated and validated in memory with fields
`candidate_id,status,scientific_metric,rejection_reason,rank`, ordered by
`candidate_id`, with deterministic ranking tie-breaks.
