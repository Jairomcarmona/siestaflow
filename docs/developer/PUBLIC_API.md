# Public API and extension points

## Typed capability integration metadata (U-Q8)

`qraft.contracts.CapabilitySupport` and its `CapabilityTarget`,
`CancellationSupport` and `ResumeSupport` enums describe deployment modes,
targets, cancel/resume semantics and source test references. Put
`support.to_mapping()` under the opt-in namespaced
`CapabilityDescriptor.metadata['qraft.integration']` key. Read it using public
`capability_support(descriptor)`; absence returns `None`, meaning **not declared**.
The extension version is `1.0`; unknown fields, versions, target/support enums,
non-boolean-to-enum coercions, malformed mode codes and duplicate entries are
rejected when constructing the descriptor. Other metadata namespaces are
preserved. Mode codes include `HF-1` without admitting it for execution.

The extension has fields `schema_version`, `modes` (code array), `targets` (enum
array), `supports` (`cancel`, `resume`) and `test_refs` (source-reference array).
It changes no existing default descriptor fields or native digests. Test
references name tests to run; their presence is not proof those tests passed.
`catalog_state`, `admitted_for` and actual qualification receipts belong to the
platform and cannot be claimed through this extension. In particular, a plugin
cannot self-declare runtime or scientific qualification by listing a target.

## CLI JSON compatibility decision (U-Q6)

All CLI `--json` payloads, including `check`, `status`, `run inspect` and
`advanced run ...`, are **non-contractual diagnostic output** in 0.2. No versioned
payload schema is promised for them. They are intended for logging and human
inspection; do not build platform state, authority or scientific decisions on
their field names. CLI command/exit-code stability does not imply JSON-field
stability. The Python integration consumer uses `qraft.api` typed
`WorkflowCompilation`, `RunPreparationResult`, `PreparedRunInspection` and
`ResumePlan` plus native public contract objects. Persist native locks as their
original bytes/digests, never recanonicalize CLI output into evidence.

Consumer fixtures assert this compatibility classification and exercise typed
descriptor round-trips, future-enum/version rejection and unchanged legacy
descriptor digests. A future versioned CLI JSON format must have a distinct
schema/version and fixtures before becoming contractual; this change does not
silently freeze the current diagnostics.

## Integration API 1.0 (Ola 1)

Block 2 additionally exports `EosProtocol`, `ElectronicAnalysisProtocol`,
`ElectronicPropertiesProtocol`, `ElectronicStateSource`,
`PreparedElectronicProperties`, and the existing `BandPathSpec`, `DosSpec`,
`PdosSpec`, `PropertySpec` input types through `qraft.api`. API_VERSION remains
1.0; native DTOs and contracts are unchanged. EOS inputs/results remain their
existing mappings. Electronic execution still requires the verified M6 handoff;
an operator SCF is not an electronic-state artifact. The explicitly authorized
`ProvisionalScfSource` route verifies SCF stdout, FDF, density matrix and pseudos
and records `NUMERICAL_CANDIDATE` / `SCF directo provisional` in separate
`parent_scf` evidence. It qualifies the pipeline only. ElectronicAnalysisProtocol
requires a private `worker_lock_path` identifying both SIESTA and fat before
execution. T-042 registration in the platform worker remains outside this block.

`scientific_policy_document(policy_id)` delivers detached JSON documents for
the approved EOS, electronic and preset policies, rejecting unknown IDs. The
platform hashes these documents using its contractual JCS canonicalization;
QRAFT native artifact digests keep their existing algorithms. No convergence
policy ID or threshold is fabricated by this provider.
The authorized `rule_document` option validates an explicit versioned
convergence rule against the existing Mesh/KGrid rule models and returns its
unchanged JSON copy. The ID must match `rule_id`; legacy unversioned IDs require
an operator decision. The corresponding rule, observation, report and evaluator
types are exported through `qraft.api`. Validation is not scientific approval:
results remain provisional and require human acceptance outside this block.
`scientific_policy_evidence()` retains the literal policy/protocol IDs and
document in an existing extensible SCIENTIFIC_ARTIFACT envelope. Its native
content digest is `qraft.content-sha256-v1`; it is independent of the platform's
JCS policy-document digest. Store and verify this envelope with its original
bytes. The envelope stays PROVISIONAL, including operator-supplied rules.

`qraft.api.__all__` is additionally public, with `API_VERSION = "1.0"`.
It exports the typed compose → compile → prepare → inspect route, its request,
result and policy types, lock readers/writer, contextual validator, canonical
controller and compiled runtime. The existing `qraft.__all__` is unchanged.
Changes to this surface follow the package 0.x compatibility policy; API version
and native contract versions are independent. No CLI JSON surface is promoted.

`WorkflowCompiler.compile_mapping(definition, source_root=..., source_bytes=None)`
uses `source_root` to resolve external artifacts without creating a definition
file. Native definition identity remains the SHA-256 of **document bytes**.
Without `source_bytes` it hashes compact, sorted UTF-8 JSON; with verified original
JSON/YAML bytes it returns the exact same lock as `compile(path)`. Different
whitespace or serialization still means a different native definition digest.
Supplied bytes disagreeing with the mapping are rejected. Legacy digests and
`compile(path)` are unchanged.

`RunPreparer(repository_root, task_adapters={capability_id: callable})` explicitly
registers preparation adapters. The callable receives `task` and keyword arguments
`by_task`, `artifacts`, `resolved_sources`, `profile`, `protected`, and returns one
controller task mapping. It must protect every scientific input in `protected`
(relative path → source Path); package validation and hashes remain mandatory.
Built-in adapters cannot be replaced. This does not execute or authorize tasks.

`CanonicalController.from_file(..., register_capabilities=callback,
capability_bindings={task_id: capability_id})` invokes the callback on its fresh
registry after built-ins and before freezing. Bindings require a verified prepared
run package and must equal the capability already fixed in its native workflow
lock. An arbitrary runtime override is forbidden. Effective capability IDs enter
the compiled workflow payload and runtime fingerprint before any attempts. The
registry rejects duplicate IDs, incomplete implementations and incompatible
contracts. Installed external capability dependencies are the deployment's
responsibility; they are not copied or dynamically discovered in QRAFT. The
legacy worker continues to use its existing built-ins; HF-1 orchestration and HPC
qualification remain pending, rather than calling Hubbard through a generic
command or pretending to establish its scientific outcome.

Consumer fixtures: `tests/consumer/`; reproducible CPython 3.12.10/uv 0.11.14
environment: `uv sync --locked --extra dev --group ci --python 3.12.10`.
The Windows/Linux consumer gate builds and tests an installed wheel outside the
checkout with isolated Python. Existing complete Linux 3.11–3.13 regressions
remain separate; this Windows gate does not claim HPC acceptance.

## Runtime boundaries (U-Q7, U-Q4, U-Q5)

`CompiledWorkflowRuntime` and `CanonicalController.from_file` accept
`authority_check: Callable[[AuthorityBoundary], bool]` and an explicit positive
decimal-string `authority_generation`. A trusted caller verifies ownership using
the run fingerprint and generation. Exactly `True` permits a boundary; false,
non-boolean answers or exceptions latch `AuthorityLost`, stop new launches and
request termination of active launchers. Checks precede attempt reservation,
launch, state/journal/event publication, immutable attempt publication and final
controller summary. No canonical publication occurs after denial. Adapter or
launcher writes outside this API are the caller's responsibility.
Fenced native events and attempt manifests record the decimal-string generation;
the generation does not alter scientific identity or native lock digests.

The callback is a **boundary hook, not an atomic multi-process lease**. Remote
launch and artifact publication must enforce the same token to close the
check/use race. Without a callback the original conservative single-controller
policy applies. No takeover or multi-worker safety is advertised by this change.

`NativeEventStream` publishes additive `stream_id`, `sequence` (starting at 1)
and `event_id` fields in the existing native JSONL. The UUID and high-water mark
are persisted in the adjacent `.stream.json`; sequence and IDs survive runtime
restart and replay. Read pages using `read(after=cursor, limit=...)`; cursors are
opaque and scoped to that native stream. Retain JSONL and metadata together.
There is no automatic rotation. Truncation, deletion, changed identities, partial
tails and foreign writers fail closed with diagnostics; do not repair in place.
Legacy complete lines receive stable derived replay identities without rewriting
their original bytes. A missing stream header has no stable replay and requires
platform snapshot/reconciliation, rather than an invented cursor. These native
IDs remain distinct from platform EventRecord IDs and cursors.
New native runtime state journals/snapshots retain `native_event_stream_id` as an
independent reference; losing both event files after initialization cannot create
a replacement stream or rewind existing cursors. Old pre-feature runtime state
with no stable ID can adopt complete legacy lines once, preserving their bytes.

`RunInspector.resume(..., terminal_evidence=TerminalSchedulerEvidence(...),
verify_terminal_evidence=verifier, expected_job=SchedulerJobIdentity(...))` is a
read-only verified resubmission plan. The receipt must match native run ID, both
lock digests and the last observed allocation, including cluster/user from the
trusted expected identity. It contains terminal `sacct` state, explicit absence
of a live/requeued allocation, timezone-aware observation/expiry, signer ID and
signature. The verifier validates **the exact `signed_bytes()`** and signature
against trusted keys; secrets and keys never enter engine state. Current time
must be in the observation validity interval. Unknown jobs, mismatched scope,
missing verifier, failure or expiry cannot permit resume. The synthetic consumer
fixture verifies a real HMAC; it is not cluster evidence or a signing service.

The legacy CLI flag `--previous-job-terminal` is still a human assertion for
compatibility and is unsuitable for platform reconciliation. The platform must
use the typed verified path, never trust the flag. Planning never performs
`sbatch` or proves scientific success. Collection/signing of live scheduler
evidence and production generation enforcement remain deployment qualifications.

When specialized `capability_bindings` are active, effective workflow metadata
references the **verified** original workflow/run lock content digests under
`qraft.native_contract_bindings`. These references enter the runtime fingerprint,
so a changed native contract or task policy cannot silently reuse an old attempt
with unchanged translated capability ID. No original lock/settings are rewritten
or recanonicalized by this binding; the legacy path without bindings preserves
its previous fingerprint semantics.

For package version 0.2, only names in `qraft.__all__` are intentional public
Python API: application/configuration, ScientificIdentity, ExecutionSpec,
ExecutionProfile/ProfileStore, OutputModel, engine/launcher/scheduler adapter
protocols, and M7.1 neutral band-path planning models. The latter comprise
`CrystalStructure`, `BandPathMode`, `BandPathRequest`, `BandPathSegment`,
`BandPathProposal`, `BandPathPlanner`, `SymmetryAnalysis`, `ProviderPath`, and
`SymmetryPathProvider`. All other modules are internal unless a specific
contract document declares otherwise.

M8-A additionally exposes the neutral collinear-spin models
`CollinearSpinSpec`, `CollinearSpinMoment`, and `CollinearMomentToken`.  They
represent only `Spin polarized`, `DM.InitSpin`, and optional `Spin.Fix` /
`Spin.Total`; non-collinear angles, SOC, spirals, and Hubbard parameters are
not representable by this API.

M8-B additionally exposes `NonCollinearSpinSpec` and
`NonCollinearSpinMoment`.  They model only `Spin non-colinear` and
`DM.InitSpin` polarization with optional explicit theta/phi directions.  SOC,
Spin.Spiral, DFT+U/Hubbard, and execution controls remain outside this API.

M8-C additionally exposes `SpinOrbitSpec`.  It intentionally reuses
`NonCollinearSpinMoment` for `Spin spin-orbit` directional `DM.InitSpin`
rows; full SOC requires engine-verified fully-relativistic PSML inputs.
Onsite SOC, `Spin.OrbitStrength`, spin spirals, Hubbard controls, orbital
moments, and execution controls are not representable.

Public CLI stability is documented in `docs/user/cli.md`. Persistent schema
stability is independent from Python import stability.

## Extensions

- Engine: implement `EngineAdapter`, declare executable/version probing through
  `EngineRegistry`, and register a protocol that names the engine.
- Launcher: register a `RegisteredLauncher` with factory, resource invariants,
  default command and probe metadata. Do not add a global launcher `if/elif`.
- Scheduler: register a `RegisteredScheduler` with command/environment probe
  metadata.
- Protocol: register a `ProtocolAdapter` with planner, runner, engine and
  accepted parameters. Planning must not authorize execution.
- Output: implement `OutputContributor`; machine evidence remains authoritative.
- Symmetry path: implement `SymmetryPathProvider` using only neutral
  `CrystalStructure`, `SymmetryAnalysis`, and `ProviderPath` values. A provider
  must never introduce an execution authority or transform an M6 parent
  structure silently.

Tests for a new adapter must cover missing executable, resource validation,
command rendering and registry extension. Never add cluster-specific defaults
to the core.

## Installed preparation and generated-runtime boundary

`RunPreparer()` and `ControllerPackageBuilder()` use the installed distribution's
Python sources and packaged engine resources by default. An explicit
`repository_root` still selects that checkout's `src/qraft` tree; a missing
explicit tree is an error, with no silent fallback. Installed preparation records
no invented Git commit or clean-tree assertion. Source revision qualification is
the deployment manifest's responsibility. Native workflow/run hashes and input
script bytes retain their existing algorithms.

A prepared package vendors the transitive inspection/profile/scheduler-evidence
and workflow modules required by frozen `CanonicalController` bindings. Its
`runtime/` is an allocation-runtime subset, not an installation of the full
authoring `qraft.api` facade. Platform authoring uses the installed wheel; generated
workers use `qraft.execution.canonical_controller.CanonicalController`. The same
class verifies original native lock references before creating its runtime.

The installed consumer gate prepares and inspects a real adaptive fixture and
checks ZIP member bytes outside the checkout, then starts a subprocess with
`-I -S` loading only the package runtime. It checks frozen bindings/fingerprints
and rejects authority before any attempt or launch. External scheduler placement
probes are explicit fixture seams; this proves packaging, not HPC or scientific
acceptance.
