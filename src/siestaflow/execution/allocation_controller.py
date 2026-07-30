"""Persistent controller that schedules scientific srun steps in one allocation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..engines.siesta.output_parser import SiestaOutputParser
from ..project_packages import load_structured
from .direct_launcher import DirectLauncher
from .hydra_launcher import HydraLauncher
from .slurm_environment import ShutdownRequest, SignalHandlers, SlurmEnvironment
from .srun_launcher import SrunLauncher, StepLaunchSpec, StepLauncher, StepOutcome


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
        if launcher_kind not in {"srun", "hydra"}:
            raise ValueError("runtime.launcher.kind must be srun or hydra")
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
        basenames: set[str] = set()
        for name, digest in hashes.items():
            relative = _safe_relative(str(name), f"{task_id}.input_hashes").as_posix()
            expected = str(digest).lower()
            if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
                raise ValueError(f"invalid SHA-256 for {relative}")
            basename = PurePosixPath(relative).name
            if basename in basenames:
                raise ValueError(f"staged input basename collision: {basename}")
            basenames.add(basename)
            normalized_hashes[relative] = expected
        if input_path not in normalized_hashes:
            raise ValueError(f"primary input is not hash-bound: {input_path}")
        required_raw = raw.get("required_artifacts", [])
        if not isinstance(required_raw, list):
            raise ValueError(f"required_artifacts must be a list for {task_id}")
        required = tuple(_safe_relative(str(item), f"{task_id}.required_artifacts").as_posix() for item in required_raw)
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
            if destination in destinations or PurePosixPath(destination).name in basenames:
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
        ))
    if max_parallel > len(tasks):
        max_parallel = len(tasks)
    for task in tasks:
        if task.cpus > total_cpus:
            raise ValueError(f"task {task.task_id} requests more CPUs than campaign allocation")
        if task.nodes > nodes:
            raise ValueError(f"task {task.task_id} requests more nodes than campaign allocation")
        if launcher_kind == "hydra" and task.task_kind == "siesta":
            if task.nodes <= 0:
                raise ValueError(f"Hydra task {task.task_id} requires an explicit positive nodes value")
            if processes_per_node is None:
                raise ValueError("Hydra launcher requires processes_per_node")
            if task.mpi_processes != task.nodes * processes_per_node:
                raise ValueError(
                    f"Hydra placement mismatch for {task.task_id}: "
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
        if launcher is not None:
            self.launcher = launcher
        elif config.launcher_kind == "hydra":
            self.launcher = HydraLauncher(
                command=config.srun_command,
                arguments=config.srun_arguments,
                bootstrap=config.launcher_bootstrap,
            )
        else:
            self.launcher = SrunLauncher(
                srun_command=config.srun_command, srun_arguments=config.srun_arguments,
                exclusive=config.exclusive,
            )
        self.shutdown = shutdown or ShutdownRequest()
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.state_path = self.root / "state" / "campaign_state.json"
        self.events_path = self.root / "evidence" / "events.jsonl"
        self.summary_path = self.root / "results" / "campaign_summary.json"
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

    def _task_state(self, task_id: str) -> dict[str, Any]:
        return self._state["tasks"][task_id]

    def _set_task(self, task_id: str, status: ExecutionStatus, reason: str, **fields: Any) -> None:
        current = self._task_state(task_id)
        previous = current["status"]
        current.update({"status": status.value, "reason": reason, **fields})
        self._event("TASK_STATE", task_id=task_id, previous=previous, status=status.value, reason=reason)
        self._save_state()

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
        for transfer in task.transfers:
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
            shutil.copy2(source, destination)
            transferred.append({
                "from_task": transfer.from_task,
                "from_attempt": source_attempt_id,
                "source_result_manifest_sha256": source_manifest_hash,
                "artifact": transfer.artifact,
                "destination": transfer.destination,
                "sha256": actual,
            })
        if transferred:
            self._atomic_json(
                attempt / "transfer_manifest.json",
                {"schema_version": "1.0", "transfers": transferred},
            )
        return tuple(transferred)

    def _prepare_attempt(self, task: ControllerTask) -> tuple[str, Path, Path]:
        task_state = self._task_state(task.task_id)
        number = int(task_state["attempts"]) + 1
        attempt_id = f"attempt-{number:04d}"
        attempt = self._attempt_path(task.task_id, attempt_id)
        self._verify_source_inputs(task)
        attempt.mkdir(parents=True, exist_ok=False)
        for relative in task.input_hashes:
            source = self.root / _safe_relative(relative, "input_hashes")
            shutil.copy2(source, attempt / source.name)
        self._transfer_inputs(task, attempt)
        primary = attempt / PurePosixPath(task.input_path).name
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
        required = tuple(dict.fromkeys((*self.CORE_ARTIFACTS, *task.required_artifacts)))
        for relative in required:
            path = attempt / _safe_relative(relative, "required_artifacts")
            if path.is_file():
                artifacts[relative] = _sha_file(path)
        staged_inputs = {
            relative: _sha_file(attempt / PurePosixPath(relative).name)
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
            path = attempt / PurePosixPath(relative).name
            if not path.is_file() or _sha_file(path) != expected:
                return False, f"staged input hash mismatch: {relative}"
        transferred = manifest.get("transferred_inputs")
        if not isinstance(transferred, list) or len(transferred) != len(task.transfers):
            return False, "transferred input manifest mismatch"
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
            if not destination.is_file() or _sha_file(destination) != digest:
                return False, f"transferred input hash mismatch: {identity[2]}"
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
            elif item["status"] == ExecutionStatus.RUNNING.value:
                valid, reason = self._validate_attempt(task, last, item.get("result_manifest_sha256")) if last else (False, "attempt missing")
                if valid:
                    self._set_task(task_id, ExecutionStatus.COMPLETED, reason, result_manifest_sha256=_sha_file(self._attempt_path(task_id, last) / "result_manifest.json"))
                else:
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
        self.root.mkdir(parents=True, exist_ok=True)
        self.slurm.validate_capacity(nodes=self.config.nodes, total_cpus=self.config.total_cpus)
        if self.config.launcher_kind == "hydra":
            self._allocated_hosts = self.slurm.resolve_hostnames()
            if len(self._allocated_hosts) != self.config.nodes:
                raise ValueError(
                    "configured campaign nodes must equal the resolved Hydra allocation"
                )
        if self.state_path.is_file():
            self._state = self._load_state()
        else:
            self._state = self._initial_state()
            self._save_state()
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
                            self.config.launcher_kind == "hydra"
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
        return final


class _NullContext:
    def __enter__(self) -> "_NullContext":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None
