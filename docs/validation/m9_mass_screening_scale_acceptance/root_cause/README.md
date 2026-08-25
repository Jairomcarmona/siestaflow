# M9-R1 Root-Cause and Parallelism Characterization

Status: **characterization only; M9 remains NOT_STARTED.**

This evidence extends, but does not replace, the accepted PRE-FIX/SERIAL
10/25/100/500 baseline in the parent directory. It runs the canonical path:

`WorkflowDefinition → CompiledWorkflow → CompiledWorkflowRuntime → ResourceCoordinator → synthetic capability → Attempt → state/event/evidence → derived summary`.

The new matrix is exactly `N=25/P=1`, `N=25/P=4`, `N=100/P=1`, and
`N=100/P=4`. Each task has one synthetic rank and consumes four CPU units;
P=4 therefore supplies 16 CPU units, four node units, and four runtime
parallel-step slots. No host topology, MPI, SIESTA, scheduler, or alternate
execution authority is asserted or used.

P=4 is empirically real, not assumed: both N=25 and N=100 report four runtime
leases and four overlapping synthetic launcher calls. For each N, the P=1 and
P=4 summaries have identical SHA-256 values. The final summaries are ordered
by `candidate_id`; rank is deterministic by `(scientific_metric, candidate_id)`.

Key finding: state save count remains linear (53 at N=25, 203 at N=100), but
each save canonicalizes, hashes, and atomically rewrites the full task map.
The cumulative bytes therefore grow superlinearly: 273,265 → 3,878,747 for
P=1, and 269,292 → 3,862,714 for P=4. Parallel execution cannot remove this
serialized persistence work. Scheduler readiness scans are also superlinear in
call count, but their measured time is currently secondary.

The earlier native-Windows `WinError 5` recovery observation is preserved in
the parent evidence. It did **not** reproduce in this one P=4 matrix
experiment (`atomic_winerror_5=0`); its current classification is therefore
`NOT_REPRODUCED_CAUSE_UNRESOLVED`, not a confirmed product race.

Contents:

- `RESULT.md` — measured matrix and conclusion.
- `SOURCE_TRACE.md` — production source ownership and compatibility facts.
- `CONCURRENCY_MODEL.md` — source-derived allocation and lock model.
- `WINDOWS_ATOMIC_IO.md` — bounded Windows classification and retry policy.
- `DESIGN_OPTIONS.md` — future alternatives and compatibility gates; no fix.
- `TEST_RESULTS.md` — focused validation results and the bounded pytest environment block.
- `measurements.json` / `measurements.csv` — raw aggregate measurements.
- `summaries.json` / `summary_hashes.json` — deterministic derived summaries.
- `commands.txt` — exact valid matrix command.
