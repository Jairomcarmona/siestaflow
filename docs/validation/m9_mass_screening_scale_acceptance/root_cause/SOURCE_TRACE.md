# Source Trace and Ownership

The source audit is read-only against baseline
`d17666e028c1bbb2b27d715290312154db6f8440`.

| Concern | Source fact | Consequence |
| --- | --- | --- |
| Runtime work loop | `CompiledWorkflowRuntime.run` creates `ThreadPoolExecutor(max_workers=max_parallel_steps)` and repeatedly scans tasks for readiness. | P=4 is served by the canonical runtime; it is not a parallel side path. |
| State persistence | `_save_state` increments revision, records time, canonicalizes the complete `_state`, hashes the complete payload, then calls `atomic_write_json`. | One transition rewrites an O(N)-sized snapshot. Linear transitions imply O(N²)-like cumulative bytes. |
| Lock scope | `_save_state`, `_event`, and `_set_task` use the same reentrant `_state_lock`. | Same-process state/event persistence is serialized; state-write overlap is not required to explain scaling. |
| Events | `_event` appends canonical JSONL through `append_text` under that same lock. | Event fsync cost can also limit P=4 wall time. |
| Scheduler | `_block_descendants` iterates all tasks each loop; the ready list calls `_is_ready` for every unattempted task. | Independent-task scan calls can grow superlinearly across launch iterations. |
| Atomic filesystem | `RealFileSystem.atomic_write_json` uses a unique `mkstemp` sibling, fsyncs the file, calls `os.replace`, then attempts directory fsync. | No fixed temporary filename collision is present; there is no retry loop. |
| State readers | `execution.campaign_progress.read_campaign_progress` validates schema `1.0`, checksum, task set, and reads `state/workflow_runtime.json`; CLI and result readers consume that helper. | A future persistence change needs a compatible reader/migration plan, not a private format replacement. |
| Resource model | `ResourceCoordinator.try_acquire` consumes CPUs, nodes, and step slots; host exclusivity applies only when required. | P=4 requires four node units as well as 16 CPU units in the generic model. |
| Recovery | `_recover_completed_nodes` validates attempt manifests, runtime fingerprints, evidence hashes, and task identity before reuse. | Any remediation must preserve durable/recoverable completed attempts and current invalidation behavior. |

Persistence decomposition:

| Component | Classification / evidence |
| --- | --- |
| A–B. transitions and `_save_state` calls | **Measured.** `2N+3`: 53 at N=25, 203 at N=100. |
| C–F. materialization, canonical JSON, hash | **Measured jointly.** Wrapper time estimate is `_save_state` minus atomic filesystem time: 0.050–0.417 s. Test-only wrapping cannot split these private in-memory calls without production probes. |
| E. serialized state size | **Measured cumulatively.** 0.269–3.879 MB; mean 5.08–19.11 KB/write. |
| G–J. temp write, flush/fsync, replace, directory fsync | **Source-proven path; measured jointly.** `atomic_write_json` time is 0.180–1.521 s. The existing filesystem boundary does not expose sub-step timings. |
| K. event append | **Measured.** 102/15.8 KB at N=25 and 402/61.5 KB at N=100; time 0.154–1.242 s. |
| L. scheduler scans | **Measured.** 0.001–0.031 s, with superlinear call counts; secondary at this scale. |
| M. attempt/evidence persistence | **Measured.** One immutable manifest/task: 44,650 B at N=25 and 178,700 B at N=100; evidence event bytes are in `measurements.json`. |
| N. lock wait | **Not directly measurable without a production probe.** Peak concurrent state writes=1 and source establishes the shared lock; total persisted time includes any waiting. |

The concrete transition path is: worker or main thread invokes `_set_task` →
holds `_state_lock` → `_event` appends and fsyncs JSONL under that lock →
`_save_state` canonicalizes/hashes the complete state and calls atomic JSON
replacement under the same lock. Main-thread invocation/final state saves also
take the lock. Workers can contend for it, but cannot write the state path
simultaneously in this process.

State/hash compatibility facts:

- The state wrapper has `schema_version="1.0"`, `payload`, and SHA-256 of
  canonical JSON `payload`.
- The payload contains runtime fingerprint, workflow ID, status, revision,
  timestamps/allocation history, and the per-task status/attempt/manifest
  metadata map. Attempt content itself is separately wrapped and hash-bound.
- The state checksum is integrity/recovery/progress evidence. It is not a
  `ScientificIdentity` component; scientific and execution fingerprints are
  already embedded in the runtime/attempt validation paths.
- Recovery loads a completed attempt only after validating state checksum,
  runtime fingerprint, manifest hash/schema/payload, artifact hashes, input
  evidence, and task/attempt identity. Existing state files must remain
  readable or be migrated deterministically.

Owner classification:

- Primary: generic runtime persistence (`qraft.execution.capability_runtime`).
- Secondary measured candidate: generic runtime scheduler scans (same module),
  classified `MEASURABLE_SECONDARY_CONTRIBUTOR`.
- Atomic I/O implementation: filesystem boundary (`qraft.filesystem`).
- Compatibility consumers: `qraft.execution.campaign_progress` and its CLI/result callers.
- Not implicated: scientific identity, execution spec semantics, core contracts, engine capabilities, launcher, or scheduler infrastructure.
