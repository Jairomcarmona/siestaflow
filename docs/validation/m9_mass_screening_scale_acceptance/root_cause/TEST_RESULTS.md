# Focused Test Results

Completed focused validation:

| Scope | Result |
| --- | --- |
| M9-R1 canonical matrix (`N=25/P=1`, `25/P=4`, `100/P=1`, `100/P=4`) | PASS, `EXIT=0` |
| New M9-R1 harness assertions exercised by the matrix | PASS: P=4 has four leases/launches; same-N summary hashes match; no atomic failures |
| Existing runtime identity test | PASS |
| Existing M3 allocation-rollover/reuse test | PASS |

The existing test functions were invoked directly in a persistent external
workspace because pytest teardown in this Codex Windows environment again
raised `PermissionError [WinError 5]` while scanning its explicit base-temp.
That pytest invocation was not rerun. The error occurred in pytest's
`cleanup_dead_symlinks` session finish, rather than in a QRAFT assertion or
the M9-R1 runtime matrix.

No full suite, SIESTA, MPI launcher, Slurm, CampaignRunner, or alternate
runtime path was executed.
