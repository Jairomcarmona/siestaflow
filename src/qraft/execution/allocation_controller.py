"""Persistent controller that schedules scientific srun steps in one allocation."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .. import __version__ as QRAFT_VERSION
from ..engines.siesta.output_parser import SiestaOutputParser
from ..project_packages import load_structured
from ..output import (
    DagEntry, ExecutionSession, NodeEntry, OutputMessage, OutputModel,
    QraftOutputWriter,
)
from .direct_launcher import DirectLauncher
from .adapters import launcher_registry
from .slurm_environment import ShutdownRequest, SignalHandlers, SlurmEnvironment
from .srun_launcher import StepLaunchSpec, StepLauncher, StepOutcome


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ArtifactTransfer:
    """Hash-bound artifact handoff from a completed parent task."""

    from_task: str
    artifact: str
    destination: str


@dataclass(frozen=True)
class ControllerTask:
    task_id: str
    input_path: str
    input_hashes: Mapping[str, str]
    required_artifacts: tuple[str, ...]
    mpi_processes: int
    cpus_per_process: int
    estimated_runtime_seconds: float
    max_attempts: int
    require_scf_converged: bool
    depends_on: tuple[str, ...] = ()
    transfers: tuple[ArtifactTransfer, ...] = ()
    nodes: int = 0
    task_kind: str = "siesta"
    command: tuple[str, ...] = ()
    input_destinations: Mapping[str, str] = field(default_factory=dict)
    optional_artifacts: tuple[str, ...] = ()

    @property
    def cpus(self) -> int:
        return self.mpi_processes * self.cpus_per_process


@dataclass(frozen=True)
class ControllerConfig:
    campaign_id: str
    system_id: str
    nodes: int
    total_cpus: int
    max_parallel_steps: int
    shutdown_margin_seconds: float
    termination_grace_seconds: float
    siesta_executable: str
    executable_arguments: tuple[str, ...]
    srun_command: tuple[str, ...]
    srun_arguments: tuple[str, ...]
    exclusive: bool
    environment: Mapping[str, str]
    tasks: tuple[ControllerTask, ...]
    launcher_kind: str = "srun"
    launcher_bootstrap: str = "ssh"
    processes_per_node: int | None = None


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _safe_relative(value: str, field: str) -> Path:
    posix = PurePosixPath(str(value).replace("\\", "/"))
    if not value or posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise ValueError(f"unsafe relative path in {field}: {value}")
    return Path(*posix.parts)


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or text.upper().startswith(("REQUIRED", "MISSING", "CONFIGURE")):
        raise ValueError(f"explicit configuration required: {field}")
    return text


def _nonempty_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"non-empty text required: {field}")
    return text


def _positive_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"positive integer required: {field}") from exc
    if result <= 0:
        raise ValueError(f"positive integer required: {field}")
    return result


def _nonnegative_float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"nonnegative number required: {field}") from exc
    if result < 0:
        raise ValueError(f"nonnegative number required: {field}")
    return result


def load_controller_config(path: Path) -> ControllerConfig:
    data = load_structured(path)
    schema_version = str(data.get("schema_version"))
    if schema_version not in {"1.0", "2.0"}:
        raise ValueError("unsupported campaign worker schema")
    campaign_id = _required_text(data.get("campaign_id"), "campaign_id")
    system_id = _required_text(data.get("system_id"), "system_id")
    slurm = data.get("slurm")
    resources = data.get("resources")
    runtime = data.get("runtime")
    if not isinstance(slurm, Mapping) or not isinstance(resources, Mapping) or not isinstance(runtime, Mapping):
        raise ValueError("slurm, resources and runtime mappings are required")
    # These fields are checked here even though sbatch consumes some of them.
    for field in ("partition", "account", "qos", "memory", "walltime"):
        source = slurm if field in {"partition", "account", "qos"} else resources
        _required_text(source.get(field), field)
    nodes = _positive_int(resources.get("nodes"), "resources.nodes")
    total_cpus = _positive_int(resources.get("total_cpus"), "resources.total_cpus")
    max_parallel = _positive_int(resources.get("max_parallel_steps"), "resources.max_parallel_steps")
    margin = _nonnegative_float(resources.get("shutdown_margin_seconds"), "resources.shutdown_margin_seconds")
    grace = _nonnegative_float(resources.get("termination_grace_seconds"), "resources.termination_grace_seconds")
    siesta = _required_text(runtime.get("siesta_executable"), "runtime.siesta_executable")
    launcher_raw = runtime.get("launcher", {})
    if schema_version == "2.0":
        if not isinstance(launcher_raw, Mapping):
            raise ValueError("runtime.launcher must be a mapping for schema 2.0")
        launcher_kind = str(launcher_raw.get("kind", "")).strip().casefold()
        launcher_adapter = launcher_registry.require(launcher_kind)
        if not launcher_adapter.supports_controller_siesta:
            raise ValueError(
                f"launcher adapter does not support controller SIESTA tasks: {launcher_kind}"
            )
        command_raw = launcher_raw.get("command")
        arguments_raw = launcher_raw.get("arguments", [])
        launcher_bootstrap = _required_text(
            launcher_raw.get("bootstrap", "ssh"), "runtime.launcher.bootstrap"
        )
        ppn_raw = launcher_raw.get("processes_per_node")
        processes_per_node = (
            _positive_int(ppn_raw, "runtime.launcher.processes_per_node")
            if ppn_raw is not None else None
        )
    else:
        launcher_kind = "srun"
        launcher_adapter = launcher_registry.require(launcher_kind)
        command_raw = runtime.get("srun_command")
        arguments_raw = runtime.get("srun_arguments", [])
        launcher_bootstrap = "ssh"
        processes_per_node = None
    if not isinstance(command_raw, list) or not command_raw:
        raise ValueError("runtime launcher command must be a non-empty argument list")
    srun_command = tuple(_required_text(item, "runtime.launcher.command") for item in command_raw)
    srun_args_raw = arguments_raw
    executable_args_raw = runtime.get("executable_arguments", [])
    environment_raw = runtime.get("environment", {})
    if not isinstance(srun_args_raw, list) or not isinstance(executable_args_raw, list) or not isinstance(environment_raw, Mapping):
        raise ValueError("runtime arguments/environment have invalid types")
    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ValueError("at least one task is required")
    tasks: list[ControllerTask] = []
    seen: set[str] = set()
    for raw in tasks_raw:
        if not isinstance(raw, Mapping):
            raise ValueError("each task must be a mapping")
        task_id = _required_text(raw.get("task_id"), "task.task_id")
        if task_id in seen or "/" in task_id or "\\" in task_id or task_id in {".", ".."}:
            raise ValueError(f"invalid or duplicate task id: {task_id}")
        seen.add(task_id)
        input_path = _safe_relative(_required_text(raw.get("input"), f"{task_id}.input"), f"{task_id}.input").as_posix()
        hashes = raw.get("input_hashes")
        if not isinstance(hashes, Mapping) or not hashes:
            raise ValueError(f"input_hashes required for {task_id}")
        normalized_hashes: dict[str, str] = {}
        for name, digest in hashes.items():
            relative = _safe_relative(str(name), f"{task_id}.input_hashes").as_posix()
            expected = str(digest).lower()
            if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
                raise ValueError(f"invalid SHA-256 for {relative}")
            normalized_hashes[relative] = expected
        if input_path not in normalized_hashes:
            raise ValueError(f"primary input is not hash-bound: {input_path}")
        destinations_raw = raw.get("input_destinations")
        if destinations_raw is None:
            input_destinations = {
                relative: PurePosixPath(relative).name
                for relative in normalized_hashes
            }
        else:
            if not isinstance(destinations_raw, Mapping):
                raise ValueError(
                    f"input_destinations must be a mapping for {task_id}"
                )
            if set(map(str, destinations_raw)) != set(normalized_hashes):
                raise ValueError(
                    f"input_destinations keys must match input_hashes for {task_id}"
                )
            input_destinations = {
                str(relative): _safe_relative(
                    str(destination),
                    f"{task_id}.input_destinations",
                ).as_posix()
                for relative, destination in destinations_raw.items()
            }
        staged_destinations = tuple(input_destinations.values())
        if len(set(staged_destinations)) != len(staged_destinations):
            raise ValueError(f"staged input destination collision: {task_id}")
        required_raw = raw.get("required_artifacts", [])
        if not isinstance(required_raw, list):
            raise ValueError(f"required_artifacts must be a list for {task_id}")
        required = tuple(_safe_relative(str(item), f"{task_id}.required_artifacts").as_posix() for item in required_raw)
        optional_raw = raw.get("optional_artifacts", [])
        if not isinstance(optional_raw, list):
            raise ValueError(f"optional_artifacts must be a list for {task_id}")
        optional = tuple(
            _safe_relative(
                str(item), f"{task_id}.optional_artifacts"
            ).as_posix()
            for item in optional_raw
        )
        if (
            len(set(required)) != len(required)
            or len(set(optional)) != len(optional)
            or set(required) & set(optional)
        ):
            raise ValueError(
                f"required and optional artifacts must be unique for {task_id}"
            )
        mpi = _positive_int(raw.get("mpi_processes"), f"{task_id}.mpi_processes")
        cpp = _positive_int(raw.get("cpus_per_process", 1), f"{task_id}.cpus_per_process")
        estimate = _nonnegative_float(raw.get("estimated_runtime_seconds"), f"{task_id}.estimated_runtime_seconds")
        if estimate == 0:
            raise ValueError(f"positive runtime estimate required for {task_id}")
        attempts = _positive_int(raw.get("max_attempts"), f"{task_id}.max_attempts")
        dependencies_raw = raw.get("depends_on", [])
        transfers_raw = raw.get("transfers", [])
        if not isinstance(dependencies_raw, list) or not isinstance(transfers_raw, list):
            raise ValueError(f"depends_on and transfers must be lists for {task_id}")
        dependencies = tuple(map(str, dependencies_raw))
        if len(set(dependencies)) != len(dependencies) or task_id in dependencies:
            raise ValueError(f"invalid dependencies for {task_id}")
        transfers: list[ArtifactTransfer] = []
        destinations: set[str] = set()
        for transfer_raw in transfers_raw:
            if not isinstance(transfer_raw, Mapping):
                raise ValueError(f"invalid transfer for {task_id}")
            source_task = _required_text(
                transfer_raw.get("from_task"), f"{task_id}.transfer.from_task"
            )
            artifact = _safe_relative(
                _nonempty_text(transfer_raw.get("artifact"), f"{task_id}.transfer.artifact"),
                f"{task_id}.transfer.artifact",
            ).as_posix()
            destination = _safe_relative(
                _nonempty_text(
                    transfer_raw.get("destination"), f"{task_id}.transfer.destination"
                ),
                f"{task_id}.transfer.destination",
            ).as_posix()
            if destination in destinations or destination in staged_destinations:
                raise ValueError(f"staged transfer destination collision: {destination}")
            destinations.add(destination)
            transfers.append(ArtifactTransfer(source_task, artifact, destination))
        task_nodes_raw = raw.get("nodes", 0)
        try:
            task_nodes = int(task_nodes_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"nonnegative integer required: {task_id}.nodes") from exc
        if task_nodes < 0:
            raise ValueError(f"nonnegative integer required: {task_id}.nodes")
        task_kind = str(raw.get("kind", "siesta")).strip().casefold()
        if task_kind not in {"siesta", "gate"}:
            raise ValueError(f"task kind must be siesta or gate: {task_id}")
        command_raw_task = raw.get("command", [])
        if task_kind == "gate":
            if not isinstance(command_raw_task, list) or not command_raw_task:
                raise ValueError(f"gate task requires a non-empty command: {task_id}")
            task_command = tuple(
                _nonempty_text(item, f"{task_id}.command") for item in command_raw_task
            )
            if mpi != 1 or cpp != 1 or task_nodes != 0:
                raise ValueError(
                    f"gate task must use mpi_processes=1, cpus_per_process=1, nodes=0: "
                    f"{task_id}"
                )
        else:
            if command_raw_task not in (None, []):
                raise ValueError(f"siesta task cannot override command: {task_id}")
            task_command = ()
        tasks.append(ControllerTask(
            task_id, input_path, normalized_hashes, required, mpi, cpp, estimate,
            attempts, bool(raw.get("require_scf_converged", True)),
            dependencies, tuple(transfers), task_nodes, task_kind, task_command,
            input_destinations, optional,
        ))
    if max_parallel > len(tasks):
        max_parallel = len(tasks)
    for task in tasks:
        if task.cpus > total_cpus:
            raise ValueError(f"task {task.task_id} requests more CPUs than campaign allocation")
        if task.nodes > nodes:
            raise ValueError(f"task {task.task_id} requests more nodes than campaign allocation")
        if launcher_adapter.requires_processes_per_node and task.task_kind == "siesta":
            if task.nodes <= 0:
                raise ValueError(
                    f"{launcher_kind} task {task.task_id} requires an explicit positive nodes value"
                )
            if processes_per_node is None:
                raise ValueError(f"{launcher_kind} launcher requires processes_per_node")
            if task.mpi_processes != task.nodes * processes_per_node:
                raise ValueError(
                    f"{launcher_kind} placement mismatch for {task.task_id}: "
                    f"{task.mpi_processes} != {task.nodes}*{processes_per_node}"
                )
    by_id = {task.task_id: task for task in tasks}
    for task in tasks:
        for dependency in task.depends_on:
            if dependency not in by_id:
                raise ValueError(f"unknown dependency for {task.task_id}: {dependency}")
        for transfer in task.transfers:
            if transfer.from_task not in task.depends_on:
                raise ValueError(
                    f"transfer source must be a direct dependency for {task.task_id}: "
                    f"{transfer.from_task}"
                )
            parent = by_id.get(transfer.from_task)
            if parent is None or transfer.artifact not in parent.required_artifacts:
                raise ValueError(
                    f"transfer artifact is not required output of {transfer.from_task}: "
                    f"{transfer.artifact}"
                )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"campaign dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].depends_on:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task in tasks:
        visit(task.task_id)
    return ControllerConfig(
        campaign_id, system_id, nodes, total_cpus, max_parallel, margin, grace,
        siesta, tuple(map(str, executable_args_raw)), srun_command,
        tuple(map(str, srun_args_raw)), bool(runtime.get("exclusive", True)),
        {str(key): str(value) for key, value in environment_raw.items()}, tuple(tasks),
        launcher_kind, launcher_bootstrap, processes_per_node,
    )


class AllocationController:
    """Schedule independent tasks, persist evidence and survive new allocations."""

    STATE_SCHEMA = "1.0"
    CORE_ARTIFACTS = ("stdout.txt", "stderr.txt", "exit_code.json", "timing.json", "command.json")

    def __init__(
        self,
        *,
        root: Path,
        config: ControllerConfig,
        slurm: SlurmEnvironment,
        launcher: StepLauncher | None = None,
        shutdown: ShutdownRequest | None = None,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.slurm = slurm
        self.launcher_adapter = launcher_registry.require(config.launcher_kind)
        if launcher is not None:
            self.launcher = launcher
        else:
            self.launcher = self.launcher_adapter.create(
                command=config.srun_command,
                arguments=config.srun_arguments,
                bootstrap=config.launcher_bootstrap,
            )
        self.shutdown = shutdown or ShutdownRequest()
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.state_path = self.root / "state" / "campaign_state.json"
        self.events_path = self.root / "evidence" / "events.jsonl"
        self.summary_path = self.root / "results" / "campaign_summary.json"
        self.output_writer = QraftOutputWriter(
            self.root / "qraft.out", campaign_root=self.root
        )
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self._allocated_hosts: tuple[str, ...] = ()
        self._direct_launcher = DirectLauncher()

    @classmethod
    def from_file(
        cls,
        campaign_path: Path,
        *,
        root: Path | None = None,
        environment: Mapping[str, str] | None = None,
        launcher: StepLauncher | None = None,
        shutdown: ShutdownRequest | None = None,
        poll_interval_seconds: float = 0.1,
    ) -> "AllocationController":
        campaign_path = campaign_path.resolve()
        selected_root = (root or campaign_path.parent).resolve()
        slurm = SlurmEnvironment.from_mapping(environment)
        if slurm.submit_dir != selected_root:
            raise ValueError(f"campaign root must equal SLURM_SUBMIT_DIR: {selected_root} != {slurm.submit_dir}")
        return cls(
            root=selected_root, config=load_controller_config(campaign_path), slurm=slurm,
            launcher=launcher, shutdown=shutdown, poll_interval_seconds=poll_interval_seconds,
        )

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": self.STATE_SCHEMA,
            "campaign_id": self.config.campaign_id,
            "system_id": self.config.system_id,
            "status": ExecutionStatus.PENDING.value,
            "current_job_id": self.slurm.job_id,
            "allocation_history": [{"job_id": self.slurm.job_id, "started_at_epoch": time.time()}],
            "tasks": {
                task.task_id: {
                    "status": ExecutionStatus.PENDING.value, "attempts": 0,
                    "last_attempt": None, "result_manifest_sha256": None,
                    "reason": "not started", "depends_on": list(task.depends_on),
                }
                for task in self.config.tasks
            },
            "revision": 0,
            "updated_at_epoch": time.time(),
        }

    def _atomic_json(self, path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        encoded = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _save_state(self) -> None:
        with self._state_lock:
            self._state["revision"] = int(self._state.get("revision", 0)) + 1
            self._state["updated_at_epoch"] = time.time()
            payload = json.loads(json.dumps(self._state))
        wrapper = {
            "schema_version": self.STATE_SCHEMA,
            "payload": payload,
            "sha256": hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest(),
        }
        self._atomic_json(self.state_path, wrapper)

    def _load_state(self) -> dict[str, Any]:
        wrapper = json.loads(self.state_path.read_text(encoding="utf-8"))
        if wrapper.get("schema_version") != self.STATE_SCHEMA or not isinstance(wrapper.get("payload"), dict):
            raise ValueError("invalid campaign state schema")
        payload = wrapper["payload"]
        if hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest() != wrapper.get("sha256"):
            raise ValueError("campaign state checksum mismatch")
        if payload.get("campaign_id") != self.config.campaign_id or payload.get("system_id") != self.config.system_id:
            raise ValueError("campaign state identity mismatch")
        configured = {task.task_id for task in self.config.tasks}
        if set(payload.get("tasks", {})) != configured:
            raise ValueError("campaign state task set mismatch")
        return payload

    def _event(self, event: str, **fields: Any) -> None:
        record = {"event": event, "job_id": self.slurm.job_id, "at_epoch": time.time(), **fields}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _render_output(self, operation: str, callback: Any) -> None:
        try:
            callback()
        except Exception as exc:  # Derived human output cannot invalidate evidence.
            self._event(
                "OUTPUT_CORE_FAILURE",
                operation=operation,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _start_output_model(self) -> OutputModel:
        statuses = self._state.get("tasks", {}) if self._state else {}
        return OutputModel(
            header={
                "Version": QRAFT_VERSION,
                "Started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "Campaign": self.config.system_id,
                "Campaign ID": self.config.campaign_id,
                "Campaign root": str(self.root),
                "Host": socket.gethostname(),
                "SLURM Job": self.slurm.job_id,
                "Partition": os.environ.get("SLURM_JOB_PARTITION"),
                "Nodes": self.config.nodes,
                "MPI ranks": self.slurm.ntasks,
                "Launcher": self.config.launcher_kind,
                "Engine": "SIESTA",
                "Engine version": "runtime-resolved",
            },
            configuration={
                "engine": "siesta",
                "protocol": "allocation_controller",
                "working root": str(self.root),
                "nodes": self.config.nodes,
                "mpi ranks": self.slurm.ntasks,
                "launcher": self.config.launcher_kind,
                "executable": self.config.siesta_executable,
                "max parallel steps": self.config.max_parallel_steps,
            },
            execution={
                "Scheduler": "slurm",
                "Launcher": self.config.launcher_kind,
                "Executable": self.config.siesta_executable,
                "Command": shlex.join((
                    *self.config.srun_command,
                    *self.config.srun_arguments,
                    self.config.siesta_executable,
                    *self.config.executable_arguments,
                )),
                "Partition": os.environ.get("SLURM_JOB_PARTITION"),
                "Nodes": self.config.nodes,
                "MPI ranks": self.slurm.ntasks,
                "Ranks/node": self.slurm.ntasks // self.config.nodes,
            },
            identity={
                "Scientific ID": self.config.campaign_id[:16],
                "Execution ID": self.slurm.job_id,
                "QRAFT version": QRAFT_VERSION,
                "QRAFT commit": os.environ.get("QRAFT_COMMIT"),
                "Engine": "SIESTA",
                "Engine version": "runtime-resolved",
            },
            dag=tuple(
                DagEntry(
                    task.task_id,
                    task.task_kind,
                    str(statuses.get(task.task_id, {}).get("status", "PENDING")),
                    task.depends_on,
                )
                for task in self.config.tasks
            ),
            paths={
                "QRAFT output": str(self.output_writer.path),
                "State": str(self.state_path),
                "Evidence": str(self.events_path),
            },
        )

    def _task_output_model(
        self, task_id: str, status: ExecutionStatus, reason: str
    ) -> OutputModel:
        task = next(item for item in self.config.tasks if item.task_id == task_id)
        current = self._task_state(task_id)
        attempt_id = current.get("last_attempt")
        attempt = self._attempt_path(task_id, str(attempt_id)) if attempt_id else None
        messages: tuple[OutputMessage, ...] = ()
        if status in {
            ExecutionStatus.FAILED,
            ExecutionStatus.BLOCKED,
            ExecutionStatus.INCOMPLETE,
            ExecutionStatus.INTERRUPTED,
            ExecutionStatus.CANCELLED,
        }:
            severity = (
                "ERROR" if status is ExecutionStatus.FAILED
                else "BLOCKED" if status is ExecutionStatus.BLOCKED
                else "REVIEW_REQUIRED"
            )
            messages = (OutputMessage(
                severity,
                reason,
                code=status.value,
                node_id=task_id,
                attempt_id=str(attempt_id) if attempt_id else None,
                paths={
                    "workdir": str(attempt) if attempt else str(self.root / "work" / task_id),
                    "stdout": str(attempt / "stdout.txt") if attempt else "not-created",
                    "stderr": str(attempt / "stderr.txt") if attempt else "not-created",
                    "evidence": str(attempt / "result_manifest.json") if attempt else "not-created",
                },
                details={
                    "Technical state": status.value,
                    "DAG action": (
                        "DEPENDENTS WILL BE BLOCKED"
                        if status is ExecutionStatus.FAILED
                        else "NODE WILL NOT RUN"
                        if status in {ExecutionStatus.BLOCKED, ExecutionStatus.CANCELLED}
                        else "ELIGIBLE FOR RECOVERY"
                    ),
                },
            ),)
        return OutputModel(
            nodes=(NodeEntry(
                node_id=task_id,
                node_type=task.task_kind,
                status=status.value,
                attempt_id=str(attempt_id) if attempt_id else None,
                workdir=str(attempt) if attempt else str(self.root / "work" / task_id),
                input_path=str(
                    attempt / task.input_destinations[task.input_path]
                    if attempt else self.root / task.input_path
                ),
                stdout_path=str(attempt / "stdout.txt") if attempt else None,
                stderr_path=str(attempt / "stderr.txt") if attempt else None,
                evidence_path=str(attempt / "result_manifest.json") if attempt else None,
                resources={
                    "Nodes": task.nodes,
                    "MPI ranks": task.mpi_processes,
                    "CPUs/rank": task.cpus_per_process,
                    "Reason": reason,
                },
                depends_on=task.depends_on,
                event=("START" if status is ExecutionStatus.RUNNING else "RESULT"),
                started=(
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    if status is ExecutionStatus.RUNNING else None
                ),
                finished=(
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    if status is not ExecutionStatus.RUNNING else None
                ),
                command=shlex.join((
                    *self.config.srun_command,
                    *self.config.srun_arguments,
                    *(task.command or (
                        self.config.siesta_executable,
                        *self.config.executable_arguments,
                    )),
                )),
            ),),
            metrics={
                "Technical validation": (
                    "PASS" if status is ExecutionStatus.COMPLETED
                    else "FAIL" if status is ExecutionStatus.FAILED
                    else status.value
                )
            },
            messages=messages,
        )

    def _campaign_output_model(self) -> OutputModel:
        model = self._start_output_model()
        return OutputModel(
            header=model.header,
        )

    def _task_state(self, task_id: str) -> dict[str, Any]:
        return self._state["tasks"][task_id]

    def _set_task(self, task_id: str, status: ExecutionStatus, reason: str, **fields: Any) -> None:
        current = self._task_state(task_id)
        previous = current["status"]
        current.update({"status": status.value, "reason": reason, **fields})
        self._event("TASK_STATE", task_id=task_id, previous=previous, status=status.value, reason=reason)
        self._save_state()
        self._render_output(
            "task_state",
            lambda: self.output_writer.append(
                "NODE STATE", self._task_output_model(task_id, status, reason)
            ),
        )

    def _attempt_path(self, task_id: str, attempt_id: str) -> Path:
        return self.root / "work" / task_id / attempt_id

    def _verify_source_inputs(self, task: ControllerTask) -> None:
        for relative, expected in task.input_hashes.items():
            path = self.root / _safe_relative(relative, "input_hashes")
            if not path.is_file():
                raise ValueError(f"missing protected input: {relative}")
            if _sha_file(path) != expected:
                raise ValueError(f"protected input hash mismatch: {relative}")

    def _transfer_inputs(self, task: ControllerTask, attempt: Path) -> tuple[dict[str, Any], ...]:
        transferred: list[dict[str, Any]] = []
        for index, transfer in enumerate(task.transfers, 1):
            source_state = self._task_state(transfer.from_task)
            source_attempt_id = source_state.get("last_attempt")
            source_manifest_hash = source_state.get("result_manifest_sha256")
            if (
                source_state.get("status") != ExecutionStatus.COMPLETED.value
                or not source_attempt_id
                or not source_manifest_hash
            ):
                raise ValueError(
                    f"transfer source is not completed and verified: {transfer.from_task}"
                )
            source_attempt = self._attempt_path(transfer.from_task, str(source_attempt_id))
            source_manifest = source_attempt / "result_manifest.json"
            if not source_manifest.is_file() or _sha_file(source_manifest) != source_manifest_hash:
                raise ValueError(f"transfer source manifest mismatch: {transfer.from_task}")
            source = source_attempt / _safe_relative(
                transfer.artifact, f"{task.task_id}.transfer.artifact"
            )
            if not source.is_file():
                raise ValueError(
                    f"transfer source artifact missing: {transfer.from_task}:{transfer.artifact}"
                )
            source_data = json.loads(source_manifest.read_text(encoding="utf-8"))
            expected = source_data.get("artifacts", {}).get(transfer.artifact)
            actual = _sha_file(source)
            if expected != actual:
                raise ValueError(
                    f"transfer source artifact hash mismatch: "
                    f"{transfer.from_task}:{transfer.artifact}"
                )
            destination = attempt / _safe_relative(
                transfer.destination, f"{task.task_id}.transfer.destination"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            evidence_relative = (
                Path(".qraft")
                / "transfer_evidence"
                / f"{index:04d}"
                / PurePosixPath(transfer.destination).name
            )
            evidence = attempt / evidence_relative
            evidence.parent.mkdir(parents=True, exist_ok=False)
            shutil.copy2(source, evidence)
            shutil.copy2(evidence, destination)
            if _sha_file(evidence) != actual or _sha_file(destination) != actual:
                raise ValueError(
                    f"transferred destination staging mismatch: {transfer.destination}"
                )
            transferred.append({
                "from_task": transfer.from_task,
                "from_attempt": source_attempt_id,
                "source_result_manifest_sha256": source_manifest_hash,
                "artifact": transfer.artifact,
                "destination": transfer.destination,
                "sha256": actual,
                "evidence_path": evidence_relative.as_posix(),
                "evidence_sha256": actual,
                "destination_sha256_before_execution": actual,
                "destination_mutable_after_launch": True,
            })
        if transferred:
            self._atomic_json(
                attempt / "transfer_manifest.json",
                {"schema_version": "2.0", "transfers": transferred},
            )
        return tuple(transferred)

    def _verify_transfers_before_launch(
        self, task: ControllerTask, attempt: Path
    ) -> None:
        """Verify working copies at the last controller boundary before execution."""
        if not task.transfers:
            return
        manifest_path = attempt / "transfer_manifest.json"
        if not manifest_path.is_file():
            raise ValueError("transfer manifest missing before launch")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = payload.get("transfers")
        if not isinstance(records, list) or len(records) != len(task.transfers):
            raise ValueError("transfer manifest mismatch before launch")
        for transfer, record in zip(task.transfers, records, strict=True):
            if not isinstance(record, dict):
                raise ValueError("invalid transfer record before launch")
            expected = str(record.get("sha256", ""))
            destination = attempt / _safe_relative(
                transfer.destination, f"{task.task_id}.transfer.destination"
            )
            evidence = attempt / _safe_relative(
                str(record.get("evidence_path", "")),
                f"{task.task_id}.transfer.evidence_path",
            )
            if (
                not destination.is_file()
                or not evidence.is_file()
                or _sha_file(destination) != expected
                or _sha_file(evidence) != expected
            ):
                raise ValueError(
                    f"transferred input changed before launch: {transfer.destination}"
                )

    def _prepare_attempt(self, task: ControllerTask) -> tuple[str, Path, Path]:
        task_state = self._task_state(task.task_id)
        number = int(task_state["attempts"]) + 1
        attempt_id = f"attempt-{number:04d}"
        attempt = self._attempt_path(task.task_id, attempt_id)
        self._verify_source_inputs(task)
        attempt.mkdir(parents=True, exist_ok=False)
        for relative, destination_relative in task.input_destinations.items():
            source = self.root / _safe_relative(relative, "input_hashes")
            destination = attempt / _safe_relative(
                destination_relative, "input_destinations"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self._transfer_inputs(task, attempt)
        primary = attempt / _safe_relative(
            task.input_destinations[task.input_path],
            "primary input destination",
        )
        task_state.update({"attempts": number, "last_attempt": attempt_id})
        return attempt_id, attempt, primary

    def _execute(
        self,
        task: ControllerTask,
        attempt_id: str,
        attempt: Path,
        primary: Path,
        hosts: tuple[str, ...] = (),
    ) -> tuple[StepOutcome | None, str | None]:
        spec = StepLaunchSpec(
            task.task_id, attempt_id, attempt, primary, attempt / "stdout.txt", attempt / "stderr.txt",
            task.mpi_processes, task.cpus_per_process,
            task.command[0] if task.task_kind == "gate" else self.config.siesta_executable,
            (
                task.command[1:]
                if task.task_kind == "gate" else self.config.executable_arguments
            ),
            self.config.environment,
            hosts, self.config.processes_per_node,
        )
        try:
            self._verify_transfers_before_launch(task, attempt)
            selected_launcher = (
                self._direct_launcher if task.task_kind == "gate" else self.launcher
            )
            outcome = selected_launcher.launch(spec)
            return outcome, None
        except Exception as exc:  # Captured as task evidence; other tasks may continue.
            return None, f"{type(exc).__name__}: {exc}"

    def _write_attempt_evidence(self, task: ControllerTask, attempt: Path, outcome: StepOutcome) -> dict[str, Any]:
        self._atomic_json(attempt / "exit_code.json", {"exit_code": outcome.exit_code})
        self._atomic_json(attempt / "timing.json", {"elapsed_seconds": outcome.elapsed_seconds})
        self._atomic_json(attempt / "command.json", {"argv": list(outcome.command), "job_id": self.slurm.job_id})
        output = (attempt / "stdout.txt").read_text(encoding="utf-8", errors="replace")
        record = (
            SiestaOutputParser().parse(output.splitlines(keepends=True), synthetic=False)
            if task.task_kind == "siesta" else None
        )
        artifacts: dict[str, str] = {}
        artifacts_to_record = tuple(
            dict.fromkeys(
                (
                    *self.CORE_ARTIFACTS,
                    *task.required_artifacts,
                    *task.optional_artifacts,
                )
            )
        )
        for relative in artifacts_to_record:
            path = attempt / _safe_relative(relative, "required_artifacts")
            if path.is_file():
                artifacts[relative] = _sha_file(path)
        staged_inputs = {
            relative: _sha_file(
                attempt
                / _safe_relative(
                    task.input_destinations[relative],
                    "input_destinations",
                )
            )
            for relative in task.input_hashes
        }
        manifest = {
            "schema_version": "1.0", "campaign_id": self.config.campaign_id,
            "system_id": self.config.system_id, "task_id": task.task_id,
            "attempt_id": outcome.attempt_id, "job_id": self.slurm.job_id,
            "exit_code": outcome.exit_code, "terminated_by_controller": outcome.terminated_by_controller,
            "task_kind": task.task_kind,
            "normal_termination": (
                record.normal_termination if record is not None else outcome.exit_code == 0
            ),
            "scf_started": record.scf_started if record is not None else False,
            "scf_converged": record.scf_converged if record is not None else False,
            "parser_classification": (
                record.classification.value if record is not None else "GATE_EXIT_STATUS"
            ),
            "parser_warnings": list(record.warnings) if record is not None else [],
            "parser_benign_warnings": (
                list(record.benign_warnings) if record is not None else []
            ),
            "restart_evidence": {
                "dm_read_attempted": (
                    record.dm_restart_attempted if record is not None else False
                ),
                "dm_read_succeeded": (
                    record.dm_restart_succeeded if record is not None else False
                ),
            },
            "input_hashes": staged_inputs, "artifacts": artifacts,
            "transferred_inputs": (
                json.loads((attempt / "transfer_manifest.json").read_text(encoding="utf-8"))[
                    "transfers"
                ]
                if (attempt / "transfer_manifest.json").is_file() else []
            ),
        }
        self._atomic_json(attempt / "result_manifest.json", manifest)
        return manifest

    def _validate_attempt(self, task: ControllerTask, attempt_id: str, expected_manifest_hash: str | None = None) -> tuple[bool, str]:
        attempt = self._attempt_path(task.task_id, attempt_id)
        manifest_path = attempt / "result_manifest.json"
        if not manifest_path.is_file():
            return False, "result manifest missing"
        if expected_manifest_hash and _sha_file(manifest_path) != expected_manifest_hash:
            return False, "result manifest hash mismatch"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "result manifest invalid"
        if manifest.get("campaign_id") != self.config.campaign_id or manifest.get("task_id") != task.task_id or manifest.get("attempt_id") != attempt_id:
            return False, "result manifest identity mismatch"
        if manifest.get("exit_code") != 0:
            return False, "nonzero process exit code"
        if not manifest.get("normal_termination"):
            return False, "SIESTA normal termination missing"
        if (
            task.task_kind == "siesta"
            and task.require_scf_converged
            and not manifest.get("scf_converged")
        ):
            return False, "required SCF convergence missing"
        try:
            self._verify_source_inputs(task)
        except ValueError as exc:
            return False, str(exc)
        staged = manifest.get("input_hashes")
        if not isinstance(staged, dict) or staged != dict(task.input_hashes):
            return False, "staged input manifest mismatch"
        for relative, expected in task.input_hashes.items():
            path = attempt / _safe_relative(
                task.input_destinations[relative],
                "input_destinations",
            )
            if not path.is_file() or _sha_file(path) != expected:
                return False, f"staged input hash mismatch: {relative}"
        transferred = manifest.get("transferred_inputs")
        if not isinstance(transferred, list) or len(transferred) != len(task.transfers):
            return False, "transferred input manifest mismatch"
        output_record = None
        output_path = attempt / "stdout.txt"
        if task.task_kind == "siesta" and output_path.is_file():
            output_record = SiestaOutputParser().parse(
                output_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines(keepends=True),
                synthetic=False,
            )
        declared_transfers = {
            (item.from_task, item.artifact, item.destination) for item in task.transfers
        }
        observed_transfers: set[tuple[str, str, str]] = set()
        for item in transferred:
            if not isinstance(item, dict):
                return False, "invalid transferred input record"
            identity = (
                str(item.get("from_task")),
                str(item.get("artifact")),
                str(item.get("destination")),
            )
            observed_transfers.add(identity)
            destination = attempt / _safe_relative(
                identity[2], f"{task.task_id}.transferred_input"
            )
            digest = str(item.get("sha256", ""))
            if not destination.is_file():
                return False, f"transferred input missing after execution: {identity[2]}"
            evidence_path = item.get("evidence_path")
            if evidence_path:
                evidence = attempt / _safe_relative(
                    str(evidence_path), f"{task.task_id}.transfer.evidence_path"
                )
                if (
                    not evidence.is_file()
                    or str(item.get("evidence_sha256", "")) != digest
                    or _sha_file(evidence) != digest
                ):
                    return False, f"transferred input evidence mismatch: {identity[2]}"
            elif _sha_file(destination) != digest:
                # Schema 1.0 compared the working copy after SIESTA had
                # legitimately replaced a restart DM. Preserve compatibility
                # only when the real output proves that the DM was consumed.
                if not (
                    task.task_kind == "siesta"
                    and identity[2].casefold().endswith(".dm")
                    and output_record is not None
                    and output_record.dm_restart_succeeded
                ):
                    return False, f"legacy transferred input hash mismatch: {identity[2]}"
            source_attempt = self._attempt_path(
                identity[0], str(item.get("from_attempt", ""))
            )
            source_manifest = source_attempt / "result_manifest.json"
            expected_source_manifest = str(
                item.get("source_result_manifest_sha256", "")
            )
            source_artifact = source_attempt / _safe_relative(
                identity[1], f"{task.task_id}.source_artifact"
            )
            if (
                not source_manifest.is_file()
                or _sha_file(source_manifest) != expected_source_manifest
                or not source_artifact.is_file()
                or _sha_file(source_artifact) != digest
            ):
                return False, f"transferred source evidence mismatch: {identity[0]}"
            if (
                task.task_kind == "siesta"
                and identity[2].casefold().endswith(".dm")
                and (
                    output_record is None
                    or not output_record.dm_restart_succeeded
                )
            ):
                return False, f"DM restart consumption not confirmed: {identity[2]}"
        if observed_transfers != declared_transfers:
            return False, "transferred input declaration mismatch"
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            return False, "artifact manifest missing"
        required = tuple(dict.fromkeys((*self.CORE_ARTIFACTS, *task.required_artifacts)))
        for relative in required:
            path = attempt / _safe_relative(relative, "required_artifacts")
            if not path.is_file() or artifacts.get(relative) != _sha_file(path):
                return False, f"required artifact invalid: {relative}"
        for relative in task.optional_artifacts:
            path = attempt / _safe_relative(relative, "optional_artifacts")
            if path.is_file() and artifacts.get(relative) != _sha_file(path):
                return False, f"optional artifact invalid: {relative}"
        return True, "exit, termination, manifest, hashes and artifacts verified"

    def _recover(self) -> None:
        old_job = self._state.get("current_job_id")
        if old_job != self.slurm.job_id:
            self._state["current_job_id"] = self.slurm.job_id
            self._state.setdefault("allocation_history", []).append({"job_id": self.slurm.job_id, "started_at_epoch": time.time()})
            self._event("NEW_ALLOCATION", previous_job_id=old_job)
        by_id = {task.task_id: task for task in self.config.tasks}
        for task_id, item in self._state["tasks"].items():
            task = by_id[task_id]
            last = item.get("last_attempt")
            if item["status"] == ExecutionStatus.COMPLETED.value:
                valid = bool(last) and self._validate_attempt(task, last, item.get("result_manifest_sha256"))[0]
                if not valid:
                    self._set_task(task_id, ExecutionStatus.INCOMPLETE, "previous completed evidence no longer validates")
            elif item["status"] in {
                ExecutionStatus.RUNNING.value,
                ExecutionStatus.INCOMPLETE.value,
                ExecutionStatus.INTERRUPTED.value,
            }:
                valid, reason = (
                    self._validate_attempt(
                        task, last, item.get("result_manifest_sha256")
                    )
                    if last
                    else (False, "attempt missing")
                )
                if valid:
                    self._set_task(
                        task_id,
                        ExecutionStatus.COMPLETED,
                        reason,
                        result_manifest_sha256=_sha_file(
                            self._attempt_path(task_id, last)
                            / "result_manifest.json"
                        ),
                    )
                elif item["status"] == ExecutionStatus.RUNNING.value:
                    self._set_task(task_id, ExecutionStatus.INTERRUPTED, f"recovered in new allocation: {reason}")
        self._save_state()

    def _eligible(self, task: ControllerTask) -> bool:
        item = self._task_state(task.task_id)
        status = ExecutionStatus(item["status"])
        retryable = status in {
            ExecutionStatus.PENDING, ExecutionStatus.INTERRUPTED,
            ExecutionStatus.CANCELLED, ExecutionStatus.INCOMPLETE,
        } and int(item["attempts"]) < task.max_attempts
        dependencies_complete = all(
            self._task_state(dependency)["status"] == ExecutionStatus.COMPLETED.value
            for dependency in task.depends_on
        )
        return retryable and dependencies_complete

    def _mark_dependency_blocks(self) -> None:
        terminal_failure = {
            ExecutionStatus.FAILED.value,
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.BLOCKED.value,
        }
        changed = True
        while changed:
            changed = False
            for task in self.config.tasks:
                item = self._task_state(task.task_id)
                if item["status"] not in {
                    ExecutionStatus.PENDING.value,
                    ExecutionStatus.INCOMPLETE.value,
                }:
                    continue
                failed = [
                    dependency
                    for dependency in task.depends_on
                    if self._task_state(dependency)["status"] in terminal_failure
                ]
                if failed:
                    self._set_task(
                        task.task_id,
                        ExecutionStatus.BLOCKED,
                        "blocked by failed dependency: " + ",".join(failed),
                    )
                    changed = True

    def _finalize(self, task: ControllerTask, attempt_id: str, attempt: Path, outcome: StepOutcome | None, error: str | None) -> None:
        if outcome is None:
            self._set_task(task.task_id, ExecutionStatus.FAILED, f"launcher failure: {error}")
            return
        manifest = self._write_attempt_evidence(task, attempt, outcome)
        manifest_hash = _sha_file(attempt / "result_manifest.json")
        if outcome.terminated_by_controller:
            self._set_task(task.task_id, ExecutionStatus.INTERRUPTED, "step terminated during controlled shutdown", result_manifest_sha256=manifest_hash)
            return
        if outcome.exit_code != 0:
            self._set_task(task.task_id, ExecutionStatus.FAILED, f"step exit code {outcome.exit_code}", result_manifest_sha256=manifest_hash)
            return
        valid, reason = self._validate_attempt(task, attempt_id, manifest_hash)
        status = ExecutionStatus.COMPLETED if valid else ExecutionStatus.INCOMPLETE
        self._set_task(task.task_id, status, reason, result_manifest_sha256=manifest_hash)

    def _remaining_allocation_allows(self, task: ControllerTask) -> bool:
        required = task.estimated_runtime_seconds + self.config.shutdown_margin_seconds
        return self.slurm.remaining_seconds() > required

    def _write_summary(self) -> None:
        summary = {
            "campaign_id": self.config.campaign_id, "system_id": self.config.system_id,
            "job_id": self.slurm.job_id, "status": self._state["status"],
            "remaining_seconds": self.slurm.remaining_seconds(),
            "shutdown_reason": self.shutdown.reason,
            "tasks": self._state["tasks"],
            "completed_tasks": sum(
                item["status"] == ExecutionStatus.COMPLETED.value
                for item in self._state["tasks"].values()
            ),
            "total_tasks": len(self._state["tasks"]),
            "launcher_kind": self.config.launcher_kind,
            "login_node_persistent_process_required": False,
        }
        self._atomic_json(self.summary_path, summary)

    def run(self, *, install_signal_handlers: bool = True) -> ExecutionStatus:
        run_started = time.monotonic()
        session_id = uuid.uuid4().hex
        session_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        session_command = shlex.join(tuple(sys.argv)) if sys.argv else "qraft allocation controller"
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.slurm.validate_capacity(nodes=self.config.nodes, total_cpus=self.config.total_cpus)
            if self.launcher_adapter.requires_hosts:
                self._allocated_hosts = self.slurm.resolve_hostnames()
                if len(self._allocated_hosts) != self.config.nodes:
                    raise ValueError(
                        "configured campaign nodes must equal the resolved host allocation"
                    )
        except Exception as exc:
            self._event(
                "CONTROLLER_BLOCKED",
                session_id=session_id,
                reason=f"{type(exc).__name__}: {exc}",
            )
            if not self.output_writer.exists:
                self._render_output(
                    "initialize", lambda: self.output_writer.initialize(self._campaign_output_model())
                )
            self._render_output(
                "session_started",
                lambda: self.output_writer.start_session(
                    ExecutionSession(
                        session_id=session_id,
                        controller_epoch=1,
                        mode="NEW",
                        started=session_started,
                        command=session_command,
                        previous_state=None,
                        working_root=str(self.root),
                    ),
                    self._start_output_model(),
                ),
            )
            self._render_output(
                "controller_blocked",
                lambda: self.output_writer.append(
                    "CONTROLLER BLOCKED",
                    OutputModel(messages=(OutputMessage(
                        "BLOCKED",
                        f"{type(exc).__name__}: {exc}",
                        code="ALLOCATION_VALIDATION",
                        paths={"root": str(self.root), "evidence": str(self.events_path)},
                        details={
                            "Technical state": "NOT_STARTED",
                            "DAG action": "ALL NODES BLOCKED BEFORE LAUNCH",
                        },
                    ),)),
                ),
            )
            self._render_output(
                "session_finished",
                lambda: self.output_writer.finish_session(
                    result="BLOCKED",
                    finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    elapsed_seconds=time.monotonic() - run_started,
                ),
            )
            self._render_output(
                "summary",
                lambda: self.output_writer.finish({
                    "Campaign status": "BLOCKED",
                    "Nodes total": len(self.config.tasks),
                    "Validated": 0,
                    "Failed": 0,
                    "Blocked": len(self.config.tasks),
                    "Pending": 0,
                    "Elapsed time seconds": max(0.0, time.monotonic() - run_started),
                    "Root": str(self.root),
                    "QRAFT output": str(self.output_writer.path),
                    "Evidence": str(self.events_path),
                }),
            )
            raise
        resumed = self.state_path.is_file()
        if resumed:
            self._state = self._load_state()
        else:
            self._state = self._initial_state()
            self._save_state()
        if not self.output_writer.exists:
            self._render_output(
                "initialize", lambda: self.output_writer.initialize(self._campaign_output_model())
            )
        previous_state = self._state.get("status") if resumed else None
        epoch = len(self._state.get("allocation_history", []))
        if resumed and self._state.get("current_job_id") != self.slurm.job_id:
            epoch += 1
        epoch = max(1, epoch)
        self._event(
            "EXECUTION_SESSION_STARTED",
            session_id=session_id,
            controller_epoch=epoch,
            mode="RECOVERY" if resumed else "NEW",
            command=session_command,
        )
        self._render_output(
            "session_started",
            lambda: self.output_writer.start_session(
                ExecutionSession(
                    session_id=session_id,
                    controller_epoch=epoch,
                    mode="RECOVERY" if resumed else "NEW",
                    started=session_started,
                    command=session_command,
                    previous_state=str(previous_state) if previous_state else None,
                    working_root=str(self.root),
                ),
                self._start_output_model(),
            ),
        )
        if resumed:
            reused = [
                f"{task_id}:{item.get('last_attempt')}"
                for task_id, item in self._state["tasks"].items()
                if item.get("status") == ExecutionStatus.COMPLETED.value
                and item.get("last_attempt")
            ]
            self._render_output(
                "recovery",
                lambda: self.output_writer.append_recovery({
                    "Controller epoch": len(self._state.get("allocation_history", [])) + 1,
                    "Previous state": self._state.get("status"),
                    "Previous job": self._state.get("current_job_id"),
                    "Current job": self.slurm.job_id,
                    "Validated attempts reused": ", ".join(reused) if reused else "none",
                    "Action": "CAMPAIGN RESUMED",
                }),
            )
        self._recover()
        self._state["status"] = ExecutionStatus.RUNNING.value
        self._save_state()
        self._event("CONTROLLER_STARTED", max_parallel_steps=self.config.max_parallel_steps)
        handler = SignalHandlers(self.shutdown, lambda reason: self._event("SHUTDOWN_SIGNAL", reason=reason))
        context = handler if install_signal_handlers else _NullContext()
        active: dict[
            Future[tuple[StepOutcome | None, str | None]],
            tuple[ControllerTask, str, Path, tuple[str, ...]],
        ] = {}
        used_cpus = 0
        used_hosts: set[str] = set()
        attempted_this_allocation: set[str] = set()
        with context, ThreadPoolExecutor(max_workers=self.config.max_parallel_steps) as executor:
            while True:
                if not self.shutdown.requested and self.slurm.remaining_seconds() <= self.config.shutdown_margin_seconds:
                    self.shutdown.request("WALLTIME_MARGIN")
                    self._event("WALLTIME_LAUNCH_STOP", remaining_seconds=self.slurm.remaining_seconds())
                launched = False
                if not self.shutdown.requested:
                    for task in self.config.tasks:
                        if len(active) >= self.config.max_parallel_steps:
                            break
                        if task.task_id in attempted_this_allocation or not self._eligible(task) or task.cpus > self.config.total_cpus - used_cpus:
                            continue
                        task_hosts: tuple[str, ...] = ()
                        if (
                            self.launcher_adapter.requires_hosts
                            and task.task_kind == "siesta"
                        ):
                            available_hosts = tuple(
                                host for host in self._allocated_hosts if host not in used_hosts
                            )
                            if len(available_hosts) < task.nodes:
                                continue
                            task_hosts = available_hosts[:task.nodes]
                        if not self._remaining_allocation_allows(task):
                            self.shutdown.request("INSUFFICIENT_WALLTIME")
                            self._event("WALLTIME_LAUNCH_STOP", task_id=task.task_id, remaining_seconds=self.slurm.remaining_seconds())
                            break
                        try:
                            attempt_id, attempt, primary = self._prepare_attempt(task)
                        except Exception as exc:
                            attempted_this_allocation.add(task.task_id)
                            self._set_task(task.task_id, ExecutionStatus.INCOMPLETE, f"attempt preparation failed: {exc}")
                            continue
                        attempted_this_allocation.add(task.task_id)
                        self._set_task(
                            task.task_id,
                            ExecutionStatus.RUNNING,
                            f"{self.config.launcher_kind} step launched",
                            last_attempt=attempt_id,
                            hosts=list(task_hosts),
                        )
                        future = executor.submit(
                            self._execute, task, attempt_id, attempt, primary, task_hosts
                        )
                        active[future] = (task, attempt_id, attempt, task_hosts)
                        used_cpus += task.cpus
                        used_hosts.update(task_hosts)
                        launched = True
                if active:
                    if self.shutdown.requested:
                        immediate = self.shutdown.reason == "SIGTERM"
                        grace_expired = self.shutdown.elapsed_seconds >= self.config.termination_grace_seconds
                        if immediate or grace_expired or self.slurm.remaining_seconds() <= 1:
                            self.launcher.terminate_all()
                            self._direct_launcher.terminate_all()
                    done, _ = wait(tuple(active), timeout=self.poll_interval_seconds, return_when=FIRST_COMPLETED)
                    for future in done:
                        task, attempt_id, attempt, task_hosts = active.pop(future)
                        used_cpus -= task.cpus
                        used_hosts.difference_update(task_hosts)
                        outcome, error = future.result()
                        self._finalize(task, attempt_id, attempt, outcome, error)
                    continue
                if not launched:
                    break
        self._mark_dependency_blocks()
        if self.shutdown.requested:
            for task in self.config.tasks:
                if task.task_id not in attempted_this_allocation and self._eligible(task):
                    self._set_task(task.task_id, ExecutionStatus.INCOMPLETE, f"not launched: {self.shutdown.reason}")
        statuses = [ExecutionStatus(item["status"]) for item in self._state["tasks"].values()]
        if all(status is ExecutionStatus.COMPLETED for status in statuses):
            final = ExecutionStatus.COMPLETED
        elif self.shutdown.requested:
            final = ExecutionStatus.INTERRUPTED
        elif any(status is ExecutionStatus.FAILED for status in statuses):
            final = ExecutionStatus.FAILED
        elif any(status is ExecutionStatus.BLOCKED for status in statuses):
            final = ExecutionStatus.BLOCKED
        elif any(status is ExecutionStatus.CANCELLED for status in statuses):
            final = ExecutionStatus.CANCELLED
        else:
            final = ExecutionStatus.INCOMPLETE
        self._state["status"] = final.value
        self._save_state()
        self._event("CONTROLLER_FINISHED", status=final.value)
        self._write_summary()
        counts = {
            status.value: sum(item["status"] == status.value for item in self._state["tasks"].values())
            for status in ExecutionStatus
        }
        self._render_output(
            "session_finished",
            lambda: self.output_writer.finish_session(
                result=final.value,
                finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                elapsed_seconds=time.monotonic() - run_started,
            ),
        )
        self._event(
            "EXECUTION_SESSION_FINISHED",
            session_id=session_id,
            status=final.value,
        )
        self._render_output(
            "summary",
            lambda: self.output_writer.finish({
                "Campaign status": final.value,
                "Nodes total": len(statuses),
                "Validated": counts[ExecutionStatus.COMPLETED.value],
                "Failed": counts[ExecutionStatus.FAILED.value],
                "Blocked": counts[ExecutionStatus.BLOCKED.value],
                "Pending": counts[ExecutionStatus.PENDING.value],
                "Incomplete": counts[ExecutionStatus.INCOMPLETE.value],
                "Interrupted": counts[ExecutionStatus.INTERRUPTED.value],
                "Cancelled": counts[ExecutionStatus.CANCELLED.value],
                "Elapsed time seconds": max(0.0, time.monotonic() - run_started),
                "Root": str(self.root),
                "QRAFT output": str(self.output_writer.path),
                "Evidence": str(self.events_path.parent),
                "Resume": f"qraft run resume {self.root}",
            }),
        )
        return final


class _NullContext:
    def __enter__(self) -> "_NullContext":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None
