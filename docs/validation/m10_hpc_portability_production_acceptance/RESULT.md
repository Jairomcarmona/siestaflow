# M10 HPC portability / production acceptance — current result

Status: `IN_PROGRESS`.

Production-code freeze point:
`d7c51a41adbfe60e590a4bc653736938e418c814`
(`fix: bind M10 acceptance to live Slurm placement`).

This document freezes evidence already obtained on Yoltla. It does not expand
M10 scope and does not introduce new production execution authority.

## Scope freeze

M10 remains limited to multinode Slurm, Hydra, institutional runtime/module
environment, shared filesystem, allocation continuation, and launcher/backend
equivalence.

Findings discovered during acceptance may be deferred as hardening unless they
are causally demonstrated to prevent an original M10 acceptance gate.

## Frozen evidence

| Evidence | Result | Interpretation |
|---|---|---|
| Live Slurm discovery and placement derivation | PASS | Fixed-partition placement derived from current scheduler evidence. |
| qz2d-128p reviewed placement | PASS | 2 nodes x 64 tasks/node = 128 tasks; account vini; QoS normal. |
| Job 787617 multinode preflight | PASS | ncz10,ncz22; 128 tasks; srun and Hydra placement exact; shared FS and runtime visibility PASS. |
| Job 787618 Hydra SIESTA smoke | FAIL_ENVIRONMENT | QRAFT reached engine launch correctly; selected linux-ivybridge SIESTA build exited before banner on Zen3 nodes. |
| Job 787621 CPU diagnostic | PASS | ncz10,ncz22 are AMD EPYC 7513; AVX, F16C and AVX2 present. |
| Static SIESTA linkage | OBSERVED | SIESTA links Intel MPI 2021.17; reviewed Hydra provenance records Intel MPI 2021.7.1. No failure is attributed to this unless demonstrated in a compatible-node run. |
| Historical job 787323 | REFERENCE_PASS | Historical tt2d-64p preflight only; not runtime authority. |

## qz2d result

The qz2d family reports the `zen3` trait. The selected SIESTA 5.4.2 executable
comes from a `linux-ivybridge` build and did not start on the allocated EPYC
7513 nodes.

This is retained as negative environment evidence. The qz2d smoke is not
repeated for M10 closure.

## Current compatible-node probe

Job `787637` is a minimal SIESTA compatibility probe on `tt2d-80p`:

- four nodes;
- one task/node;
- minimal memory;
- two-minute walltime.

Current state: `PENDING (Resources)` due cluster queue/resource pressure.

No production-code modification is authorized while this probe is pending.

## Remaining closure sequence

1. Confirm a compatible multinode partition where selected SIESTA starts.
2. Produce a fresh QRAFT live Slurm selection for that partition.
3. Render the acceptance bundle using that live selection and reviewed runtime evidence.
4. Run generated multinode preflight — PASS required.
5. Run real Hydra SIESTA technical smoke — PASS required.
6. Run independent real srun SIESTA technical smoke — PASS required.
7. Run allocation continuation Job #1 and Job #2 from the exact same package root.
8. Verify interruption/reuse/allocation-history semantics.
9. Verify backend equivalence: same workflow/scientific identity, different ExecutionSpec.
10. Archive final evidence and close M10.

## Deferred hardening

Not M10 blockers unless directly demonstrated otherwise:

- compute-node engine runtime compatibility preflight;
- stronger MPI engine/launcher compatibility evidence;
- duplicated module setup cleanup;
- CLI optional-dependency/lazy-import cleanup.

## Closure rule

A new finding may reopen production code only when it is causally demonstrated
to prevent one of the original M10 gates. Otherwise it is documented as
deferred hardening and M10 proceeds toward closure.
