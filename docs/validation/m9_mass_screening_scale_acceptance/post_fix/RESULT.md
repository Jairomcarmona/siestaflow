# M9 persistence post-fix characterization

Scope: Option B only — canonical `state/workflow_runtime.json` snapshot plus
append-only `state/workflow_runtime.journal.jsonl`. M9 remains open.

| Case | Pre-fix full snapshots | Post-fix full snapshots | Pre-fix state bytes | Post-fix total persistence bytes | Summary SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| N=25, P=4 | 53 | 2 | 269292 | 30703 | `73ce82c5a4207d8accd472999474af482f97d9da3a7c165c527f0863155eb1bc` |
| N=100, P=4 | 203 | 2 | 3862714 | 117163 | `55bd0659b8500d03ab1951976b295a396b5401ed2e768f5e31879d6bf1c27684` |

Post-fix journal appends were 53 (N=25) and 203 (N=100). Each case used
`total_cpus=16`, `total_nodes=1`, `max_parallel_steps=4`, and
`cpus_per_task=4`; observed peaks were P=4, CPUs=16, nodes=1. The logical
summary hashes matched their recorded pre-fix equivalents.

Focused recovery coverage includes legacy snapshot loading, multi-mutation
journal replay, clean compaction, corruption rejection, reserved-attempt
recovery, and sibling-failure isolation. No full regression was run.
