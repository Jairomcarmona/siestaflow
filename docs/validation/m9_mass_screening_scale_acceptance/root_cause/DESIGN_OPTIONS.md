# Future Design Options (Not Implemented)

The primary problem is repeated O(N)-sized durable state snapshots at O(N)
transitions. The smallest compatible next change should remain in the generic
runtime persistence layer; it must not move this responsibility to a protocol,
capability, engine, scheduler, or launcher.

| Option | Benefit | Main compatibility/recovery risk | Assessment |
| --- | --- | --- | --- |
| A. Coalesce full snapshots at explicit durability boundaries | Smallest code change; preserves current snapshot reader. | A crash between transitions can lose more progress unless an explicit durable journal exists. | Insufficient alone until durability/recovery contract is made explicit. |
| B. Append deterministic transition journal plus periodic canonical snapshot | Near-linear append volume; preserves durable transition history and permits bounded snapshot rewrite frequency. | Requires schema/versioning, replay, checksum/ordering rules, compaction, and reader migration. | Recommended minimum design direction. |
| C. Per-task durable records plus deterministic aggregate reconstruction | Reduces whole-map rewrites and isolates task writes. | Many files, aggregate consistency, recovery ordering, and current canonical-state reader compatibility. | Viable but broader change than B. |

Cross-option constraints: A has the lowest implementation complexity but does
not by itself retain a durable transition history. B gives append-oriented
bytes/CPU and bounded snapshot cost while retaining a deterministic canonical
checkpoint; it has medium migration/recovery/test burden. C can reduce global
lock scope further but has the greatest reconstruction and filesystem-entry
burden. All three must retain deterministic ordering, attempt immutability,
state checksum meaning, failure propagation, and exact recovery/reuse. On both
Windows and POSIX, durable append/snapshot operations need explicit crash and
replacement semantics; no option is assumed to cure `WinError 5` without a
native persistent-workspace test.

Recommended next design: **Option B**, with the present canonical snapshot
retained as a materialized compatibility checkpoint during migration. This is
not an implementation authorization and does not choose a batching threshold.

Required future gates before implementation:

1. Define state schema/version and backward reader/migration behavior for
   `campaign_progress`, CLI, and result readers.
2. Preserve checksum validation, runtime fingerprint binding, attempt manifest
   validation, immutable attempts, dependency blocking, and exact reuse.
3. Add deterministic P=1/P=4 characterization tests that preserve summary
   hashes and ordering; keep the present baseline data for comparison.
4. Add crash/restart tests at journal/snapshot boundaries, including partial
   compaction and corrupt journal/snapshot rejection.
5. Run a persistent native Windows workspace test for atomic failures without
   masking `WinError 5`; report it separately from scientific correctness.
6. Characterize scheduler scans independently after persistence work is
   reduced, rather than conflating the two bottlenecks.
7. Preserve `candidate_id,status,scientific_metric,rejection_reason,rank` and
   identical logical summary hashes across P=1/P=4.
8. Re-run the focused immutable-attempt, corrupt-artifact, sibling-isolation,
   dependent-blocking, interruption, and allocation-rollover tests.

Likely owner files for that future scoped goal are
`src/qraft/execution/capability_runtime.py` (state transition/persistence
orchestration), `src/qraft/filesystem.py` (durable append/atomic primitives if
needed), and `src/qraft/execution/campaign_progress.py` (compatible reader).
No change is proposed for `qraft.core`, `qraft.contracts`,
`ResourceCoordinator`, scheduler/launcher behavior, `ScientificIdentity`, or
`ExecutionSpec`.

ADR classification: **`NO_ADR_REQUIRED`**, provided the migration preserves the
current reader contract or updates all in-repository readers compatibly. The
change remains within generic-runtime persistence ownership; it neither moves
responsibility, creates execution authority, nor changes ScientificIdentity or
ExecutionSpec semantics. No contract gap has been demonstrated.
