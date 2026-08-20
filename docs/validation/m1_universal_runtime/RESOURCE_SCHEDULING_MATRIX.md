# Resource scheduling matrix

| Gate | Synthetic arrangement | Required observation | Result |
|---|---|---|---|
| Bounded concurrency | `ROOT → {A,B,C}`, capacity two | peak exactly 2; never above 2; all complete | PASS |
| CPU arbitration | 8 CPUs; A=6, B=6, C=2 | A+C may run; B waits; peak 8; all leases released | PASS |
| Host arbitration | two exclusive Hydra hosts; three ready tasks | first wave gets distinct hosts; later task reuses released host | PASS |
| Walltime launch gate | remaining=70, estimate=60, margin=10 | no attempt created; state remains resumable | PASS |
| Controlled interruption | A completes while B is active; `SIGTERM` requested | A remains complete; B is `INTERRUPTED`, never false complete | PASS |
| Allocation continuation | later allocation has sufficient time | A reused; B resumes as immutable `attempt-0002` | PASS |
| Final release | all cases | used CPUs=0, used hosts=empty, active leases=empty | PASS |

Synchronization uses `threading.Event` and executor futures. Assertions do not
depend on arbitrary sleep durations.
