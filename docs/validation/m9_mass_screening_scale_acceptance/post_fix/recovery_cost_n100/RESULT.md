# M9 POST-FIX recovery cost — N=100/P=4

Single two-stage recovery-cost characterization. No clean equivalent campaign,
N=500 rerun, full regression, SIESTA, MPI, or M10 execution was performed.

## FIRST_INVOCATION

- 95 unaffected EVAL nodes completed
- 5 EVAL nodes failed (`i % 20 == 7`)
- 5 SCORE descendants blocked
- attempts started: 195
- wall: 12.2389807 s
- snapshots: 2
- journal: 398 appends / 155096 bytes
- total state persistence: 234521 bytes

## RECOVERY

- reused nodes: 190
- new attempts: 10
- candidates reexecuted: 5
- only EVAL/SCORE branches for candidates 0007, 0027, 0047, 0067, 0087 reran
- attempt-0001 remained present and immutable; attempt-0002 appeared only there
- final: 100 completed, 0 failed, 0 blocked
- wall: 8.8886419 s
- snapshots: 1
- journal: 33 appends / 12260 bytes
- total state persistence: 62198 bytes
- final summary SHA-256: `55bd0659b8500d03ab1951976b295a396b5401ed2e768f5e31879d6bf1c27684`
