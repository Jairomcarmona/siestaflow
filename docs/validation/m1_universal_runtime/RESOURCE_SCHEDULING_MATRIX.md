# Resource scheduling matrix

| Gate | Synthetic arrangement | Required observation | Result |
|---|---|---|---|
| Bounded concurrency | `ROOT → {A,B,C}`, capacity two | peak exactly 2; never above 2; all complete | PASS |
| CPU arbitration | 8 CPUs; A=6, B=6, C=2 | A+C may run; B waits; peak 8; all leases released | PASS |
| Node arbitration | 2 nodes; A=2, B=2 | only one lease at a time; peak nodes=2 | PASS |
| Valid node sharing | 2 nodes; A=1, B=1 | both leases coexist; peak nodes=2 | PASS |
| Joint CPU/node enforcement | separate CPU-bound and node-bound fixtures | each independent capacity limit wins when tighter | PASS |
| Host arbitration | two exclusive Hydra hosts; three ready tasks | first wave gets distinct hosts; later task reuses released host | PASS |
| Walltime launch gate | remaining=70, estimate=60, margin=10 | no attempt created; state remains resumable | PASS |
| Controlled interruption | A completes while B is active; `SIGTERM` requested | A remains complete; B is `INTERRUPTED`, never false complete | PASS |
| Allocation continuation | later allocation has sufficient time | A reused; B resumes as immutable `attempt-0002` | PASS |
| Final release | all cases | used CPUs=0, used nodes=0, used hosts=empty, active leases=empty | PASS |

Synchronization uses `threading.Event` and executor futures. Assertions do not
depend on arbitrary sleep durations.
