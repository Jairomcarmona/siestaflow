"""Engine-neutral execution authority for compiled QRAFT workflows.

The runtime owns DAG state, immutable attempts, recovery, artifact integrity,
and process lifecycle.  Registered capabilities own input preparation, command
construction, parsing, artifact discovery, and technical classification.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..contracts import (
    EXECUTION_EVIDENCE,
    EXECUTION_REQUEST,
    CapabilityRegistry,
    CompiledWorkflow,
    ContractCompatibilityError,
    WorkflowTaskNode,
)
from ..core import (
    Attempt,
    ExecutionSpec,
    NodeResult,
    ScientificDecision,
    ScientificIdentity,
    TechnicalValidation,
)
from ..filesystem import RealFileSystem
from .adapters import launcher_registry
from .resource_coordinator import (
    CooperativeShutdown,
    ResourceCoordinator,
    ResourceLease,
    ResourceRequest,
    RuntimeAllocation,
    ShutdownControl,
    local_allocation,
)
from .srun_launcher import StepLaunchSpec, StepLauncher, StepOutcome


_TERMINAL_FAILURES = {"FAILED", "BLOCKED", "CANCELLED"}
_EXECUTABLE_CAPABILITY_METHODS = (
    "inspect_input",
    "validate_input",
    "prepare_task",
    "build_command",
    "parse_output",
    "discover_artifacts",
    "classify_result",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _safe_relative(value: str, *, field: str) -> Path:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe relative path in {field}: {value!r}")
    return Path(*path.parts)


def normalize_technical_validation(value: object) -> TechnicalValidation:
    """Normalize a capability-owned classification without engine knowledge."""

    if isinstance(value, TechnicalValidation):
        return value
    raw_status = getattr(value, "status", None)
    status = getattr(raw_status, "value", raw_status)
    if status is None:
        raise TypeError("capability classification must expose status")
    raw_classification = getattr(value, "classification", type(value).__name__)
    classification = str(getattr(raw_classification, "value", raw_classification))
    raw_reasons = getattr(value, "reasons", None)
    if raw_reasons is None:
        reason = getattr(value, "reason", None)
        raw_reasons = (str(reason),) if reason else tuple(
            map(str, getattr(value, "evidence", ()))
        )
    elif isinstance(raw_reasons, str):
        raw_reasons = (raw_reasons,)
    summary = asdict(value) if is_dataclass(value) else {}
    return TechnicalValidation(
        status=str(status),
        classification=classification,
        reasons=tuple(map(str, raw_reasons)),
        parser_summary=summary,
    )


@dataclass(frozen=True)
class WorkflowRuntimeResult:
    status: str
    node_results: Mapping[str, NodeResult]
    attempts: Mapping[str, Attempt]
    reused_nodes: tuple[str, ...]
    peak_cpus: int = 0
    peak_nodes: int = 0
    peak_parallel_steps: int = 0


class CompiledWorkflowRuntime:
    """Execute a :class:`CompiledWorkflow` through ``CapabilityRegistry``."""

    STATE_SCHEMA = "1.0"
    MANIFEST_SCHEMA = "1.0"

    def __init__(
        self,
        *,
        workflow: CompiledWorkflow,
        registry: CapabilityRegistry,
        root: Path,
        source_root: Path,
        scientific_identities: Mapping[str, ScientificIdentity],
        execution_specs: Mapping[str, ExecutionSpec] | ExecutionSpec,
        launcher: StepLauncher | Mapping[str, StepLauncher],
        allocation: RuntimeAllocation | None = None,
        shutdown: ShutdownControl | None = None,
        poll_interval_seconds: float = 0.05,
        force_new_attempts: bool = False,
    ) -> None:
        if not registry.frozen:
            raise ValueError("capability registry must be frozen before execution")
        self.workflow = workflow
        self.registry = registry
        self.root = root.resolve()
        self.source_root = source_root.resolve()
        self.scientific_identities = dict(scientific_identities)
        self.execution_specs = (
            {task.task_id: execution_specs for task in workflow.tasks}
            if isinstance(execution_specs, ExecutionSpec)
            else dict(execution_specs)
        )
        task_ids = {task.task_id for task in workflow.tasks}
        if set(self.scientific_identities) != task_ids:
            raise ValueError("scientific identity mapping must cover every task")
        if set(self.execution_specs) != task_ids:
            raise ValueError("execution spec mapping must cover every task")
        if isinstance(launcher, Mapping):
            if not launcher:
                raise ValueError("launcher mapping must not be empty")
            self.launchers = {
                str(name).strip().casefold(): value
                for name, value in launcher.items()
            }
        else:
            self.launchers = {"*": launcher}
        requests = tuple(self._resource_request(task) for task in workflow.tasks)
        self.allocation = allocation or local_allocation(requests)
        self.coordinator = ResourceCoordinator(self.allocation)
        self.shutdown = shutdown or CooperativeShutdown()
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self.force_new_attempts = bool(force_new_attempts)
        self.filesystem = RealFileSystem()
        self.state_path = self.root / "state" / "workflow_runtime.json"
        self.events_path = self.root / "evidence" / "workflow_events.jsonl"
        self._state: dict[str, Any] = {}
        self._results: dict[str, NodeResult] = {}
        self._attempts: dict[str, Attempt] = {}
        self._reused: set[str] = set()
        self._assigned_hosts: dict[str, tuple[str, ...]] = {}
        self._state_lock = threading.RLock()

    @property
    def runtime_fingerprint(self) -> str:
        payload = {
            "workflow": self.workflow.payload(),
            "scientific": {
                key: value.fingerprint
                for key, value in sorted(self.scientific_identities.items())
            },
            "execution": {
                key: value.fingerprint
                for key, value in sorted(self.execution_specs.items())
            },
            "capability_provenance": self._capability_provenance(),
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

    def _capability_provenance(self) -> dict[str, dict[str, str]]:
        provenance: dict[str, dict[str, str]] = {}
        for task in sorted(self.workflow.tasks, key=lambda item: item.task_id):
            try:
                registered = self.registry.resolve(task.capability_id)
            except KeyError:
                # The workflow payload already binds an unresolved identifier;
                # preserve the existing runtime behavior that reports it as
                # blocked rather than failing while initializing state.
                provenance[task.task_id] = {"capability_id": task.capability_id}
                continue
            provenance[task.task_id] = {
                "capability_id": registered.descriptor.capability_id,
                "implementation_version": registered.descriptor.implementation_version,
                "plugin_id": registered.plugin.plugin_id,
                "plugin_version": registered.plugin.plugin_version,
            }
        return provenance

    def _resource_request(self, task: WorkflowTaskNode) -> ResourceRequest:
        execution = self.execution_specs[task.task_id]
        try:
            requires_hosts = bool(
                launcher_registry.require(execution.launcher).requires_hosts
            )
        except ValueError:
            # Explicitly composed fixture/custom launchers need no global
            # registry mutation unless they request host-aware placement.
            requires_hosts = False
        return ResourceRequest(
            task_id=task.task_id,
            cpus=execution.allocated_cpus,
            nodes=execution.nodes,
            exclusive_hosts=requires_hosts,
        )

    def _launcher_for(self, task: WorkflowTaskNode) -> StepLauncher:
        name = self.execution_specs[task.task_id].launcher.casefold()
        if name in self.launchers:
            return self.launchers[name]
        if "*" in self.launchers:
            return self.launchers["*"]
        raise ValueError(f"no launcher composed for execution adapter: {name}")

    def _terminate_launchers(self) -> tuple[str, ...]:
        affected: set[str] = set()
        seen: set[int] = set()
        for launcher in self.launchers.values():
            identity = id(launcher)
            if identity in seen:
                continue
            seen.add(identity)
            affected.update(launcher.terminate_all())
        return tuple(sorted(affected))

    def _remaining_allocation_allows(self, task: WorkflowTaskNode) -> bool:
        estimate = float(
            task.resources.get(
                "estimated_runtime_seconds",
                self.execution_specs[task.task_id].walltime_seconds,
            )
        )
        if estimate < 0:
            raise ValueError("estimated_runtime_seconds cannot be negative")
        required = estimate + self.allocation.shutdown_margin_seconds
        return self.allocation.remaining_seconds() > required

    def run(self) -> WorkflowRuntimeResult:
        self.root.mkdir(parents=True, exist_ok=True)
        self._verify_external_artifacts()
        self._load_or_initialize_state()
        self._recover_completed_nodes()
        invocation = {
            "allocation_id": self.allocation.allocation_id,
            "started_at": _utc_now(),
            "capacity": {
                "cpus": self.allocation.total_cpus,
                "nodes": self.allocation.total_nodes,
                "max_parallel_steps": self.allocation.max_parallel_steps,
                "hosts": list(self.allocation.hosts),
            },
        }
        with self._state_lock:
            self._state.setdefault("allocation_history", []).append(invocation)
            self._save_state()
        self._event("RUNTIME_INVOCATION_STARTED", **invocation)
        attempted_this_run: set[str] = set()

        active: dict[Future[None], tuple[WorkflowTaskNode, ResourceLease]] = {}
        with ThreadPoolExecutor(
            max_workers=self.allocation.max_parallel_steps
        ) as executor:
            while True:
                self._block_descendants()
                if (
                    not self.shutdown.requested
                    and self.allocation.remaining_seconds()
                    <= self.allocation.shutdown_margin_seconds
                ):
                    self.shutdown.request("WALLTIME_MARGIN")
                    self._event(
                        "WALLTIME_LAUNCH_STOP",
                        remaining_seconds=self.allocation.remaining_seconds(),
                    )

                launched = False
                if not self.shutdown.requested:
                    ready = [
                        task
                        for task in self.workflow.tasks
                        if task.task_id not in attempted_this_run
                        and self._is_ready(task)
                    ]
                    for task in ready:
                        request = self._resource_request(task)
                        if not self.coordinator.can_ever_fit(request):
                            attempted_this_run.add(task.task_id)
                            self._set_task(
                                task.task_id,
                                "BLOCKED",
                                "resource request exceeds allocation capacity",
                            )
                            continue
                        if not self._remaining_allocation_allows(task):
                            self.shutdown.request("INSUFFICIENT_WALLTIME")
                            self._event(
                                "WALLTIME_LAUNCH_STOP",
                                task_id=task.task_id,
                                remaining_seconds=self.allocation.remaining_seconds(),
                            )
                            break
                        lease = self.coordinator.try_acquire(request)
                        if lease is None:
                            continue
                        attempted_this_run.add(task.task_id)
                        self._assigned_hosts[task.task_id] = lease.hosts
                        future = executor.submit(self._execute_task, task)
                        active[future] = (task, lease)
                        launched = True
                        self._event(
                            "RESOURCE_ACQUIRED",
                            task_id=task.task_id,
                            cpus=lease.cpus,
                            nodes=lease.nodes,
                            hosts=list(lease.hosts),
                        )

                if active:
                    if self.shutdown.requested:
                        immediate = self.shutdown.reason == "SIGTERM"
                        grace_expired = (
                            self.shutdown.elapsed_seconds
                            >= self.allocation.termination_grace_seconds
                        )
                        if (
                            immediate
                            or grace_expired
                            or self.allocation.remaining_seconds() <= 1
                        ):
                            affected = self._terminate_launchers()
                            if affected:
                                self._event(
                                    "ACTIVE_ATTEMPTS_TERMINATED",
                                    attempt_ids=list(affected),
                                    reason=self.shutdown.reason,
                                )
                    done, _ = wait(
                        tuple(active),
                        timeout=self.poll_interval_seconds,
                        return_when=FIRST_COMPLETED,
                    )
                    for future in done:
                        task, lease = active.pop(future)
                        try:
                            future.result()
                        except Exception as exc:  # defensive isolation
                            self._set_task(
                                task.task_id,
                                "INCOMPLETE",
                                f"runtime worker error: {type(exc).__name__}: {exc}",
                            )
                        finally:
                            self._assigned_hosts.pop(task.task_id, None)
                            self.coordinator.release(lease)
                            self._event(
                                "RESOURCE_RELEASED",
                                task_id=task.task_id,
                                cpus=lease.cpus,
                                nodes=lease.nodes,
                                hosts=list(lease.hosts),
                            )
                    continue
                if not launched:
                    break

        self.coordinator.assert_released()

        statuses = {
            task_id: record["status"]
            for task_id, record in self._state["tasks"].items()
        }
        if all(value == "COMPLETED" for value in statuses.values()):
            overall = "COMPLETED"
        elif self.shutdown.requested:
            overall = "INTERRUPTED"
        elif any(value == "FAILED" for value in statuses.values()):
            overall = "FAILED"
        elif any(value == "INTERRUPTED" for value in statuses.values()):
            overall = "INTERRUPTED"
        else:
            overall = "BLOCKED"
        self._state["status"] = overall
        invocation.update(
            {
                "finished_at": _utc_now(),
                "status": overall,
                "peak_cpus": self.coordinator.peak_cpus,
                "peak_nodes": self.coordinator.peak_nodes,
                "peak_parallel_steps": self.coordinator.peak_steps,
            }
        )
        self._event("RUNTIME_INVOCATION_FINISHED", **invocation)
        self._save_state()
        return WorkflowRuntimeResult(
            overall,
            dict(self._results),
            dict(self._attempts),
            tuple(sorted(self._reused)),
            self.coordinator.peak_cpus,
            self.coordinator.peak_nodes,
            self.coordinator.peak_steps,
        )

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": self.STATE_SCHEMA,
            "runtime_fingerprint": self.runtime_fingerprint,
            "workflow_id": self.workflow.workflow_id,
            "status": "PENDING",
            "revision": 0,
            "allocation_history": [],
            "tasks": {
                task.task_id: {
                    "status": "PENDING",
                    "attempts": 0,
                    "last_attempt": None,
                    "manifest_sha256": None,
                    "reason": "not started",
                    "depends_on": list(task.dependencies),
                }
                for task in self.workflow.tasks
            },
        }

    def _load_or_initialize_state(self) -> None:
        if not self.state_path.is_file():
            self._state = self._initial_state()
            self._save_state()
            return
        wrapper = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload = wrapper.get("payload")
        if wrapper.get("schema_version") != self.STATE_SCHEMA or not isinstance(payload, dict):
            raise ValueError("invalid workflow runtime state schema")
        if hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest() != wrapper.get("sha256"):
            raise ValueError("workflow runtime state checksum mismatch")
        if payload.get("runtime_fingerprint") != self.runtime_fingerprint:
            raise ValueError("workflow runtime identity mismatch")
        if set(payload.get("tasks", {})) != {task.task_id for task in self.workflow.tasks}:
            raise ValueError("workflow runtime task set mismatch")
        self._state = payload

    def _save_state(self) -> None:
        with self._state_lock:
            self._state["revision"] = int(self._state.get("revision", 0)) + 1
            self._state["updated_at"] = _utc_now()
            payload = json.loads(_canonical(self._state))
            wrapper = {
                "schema_version": self.STATE_SCHEMA,
                "payload": payload,
                "sha256": hashlib.sha256(
                    _canonical(payload).encode("utf-8")
                ).hexdigest(),
            }
            self.filesystem.atomic_write_json(self.state_path, wrapper)

    def _event(self, event: str, **fields: object) -> None:
        with self._state_lock:
            record = {"event": event, "at": _utc_now(), **fields}
            self.filesystem.append_text(
                self.events_path, _canonical(record) + "\n"
            )

    def _set_task(self, task_id: str, status: str, reason: str, **fields: object) -> None:
        with self._state_lock:
            current = self._state["tasks"][task_id]
            previous = current["status"]
            current.update({"status": status, "reason": reason, **fields})
            self._event(
                "TASK_STATE",
                task_id=task_id,
                previous=previous,
                status=status,
                reason=reason,
            )
            self._save_state()

    def _verify_external_artifacts(self) -> None:
        for artifact in self.workflow.external_artifacts:
            path = self.source_root / _safe_relative(
                artifact.relative_path, field="external artifact"
            )
            if not path.is_file():
                raise ValueError(f"external artifact missing: {artifact.relative_path}")
            if _sha_file(path) != artifact.sha256:
                raise ValueError(f"external artifact hash mismatch: {artifact.relative_path}")

    def _recover_completed_nodes(self) -> None:
        for task in self.workflow.tasks:
            record = self._state["tasks"][task.task_id]
            if record["status"] != "COMPLETED":
                if record["status"] == "RUNNING":
                    self._set_task(task.task_id, "INTERRUPTED", "crashed RUNNING attempt")
                continue
            if self.force_new_attempts:
                self._set_task(
                    task.task_id,
                    "PENDING",
                    "force new attempt requested",
                    manifest_sha256=None,
                )
                continue
            try:
                attempt = self._load_valid_attempt(task, record)
            except (OSError, TypeError, ValueError) as exc:
                self._set_task(
                    task.task_id,
                    "PENDING",
                    f"persisted completion rejected: {exc}",
                    manifest_sha256=None,
                )
                continue
            self._attempts[task.task_id] = attempt
            self._results[task.task_id] = attempt.result
            self._reused.add(task.task_id)
            self._event(
                "ATTEMPT_REUSED",
                task_id=task.task_id,
                attempt_id=attempt.attempt_id,
            )

    def _load_valid_attempt(
        self, task: WorkflowTaskNode, record: Mapping[str, Any]
    ) -> Attempt:
        attempt_id = str(record.get("last_attempt") or "")
        if not attempt_id:
            raise ValueError("completed task lacks attempt identity")
        attempt_root = self._attempt_path(task.task_id, attempt_id)
        manifest_path = attempt_root / "attempt.json"
        if not manifest_path.is_file():
            raise ValueError("attempt manifest missing")
        expected_manifest = str(record.get("manifest_sha256") or "")
        if _sha_file(manifest_path) != expected_manifest:
            raise ValueError("attempt manifest hash mismatch")
        wrapper = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = wrapper.get("payload")
        if wrapper.get("schema_version") != self.MANIFEST_SCHEMA or not isinstance(payload, dict):
            raise ValueError("attempt manifest schema invalid")
        if hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest() != wrapper.get("sha256"):
            raise ValueError("attempt manifest checksum mismatch")
        if payload.get("runtime_fingerprint") != self.runtime_fingerprint:
            raise ValueError("attempt runtime identity mismatch")
        attempt = self._attempt_from_dict(payload["attempt"])
        if attempt.node_id != task.task_id or attempt.attempt_id != attempt_id:
            raise ValueError("attempt identity mismatch")
        if attempt.result.execution_state != "COMPLETED" or attempt.result.technical_validation.status != "PASS":
            raise ValueError("attempt is not technically completed")
        for relative, digest in attempt.artifacts.items():
            path = attempt_root / _safe_relative(relative, field="attempt artifact")
            if not path.is_file() or _sha_file(path) != digest:
                raise ValueError(f"attempt artifact mismatch: {relative}")
        for relative, digest in payload.get("input_evidence", {}).items():
            path = attempt_root / _safe_relative(relative, field="input evidence")
            if not path.is_file() or _sha_file(path) != digest:
                raise ValueError(f"attempt input evidence mismatch: {relative}")
        for relative, digest in payload.get("working_input_evidence", {}).items():
            path = attempt_root / _safe_relative(relative, field="working input evidence")
            if not path.is_file() or _sha_file(path) != digest:
                raise ValueError(f"attempt working input mismatch: {relative}")
        input_sources = payload.get("input_sources")
        if input_sources is not None:
            if not isinstance(input_sources, dict):
                raise ValueError("attempt input source evidence invalid")
            current_sources = self._resolve_inputs(task)
            if set(current_sources) != set(input_sources):
                raise ValueError("attempt input source set mismatch")
            for name, path in current_sources.items():
                if _sha_file(path) != input_sources[name]:
                    raise ValueError(f"attempt input source mismatch: {name}")
        for relative, digest in payload.get("evidence_files", {}).items():
            path = attempt_root / _safe_relative(relative, field="attempt evidence")
            if not path.is_file() or _sha_file(path) != digest:
                raise ValueError(f"attempt evidence mismatch: {relative}")
        return attempt

    @staticmethod
    def _attempt_from_dict(data: Mapping[str, Any]) -> Attempt:
        validation_data = data["result"]["technical_validation"]
        result = NodeResult(
            execution_state=str(data["result"]["execution_state"]),
            technical_validation=TechnicalValidation(
                status=str(validation_data["status"]),
                classification=str(validation_data["classification"]),
                reasons=tuple(validation_data.get("reasons", ())),
                parser_summary=dict(validation_data.get("parser_summary", {})),
            ),
            scientific_decision=ScientificDecision(
                data["result"].get("scientific_decision", "NOT_EVALUATED")
            ),
        )
        return Attempt(
            node_id=str(data["node_id"]),
            attempt_id=str(data["attempt_id"]),
            scientific_identity_sha256=str(data["scientific_identity_sha256"]),
            execution_spec_sha256=str(data["execution_spec_sha256"]),
            started_at=str(data["started_at"]),
            finished_at=str(data["finished_at"]),
            stdout=str(data["stdout"]),
            stderr=str(data["stderr"]),
            exit_code=data.get("exit_code"),
            artifacts=dict(data.get("artifacts", {})),
            result=result,
        )

    def _block_descendants(self) -> None:
        for task in self.workflow.tasks:
            record = self._state["tasks"][task.task_id]
            if record["status"] != "PENDING":
                continue
            failed = [
                dependency
                for dependency in task.dependencies
                if self._state["tasks"][dependency]["status"] in _TERMINAL_FAILURES
            ]
            if failed:
                self._set_task(
                    task.task_id,
                    "BLOCKED",
                    "failed dependency: " + ", ".join(sorted(failed)),
                )

    def _is_ready(self, task: WorkflowTaskNode) -> bool:
        record = self._state["tasks"][task.task_id]
        if record["status"] not in {"PENDING", "INTERRUPTED", "INCOMPLETE"}:
            return False
        max_attempts = int(task.resources.get("max_attempts", 2))
        if int(record["attempts"]) >= max_attempts:
            self._set_task(task.task_id, "FAILED", "maximum attempts exhausted")
            return False
        return all(
            self._state["tasks"][dependency]["status"] == "COMPLETED"
            for dependency in task.dependencies
        )

    def _resolve_inputs(self, task: WorkflowTaskNode) -> dict[str, Path]:
        external = {
            artifact.artifact_id: artifact for artifact in self.workflow.external_artifacts
        }
        by_task = {item.task_id: item for item in self.workflow.tasks}
        resolved: dict[str, Path] = {}
        for binding in task.inputs:
            if binding.external_artifact_id is not None:
                artifact = external[binding.external_artifact_id]
                path = self.source_root / _safe_relative(
                    artifact.relative_path, field=f"{task.task_id}.{binding.name}"
                )
                if _sha_file(path) != artifact.sha256:
                    raise ValueError(f"external artifact hash mismatch: {artifact.relative_path}")
            else:
                parent_id = str(binding.source_task_id)
                parent = by_task[parent_id]
                output = next(
                    item for item in parent.outputs if item.name == binding.source_output_name
                )
                parent_record = self._state["tasks"][parent_id]
                parent_attempt = self._attempt_path(
                    parent_id, str(parent_record["last_attempt"])
                )
                path = parent_attempt / _safe_relative(
                    output.relative_path, field=f"{task.task_id}.{binding.name}"
                )
                parent_attempt_evidence = self._attempts.get(parent_id)
                if parent_attempt_evidence is None:
                    raise ValueError(f"parent completion unavailable: {parent_id}")
                expected = parent_attempt_evidence.artifacts.get(output.relative_path)
                if not path.is_file() or expected is None or _sha_file(path) != expected:
                    raise ValueError(f"parent artifact hash mismatch: {parent_id}.{output.name}")
            resolved[binding.name] = path
        if not resolved:
            raise ValueError(f"workflow task has no executable input: {task.task_id}")
        return resolved

    def _resolve_executable_capability(self, task: WorkflowTaskNode):
        registered = self.registry.resolve(
            task.capability_id,
            required_inputs=(EXECUTION_REQUEST,),
            required_outputs=(EXECUTION_EVIDENCE,),
        )
        missing = [
            name
            for name in _EXECUTABLE_CAPABILITY_METHODS
            if not callable(getattr(registered.implementation, name, None))
        ]
        if missing:
            raise TypeError(
                f"runtime capability lacks executable contract methods: {missing}"
            )
        return registered

    @staticmethod
    def _select_primary_input(
        task: WorkflowTaskNode,
        capability: object,
        inputs: Mapping[str, Path],
    ) -> str:
        if len(inputs) == 1:
            return next(iter(inputs))
        selector = getattr(capability, "select_primary_input", None)
        if not callable(selector):
            raise TypeError(
                f"multi-input capability must explicitly select its primary input: "
                f"{task.capability_id}"
            )
        selected = str(
            selector(
                inputs=dict(inputs),
                bindings={item.name: item for item in task.inputs},
                settings=dict(task.settings),
            )
        )
        if selected not in inputs:
            raise ValueError(
                f"capability selected unknown primary input {selected!r} for {task.task_id}"
            )
        return selected

    @staticmethod
    def _mutable_input_names(
        task: WorkflowTaskNode,
        capability: object,
        inputs: Mapping[str, Path],
    ) -> frozenset[str]:
        declarer = getattr(capability, "mutable_input_names", None)
        if not callable(declarer):
            return frozenset()
        declared = tuple(
            map(
                str,
                declarer(
                    inputs=dict(inputs),
                    bindings={item.name: item for item in task.inputs},
                    settings=dict(task.settings),
                )
                or (),
            )
        )
        if len(set(declared)) != len(declared):
            raise ValueError("capability declared duplicate mutable inputs")
        unknown = sorted(set(declared) - set(inputs))
        if unknown:
            raise ValueError(f"capability declared unknown mutable inputs: {unknown}")
        if declared and not callable(
            getattr(capability, "validate_consumed_inputs", None)
        ):
            raise TypeError(
                "capability declaring mutable inputs must validate their consumption"
            )
        return frozenset(declared)

    def _execute_task(self, task: WorkflowTaskNode) -> None:
        hosts = self._assigned_hosts.get(task.task_id, ())
        record = self._state["tasks"][task.task_id]
        try:
            registered = self._resolve_executable_capability(task)
            inputs = self._resolve_inputs(task)
            primary_name = self._select_primary_input(
                task, registered.implementation, inputs
            )
            primary = inputs[primary_name]
            inspected = registered.implementation.inspect_input(primary)
            validation = registered.implementation.validate_input(
                inspected,
                settings=dict(task.settings),
                inputs=dict(inputs),
                bindings={item.name: item for item in task.inputs},
            )
            raw_status = getattr(getattr(validation, "status", None), "value", getattr(validation, "status", None))
            if raw_status is not None and str(raw_status).upper() in {"FAIL", "BLOCKED"}:
                raise ValueError(f"capability input validation {raw_status}")
            mutable_inputs = self._mutable_input_names(
                task, registered.implementation, inputs
            )
        except (KeyError, ContractCompatibilityError, OSError, TypeError, ValueError) as exc:
            self._set_task(task.task_id, "BLOCKED", str(exc))
            return

        number = int(record["attempts"]) + 1
        attempt_id = f"attempt-{number:04d}"
        attempt_root = self._attempt_path(task.task_id, attempt_id)
        started = _utc_now()
        self._set_task(
            task.task_id,
            "RUNNING",
            "attempt reserved",
            attempts=number,
            last_attempt=attempt_id,
            manifest_sha256=None,
        )
        try:
            attempt_root.mkdir(parents=True, exist_ok=False)
            input_evidence: dict[str, str] = {}
            input_sources: dict[str, str] = {}
            working_input_evidence: dict[str, str] = {}
            staged_inputs: dict[str, Path] = {}
            bindings = {item.name: item for item in task.inputs}
            for index, (name, source) in enumerate(sorted(inputs.items()), start=1):
                destination = attempt_root / _safe_relative(
                    bindings[name].destination,
                    field=f"{task.task_id}.{name}.destination",
                )
                evidence_relative = Path(
                    ".qraft",
                    "input-evidence",
                    f"{index:03d}-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]}",
                )
                evidence_path = attempt_root / evidence_relative
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, evidence_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(evidence_path, destination)
                staged_inputs[name] = destination
                digest = _sha_file(evidence_path)
                input_evidence[evidence_relative.as_posix()] = digest
                input_sources[name] = digest
                if name not in mutable_inputs:
                    working_input_evidence[
                        destination.relative_to(attempt_root).as_posix()
                    ] = digest
            staged_inspected = registered.implementation.inspect_input(
                staged_inputs[primary_name]
            )
            prepared = registered.implementation.prepare_task(
                staged_inspected,
                attempt_root,
                filesystem=self.filesystem,
                settings=dict(task.settings),
                inputs=dict(staged_inputs),
                bindings=bindings,
                task_id=task.task_id,
                attempt_id=attempt_id,
            )
            prepared_path = Path(getattr(prepared, "destination", prepared))
            execution_spec = self.execution_specs[task.task_id]
            command = tuple(
                map(
                    str,
                    registered.implementation.build_command(
                        prepared_path,
                        execution_spec=execution_spec,
                        settings=dict(task.settings),
                    ),
                )
            )
            if not command:
                raise ValueError("capability returned an empty command")
            outcome = self._launcher_for(task).launch(
                StepLaunchSpec(
                    task_id=task.task_id,
                    attempt_id=attempt_id,
                    workdir=attempt_root,
                    input_path=prepared_path,
                    stdout_path=attempt_root / "stdout.txt",
                    stderr_path=attempt_root / "stderr.txt",
                    mpi_processes=execution_spec.mpi_ranks,
                    cpus_per_process=execution_spec.cpus_per_rank,
                    executable=command[0],
                    executable_arguments=command[1:],
                    environment=execution_spec.environment,
                    hosts=hosts,
                    processes_per_node=execution_spec.ranks_per_node,
                )
            )
            attempt = self._finalize_attempt(
                task,
                registered.implementation,
                attempt_id,
                attempt_root,
                outcome,
                started,
                command,
                input_evidence,
                input_sources,
                working_input_evidence,
                mutable_inputs,
            )
        except Exception as exc:
            self._set_task(task.task_id, "INCOMPLETE", f"attempt error: {type(exc).__name__}: {exc}")
            return

        manifest_path = attempt_root / "attempt.json"
        manifest_sha = _sha_file(manifest_path)
        with self._state_lock:
            self._attempts[task.task_id] = attempt
            self._results[task.task_id] = attempt.result
        self._set_task(
            task.task_id,
            attempt.result.execution_state,
            "; ".join(attempt.result.technical_validation.reasons)
            or attempt.result.technical_validation.classification,
            manifest_sha256=manifest_sha,
        )

    def _finalize_attempt(
        self,
        task: WorkflowTaskNode,
        capability: object,
        attempt_id: str,
        attempt_root: Path,
        outcome: StepOutcome,
        started: str,
        command: tuple[str, ...],
        input_evidence: Mapping[str, str],
        input_sources: Mapping[str, str],
        working_input_evidence: Mapping[str, str],
        mutable_inputs: frozenset[str],
    ) -> Attempt:
        stdout_path = attempt_root / "stdout.txt"
        stderr_path = attempt_root / "stderr.txt"
        stdout_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        parsed = capability.parse_output(
            stdout.splitlines(keepends=True),
            stderr=stderr,
            outcome=outcome,
            settings=dict(task.settings),
        )
        classified = capability.classify_result(
            parsed,
            outcome=outcome,
            settings=dict(task.settings),
        )
        if mutable_inputs:
            classified = capability.validate_consumed_inputs(
                parsed,
                classified=classified,
                mutable_inputs=tuple(sorted(mutable_inputs)),
                bindings={item.name: item for item in task.inputs},
                settings=dict(task.settings),
            )
        technical = normalize_technical_validation(classified)
        if outcome.terminated_by_controller:
            technical = TechnicalValidation(
                "BLOCKED", "INTERRUPTED", ("launcher interrupted attempt",), {}
            )
            execution_state = "INTERRUPTED"
        elif outcome.exit_code != 0:
            technical = TechnicalValidation(
                "FAIL",
                "PROCESS_EXIT_NONZERO",
                (f"process exit code {outcome.exit_code}",),
                technical.parser_summary,
            )
            execution_state = "FAILED"
        else:
            execution_state = {
                "PASS": "COMPLETED",
                "FAIL": "FAILED",
                "BLOCKED": "BLOCKED",
                "REVIEW": "INCOMPLETE",
            }[technical.status]

        discovered = capability.discover_artifacts(
            attempt_root,
            task_id=task.task_id,
            attempt_id=attempt_id,
            settings=dict(task.settings),
        )
        discovered_hashes: dict[str, str] = {}
        for item in discovered or ():
            reported = Path(str(getattr(item, "path", "")))
            digest = str(getattr(item, "sha256", ""))
            if not str(reported):
                continue
            if reported.is_absolute():
                try:
                    relative_path = reported.resolve().relative_to(attempt_root.resolve())
                except ValueError as exc:
                    raise ValueError(
                        f"capability artifact escapes attempt: {reported}"
                    ) from exc
            else:
                relative_path = _safe_relative(
                    reported.as_posix(), field="discovered artifact"
                )
            relative = relative_path.as_posix()
            path = attempt_root / relative_path
            if not path.is_file() or _sha_file(path) != digest:
                raise ValueError(f"capability artifact evidence mismatch: {relative}")
            discovered_hashes[relative] = digest
        artifact_hashes: dict[str, str] = {}
        missing: list[str] = []
        for output in task.outputs:
            path = attempt_root / _safe_relative(output.relative_path, field="workflow output")
            if path.is_file():
                artifact_hashes[output.relative_path] = _sha_file(path)
                if output.relative_path in discovered_hashes and discovered_hashes[output.relative_path] != artifact_hashes[output.relative_path]:
                    raise ValueError(f"capability/workflow artifact hash mismatch: {output.relative_path}")
            elif output.required:
                missing.append(output.relative_path)
        if missing and execution_state != "INTERRUPTED":
            technical = TechnicalValidation(
                "FAIL",
                "REQUIRED_ARTIFACT_MISSING",
                tuple(f"required artifact missing: {path}" for path in missing),
                technical.parser_summary,
            )
            execution_state = "FAILED"

        attempt = Attempt(
            node_id=task.task_id,
            attempt_id=attempt_id,
            scientific_identity_sha256=self.scientific_identities[task.task_id].fingerprint,
            execution_spec_sha256=self.execution_specs[task.task_id].fingerprint,
            started_at=started,
            finished_at=_utc_now(),
            stdout="stdout.txt",
            stderr="stderr.txt",
            exit_code=outcome.exit_code,
            artifacts=artifact_hashes,
            result=NodeResult(execution_state, technical),
        )
        payload = {
            "runtime_fingerprint": self.runtime_fingerprint,
            "capability_id": task.capability_id,
            "command": list(command),
            "input_evidence": dict(input_evidence),
            "input_sources": dict(input_sources),
            "working_input_evidence": dict(working_input_evidence),
            "mutable_inputs": sorted(mutable_inputs),
            "evidence_files": {
                "stdout.txt": _sha_file(stdout_path),
                "stderr.txt": _sha_file(stderr_path),
            },
            "attempt": attempt.to_dict(),
        }
        wrapper = {
            "schema_version": self.MANIFEST_SCHEMA,
            "payload": payload,
            "sha256": hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest(),
        }
        self.filesystem.atomic_write_json(attempt_root / "attempt.json", wrapper)
        return attempt

    def _attempt_path(self, task_id: str, attempt_id: str) -> Path:
        return self.root / "work" / task_id / attempt_id
