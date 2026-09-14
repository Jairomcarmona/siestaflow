# M9-R1 Characterization Result

Baseline: `d17666e028c1bbb2b27d715290312154db6f8440`  
Environment: Windows 11, Python 3.13.14, synthetic capability and recording launcher only.

| N | P | Wall s | CPU s | Candidates/s | State writes | State bytes | State save s | Atomic state I/O s | Event I/O s | Scheduler scan s | Peak steps | Summary SHA-256 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 25 | 1 | 2.260705 | 1.046875 | 11.058 | 53 | 273,265 | 0.229284 | 0.179781 | 0.153513 | 0.003078 | 1 | `73ce82c5a4207d8accd472999474af482f97d9da3a7c165c527f0863155eb1bc` |
| 25 | 4 | 0.776110 | 1.062500 | 32.212 | 53 | 269,292 | 0.287420 | 0.229320 | 0.195150 | 0.001023 | 4 | `73ce82c5a4207d8accd472999474af482f97d9da3a7c165c527f0863155eb1bc` |
| 100 | 1 | 10.769914 | 5.468750 | 9.285 | 203 | 3,878,747 | 1.234635 | 0.886472 | 0.596385 | 0.030719 | 1 | `55bd0659b8500d03ab1951976b295a396b5401ed2e768f5e31879d6bf1c27684` |
| 100 | 4 | 4.137365 | 5.265625 | 24.170 | 203 | 3,862,714 | 1.937892 | 1.521183 | 1.241728 | 0.014694 | 4 | `55bd0659b8500d03ab1951976b295a396b5401ed2e768f5e31879d6bf1c27684` |

All four runs completed 100% of their candidates: failed=0, blocked=0,
reused=0, atomic failures=0, and `WinError 5`=0. Peak concurrent state writes
was exactly one in every run, as expected from the runtime state lock.
Artifact collisions, cross-candidate leakage, unexpected propagation, and
ranking mismatches were all zero; attempt-manifest persistence was 25/44,650 B
at N=25 and 100/178,700 B at N=100 for either P.

At N=100, P=4 reduces wall time by 2.60× and increases throughput by 2.60×,
but retains the same count and nearly the same cumulative volume of state
rewrites. From N=25 to N=100, state bytes grow 14.19× for P=1 and 14.34× for
P=4 when N grows 4×. This confirms the persistence scaling mechanism at the
owner layer `qraft.execution.capability_runtime.CompiledWorkflowRuntime`.

The scheduler is measurable but secondary in this matrix: its N=100 time is
0.031 s at P=1 and 0.015 s at P=4, versus 1.235 s and 1.938 s in state saves.
Its `_is_ready` calls grow 627 → 10,184 (P=1) and 240 → 5,021 (P=4), which is
superlinear and should remain a separate future optimization candidate.

Derived exponents over N=25 → N=100 are: cumulative state bytes `p=1.913`
(P=1) and `p=1.921` (P=4); wall time `p=1.126` (P=1) and `p=1.207` (P=4);
process CPU `p=1.193` (P=1) and `p=1.154` (P=4). The accepted serial
N=100 → N=500 baseline independently gives state-byte `p≈1.977`.

Persistence scaling classification: **`CONFIRMED`**. Source proves O(N)
transitions and O(N) full-state serialization each transition; therefore the
sum of serialized state sizes is O(N²). Both serial baselines and this P=1/P=4
matrix measure that predicted cumulative-byte growth.

No performance threshold, product optimization, retry policy, M9 closure, or
M10 activity is established by this evidence.

**Verdict: `M9_ROOT_CAUSE_CONFIRMED_FIX_DESIGN_READY`.**
