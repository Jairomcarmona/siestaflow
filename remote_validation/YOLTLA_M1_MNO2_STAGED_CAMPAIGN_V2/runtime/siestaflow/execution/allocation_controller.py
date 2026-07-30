"""Persistent, dependency-aware, node-aware controller for one SLURM allocation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..engines.siesta.models import OutputClassification
from ..engines.siesta.output_parser import SiestaOutputParser
from ..project_packages import load_structured
from .resource_manager import ResourceManager, ResourceReservation
from .slurm_environment import ShutdownRequest, SignalHandlers, SlurmEnvironment
from .srun_launcher import (
    Launcher,
    StepLaunchSpec,
    StepOutcome,
    launcher_from_config,
)
from .time_utils import parse_slurm_walltime


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYABLE = "RETRYABLE"
    COMPLETED = "COMPLETED"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    BLOCKED = "BLOCKED"
    INTERRUPTED = "INTERRUPTED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class ControllerTask:
    task_id: str
    input_path: str
    input_hashes: Mapping[str, str]
    required_artifacts: tuple[str, ...]
    mpi_processes: int
    cpus_per_process: int
    nodes_required: int
    estimated_runtime_seconds: float
    max_attempts: int
    retry_backoff_seconds: float
    retryable_exit_codes: tuple[int, ...]
    require_scf_converged: bool
    depends_on: tuple[str, ...]
    postcondition: str | None

    @property
    def cpus(self) -> int:
        return self.mpi_processes * self.cpus_per_process


@dataclass(frozen=True)
class ControllerConfig:
    campaign_id: str
    system_id: str
    nodes: int
    total_cpus: int
    tasks_per_node: int
    max_parallel_steps: int
    walltime: str
    shutdown_margin_seconds: float
    termination_grace_seconds: float
    siesta_executable: str
    required_siesta_version: str
    executable_arguments: tuple[str, ...]
    launcher: Mapping[str, object]
    environment: Mapping[str, str]
    failure_policy: str
    tasks: tuple[ControllerTask, ...]


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
    if str(data.get("schema_version")) != "2.0":
        raise ValueError("unsupported V2 controller schema")
    campaign_id = _required_text(data.get("campaign_id"), "campaign_id")
    system_id = _required_text(data.get("system_id"), "system_id")
    slurm = data.get("slurm")
    resources = data.get("resources")
    runtime = data.get("runtime")
    if not all(isinstance(item, Mapping) for item in (slurm, resources, runtime)):
        raise ValueError("slurm, resources and runtime mappings are required")
    for field in ("partition", "account", "qos"):
        _required_text(slurm.get(field), f"slurm.{field}")
    nodes = _positive_int(resources.get("nodes"), "resources.nodes")
    total_cpus = _positive_int(resources.get("total_cpus"), "resources.total_cpus")
    tasks_per_node = _positive_int(
        resources.get("tasks_per_node"), "resources.tasks_per_node"
    )
    if total_cpus != nodes * tasks_per_node:
        raise ValueError("total_cpus must equal nodes * tasks_per_node")
    physical = _positive_int(
        resources.get("physical_cpus_per_node"), "resources.physical_cpus_per_node"
    )
    if tasks_per_node > physical:
        raise ValueError("tasks_per_node exceeds physical CPU capacity")
    walltime = _required_text(resources.get("walltime"), "resources.walltime")
    parse_slurm_walltime(walltime)
    max_parallel = _positive_int(
        resources.get("max_parallel_steps"), "resources.max_parallel_steps"
    )
    margin = _nonnegative_float(
        resources.get("shutdown_margin_seconds"), "resources.shutdown_margin_seconds"
    )
    grace = _nonnegative_float(
        resources.get("termination_grace_seconds"), "resources.termination_grace_seconds"
    )
    siesta = _required_text(runtime.get("siesta_executable"), "runtime.siesta_executable")
    required_version = _required_text(
        runtime.get("required_siesta_version"), "runtime.required_siesta_version"
    )
    launcher = runtime.get("launcher")
    environment = runtime.get("environment", {})
    executable_arguments = runtime.get("executable_arguments", [])
    if not isinstance(launcher, Mapping):
        raise ValueError("runtime.launcher mapping is required")
    launcher_from_config(launcher)  # structural validation only; launches nothing
    if not isinstance(environment, Mapping) or not isinstance(executable_arguments, list):
        raise ValueError("runtime environment/arguments invalid")
    failure_policy = str(data.get("failure_policy", "continue_independent"))
    if failure_policy not in {"continue_independent", "stop_all"}:
        raise ValueError("unsupported failure_policy")

    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ValueError("at least one task is required")
    tasks: list[ControllerTask] = []
    seen: set[str] = set()
    for raw in tasks_raw:
        if not isinstance(raw, Mapping):
            raise ValueError("each task must be a mapping")
        task_id = _required_text(raw.get("task_id"), "task.task_id")
        if task_id in seen or "/" in task_id or "\\" in task_id:
            raise ValueError(f"invalid or duplicate task id: {task_id}")
        seen.add(task_id)
        input_path = _safe_relative(
            _required_text(raw.get("input"), f"{task_id}.input"),
            f"{task_id}.input",
        ).as_posix()
        hashes = raw.get("input_hashes")
        if not isinstance(hashes, Mapping) or not hashes:
            raise ValueError(f"input_hashes required for {task_id}")
        normalized: dict[str, str] = {}
        basenames: set[str] = set()
        for name, digest in hashes.items():
            relative = _safe_relative(str(name), f"{task_id}.input_hashes").as_posix()
            expected = str(digest).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError(f"invalid SHA-256 for {relative}")
            basename = PurePosixPath(relative).name
            if basename in basenames:
                raise ValueError(f"staged basename collision: {basename}")
            basenames.add(basename)
            normalized[relative] = expected
        if input_path not in normalized:
            raise ValueError("primary input must be hash-bound")
        required = raw.get("required_artifacts", [])
        dependencies = raw.get("depends_on", [])
        retryable_codes = raw.get("retryable_exit_codes", [])
        if not all(isinstance(item, list) for item in (required, dependencies, retryable_codes)):
            raise ValueError(f"task lists invalid for {task_id}")
        mpi = _positive_int(raw.get("mpi_processes"), f"{task_id}.mpi_processes")
        cpp = _positive_int(raw.get("cpus_per_process", 1), f"{task_id}.cpus_per_process")
        task_nodes = _positive_int(raw.get("nodes_required"), f"{task_id}.nodes_required")
        if mpi % task_nodes or mpi // task_nodes > tasks_per_node:
            raise ValueError(f"task placement incompatible with tasks_per_node: {task_id}")
        tasks.append(
            ControllerTask(
                task_id,
                input_path,
                normalized,
                tuple(_safe_relative(str(item), "required_artifacts").as_posix() for item in required),
                mpi,
                cpp,
                task_nodes,
                _nonnegative_float(raw.get("estimated_runtime_seconds"), "estimated_runtime_seconds"),
                _positive_int(raw.get("max_attempts"), "max_attempts"),
                _nonnegative_float(raw.get("retry_backoff_seconds", 0), "retry_backoff_seconds"),
                tuple(int(item) for item in retryable_codes),
                bool(raw.get("require_scf_converged", True)),
                tuple(map(str, dependencies)),
                str(raw["postcondition"]) if raw.get("postcondition") else None,
            )
        )
    all_ids = {task.task_id for task in tasks}
    for task in tasks:
        if task.estimated_runtime_seconds <= 0:
            raise ValueError(f"positive runtime estimate required: {task.task_id}")
        if task.task_id in task.depends_on or not set(task.depends_on) <= all_ids:
            raise ValueError(f"invalid dependency graph at {task.task_id}")
    return ControllerConfig(
        campaign_id,
        system_id,
        nodes,
        total_cpus,
        tasks_per_node,
        min(max_parallel, len(tasks)),
        walltime,
        margin,
        grace,
        siesta,
        required_version,
        tuple(map(str, executable_arguments)),
        {str(key): value for key, value in launcher.items()},
        {str(key): str(value) for key, value in environment.items()},
        failure_policy,
        tuple(tasks),
    )


class AllocationController:
    STATE_SCHEMA = "2.0"
    CORE_ARTIFACTS = (
        "stdout.txt",
        "stderr.txt",
        "exit_code.json",
        "timing.json",
        "command.json",
        "placement.json",
    )

    def __init__(
        self,
        *,
        root: Path,
        config: ControllerConfig,
        slurm: SlurmEnvironment,
        launcher: Launcher | None = None,
        resource_manager: ResourceManager | None = None,
        shutdown: ShutdownRequest | None = None,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.slurm = slurm
        self.launcher = launcher or launcher_from_config(config.launcher)
        self.resources = resource_manager or ResourceManager(
            slurm.hosts, config.tasks_per_node
        )
        self.shutdown = shutdown or ShutdownRequest()
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.state_path = self.root / "state/campaign_state.json"
        self.events_path = self.root / "evidence/events.jsonl"
        self.summary_path = self.root / "results/campaign_summary.json"
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {}

    @classmethod
    def from_file(
        cls,
        campaign_path: Path,
        *,
        root: Path | None = None,
        environment: Mapping[str, str] | None = None,
        launcher: Launcher | None = None,
        resource_manager: ResourceManager | None = None,
        shutdown: ShutdownRequest | None = None,
        poll_interval_seconds: float = 0.1,
    ) -> "AllocationController":
        campaign_path = campaign_path.resolve()
        selected_root = (root or campaign_path.parent).resolve()
        config = load_controller_config(campaign_path)
        slurm = SlurmEnvironment.from_mapping(
            environment, configured_walltime=config.walltime
        )
        if slurm.submit_dir != selected_root:
            raise ValueError("campaign root must equal SLURM_SUBMIT_DIR")
        return cls(
            root=selected_root,
            config=config,
            slurm=slurm,
            launcher=launcher,
            resource_manager=resource_manager,
            shutdown=shutdown,
            poll_interval_seconds=poll_interval_seconds,
        )

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": self.STATE_SCHEMA,
            "campaign_id": self.config.campaign_id,
            "system_id": self.config.system_id,
            "status": ExecutionStatus.PENDING.value,
            "current_job_id": self.slurm.job_id,
            "allocation_history": [
                {
                    "job_id": self.slurm.job_id,
                    "started_at_epoch": time.time(),
                    "hosts": list(self.slurm.hosts),
                    "end_time_source": self.slurm.end_time_source,
                }
            ],
            "tasks": {
                task.task_id: {
                    "status": ExecutionStatus.PENDING.value,
                    "attempts": 0,
                    "last_attempt": None,
                    "result_manifest_sha256": None,
                    "reason": "not started",
                    "retry_not_before_epoch": 0.0,
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
        self._atomic_json(
            self.state_path,
            {
                "schema_version": self.STATE_SCHEMA,
                "payload": payload,
                "sha256": hashlib.sha256(_canonical(payload).encode()).hexdigest(),
            },
        )

    def _load_state(self) -> dict[str, Any]:
        wrapper = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload = wrapper.get("payload")
        if wrapper.get("schema_version") != self.STATE_SCHEMA or not isinstance(payload, dict):
            raise ValueError("invalid campaign state schema")
        if hashlib.sha256(_canonical(payload).encode()).hexdigest() != wrapper.get("sha256"):
            raise ValueError("campaign state checksum mismatch")
        if payload.get("campaign_id") != self.config.campaign_id:
            raise ValueError("campaign state identity mismatch")
        if set(payload.get("tasks", {})) != {task.task_id for task in self.config.tasks}:
            raise ValueError("campaign task set changed")
        return payload

    def _event(self, event: str, **fields: Any) -> None:
        record = {
            "event": event,
            "job_id": self.slurm.job_id,
            "at_epoch": time.time(),
            **fields,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _set_task(
        self, task_id: str, status: ExecutionStatus, reason: str, **fields: Any
    ) -> None:
        current = self._state["tasks"][task_id]
        previous = current["status"]
        current.update({"status": status.value, "reason": reason, **fields})
        self._event(
            "TASK_STATE",
            task_id=task_id,
            previous=previous,
            status=status.value,
            reason=reason,
        )
        self._save_state()

    def _verify_source_inputs(self, task: ControllerTask) -> None:
        for relative, expected in task.input_hashes.items():
            path = self.root / _safe_relative(relative, "input_hashes")
            if not path.is_file():
                raise ValueError(f"missing protected input: {relative}")
            if _sha_file(path) != expected:
                raise ValueError(f"protected input hash mismatch: {relative}")

    def _attempt_path(self, task_id: str, attempt_id: str) -> Path:
        return self.root / "work" / task_id / attempt_id

    def _prepare_attempt(
        self, task: ControllerTask, reservation: ResourceReservation
    ) -> tuple[str, Path, Path]:
        state = self._state["tasks"][task.task_id]
        number = int(state["attempts"]) + 1
        attempt_id = f"attempt-{number:04d}"
        attempt = self._attempt_path(task.task_id, attempt_id)
        self._verify_source_inputs(task)
        attempt.mkdir(parents=True, exist_ok=False)
        for relative in task.input_hashes:
            source = self.root / _safe_relative(relative, "input_hashes")
            shutil.copy2(source, attempt / source.name)
        state.update({"attempts": number, "last_attempt": attempt_id})
        self._atomic_json(attempt / "placement.json", reservation.as_dict())
        return attempt_id, attempt, attempt / PurePosixPath(task.input_path).name

    def _execute(
        self,
        task: ControllerTask,
        attempt_id: str,
        attempt: Path,
        primary: Path,
        reservation: ResourceReservation,
    ) -> tuple[StepOutcome | None, str | None]:
        spec = StepLaunchSpec(
            task.task_id,
            attempt_id,
            attempt,
            primary,
            attempt / "stdout.txt",
            attempt / "stderr.txt",
            task.mpi_processes,
            task.cpus_per_process,
            self.config.siesta_executable,
            self.config.executable_arguments,
            self.config.environment,
            reservation,
        )
        try:
            return self.launcher.launch(spec), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def _technical_postcondition(
        self,
        task: ControllerTask,
        attempt: Path,
        record: Any,
    ) -> tuple[bool, str, dict[str, object]]:
        if not task.postcondition:
            return True, "no task-specific postcondition", {}
        if task.postcondition != "m1_sanity_automatic_technical_v1":
            return False, "unknown postcondition", {}
        input_text = (attempt / PurePosixPath(task.input_path).name).read_text(
            encoding="utf-8"
        )
        checks = {
            "atoms_54": bool(re.search(r"^\s*NumberOfAtoms\s+54\s*$", input_text, re.I | re.M)),
            "species_2": bool(re.search(r"^\s*NumberOfSpecies\s+2\s*$", input_text, re.I | re.M)),
            "vdw_lmkll": bool(re.search(r"^\s*XC\.Functional\s+VDW\s*$", input_text, re.I | re.M))
            and bool(re.search(r"^\s*XC\.Authors\s+LMKLL\s*$", input_text, re.I | re.M)),
            "d3_off": bool(re.search(r"^\s*DFTD3\s+false\s*$", input_text, re.I | re.M)),
            "charge_zero": bool(re.search(r"^\s*NetCharge\s+0\s*$", input_text, re.I | re.M)),
            "spin_polarized": bool(re.search(r"^\s*Spin\s+polarized\s*$", input_text, re.I | re.M)),
            "no_dftu": not bool(re.search(r"^\s*(?:%block\s+)?DFTU\.", input_text, re.I | re.M)),
            "md_steps_zero": bool(re.search(r"^\s*MD\.Steps\s+0\s*$", input_text, re.I | re.M)),
            "normal_termination": bool(record.normal_termination),
            "scf_started": bool(record.scf_started),
            "scf_converged": bool(record.scf_converged),
            "reported_atoms_match": record.atoms in {None, 54},
            "reported_species_match": record.species in {None, 2},
            "no_parser_errors": not bool(record.errors),
            "no_ambiguous_warnings": not bool(record.warnings),
            "no_geometry_step_artifact": ".CG" not in record.mentioned_artifacts,
        }
        passed = all(checks.values())
        evidence = {
            "schema_version": "1.0",
            "gate": task.postcondition,
            "decision": "AUTOMATIC_TECHNICAL_PASS" if passed else "AUTOMATIC_TECHNICAL_BLOCK",
            "checks": checks,
            "warnings": list(record.warnings),
            "errors": list(record.errors),
            "scientific_acceptance": False,
        }
        self._atomic_json(attempt / "technical_gate.json", evidence)
        return passed, evidence["decision"], evidence

    def _write_evidence(
        self, task: ControllerTask, attempt: Path, outcome: StepOutcome
    ) -> tuple[dict[str, Any], Any]:
        self._atomic_json(attempt / "exit_code.json", {"exit_code": outcome.exit_code})
        self._atomic_json(
            attempt / "timing.json",
            {
                "elapsed_seconds": outcome.elapsed_seconds,
                "cpu_time_upper_bound_seconds": outcome.elapsed_seconds * task.cpus,
            },
        )
        self._atomic_json(
            attempt / "command.json",
            {
                "argv": list(outcome.command),
                "job_id": self.slurm.job_id,
                "launcher_backend": outcome.launcher_backend,
                "hostfile_sha256": outcome.hostfile_sha256,
            },
        )
        output = (attempt / "stdout.txt").read_text(encoding="utf-8", errors="replace")
        record = SiestaOutputParser().parse(output.splitlines(keepends=True), synthetic=False)
        artifacts: dict[str, str] = {}
        required = tuple(dict.fromkeys((*self.CORE_ARTIFACTS, *task.required_artifacts)))
        for relative in required:
            path = attempt / _safe_relative(relative, "required_artifacts")
            if path.is_file():
                artifacts[relative] = _sha_file(path)
        staged = {
            relative: _sha_file(attempt / PurePosixPath(relative).name)
            for relative in task.input_hashes
        }
        manifest = {
            "schema_version": "2.0",
            "campaign_id": self.config.campaign_id,
            "system_id": self.config.system_id,
            "task_id": task.task_id,
            "attempt_id": outcome.attempt_id,
            "job_id": self.slurm.job_id,
            "exit_code": outcome.exit_code,
            "normal_termination": record.normal_termination,
            "scf_started": record.scf_started,
            "scf_converged": record.scf_converged,
            "parser_classification": record.classification.value,
            "input_hashes": staged,
            "artifacts": artifacts,
            "placement": dict(outcome.placement),
            "launcher_backend": outcome.launcher_backend,
        }
        self._atomic_json(attempt / "result_manifest.json", manifest)
        return manifest, record

    def _completed_evidence_valid(
        self, task: ControllerTask, attempt_id: str, expected_hash: str | None
    ) -> bool:
        attempt = self._attempt_path(task.task_id, attempt_id)
        manifest_path = attempt / "result_manifest.json"
        if not manifest_path.is_file():
            return False
        if expected_hash and _sha_file(manifest_path) != expected_hash:
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._verify_source_inputs(task)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        if task.postcondition:
            gate_path = attempt / "technical_gate.json"
            if (
                not gate_path.is_file()
                or manifest.get("technical_gate_sha256") != _sha_file(gate_path)
            ):
                return False
            try:
                gate = json.loads(gate_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            if gate.get("decision") != "AUTOMATIC_TECHNICAL_PASS":
                return False
        return (
            manifest.get("task_id") == task.task_id
            and manifest.get("exit_code") == 0
            and manifest.get("normal_termination") is True
            and (
                not task.require_scf_converged
                or manifest.get("scf_converged") is True
            )
            and manifest.get("input_hashes") == dict(task.input_hashes)
        )

    def _recover(self) -> None:
        previous = self._state.get("current_job_id")
        if previous != self.slurm.job_id:
            self._state["current_job_id"] = self.slurm.job_id
            self._state["allocation_history"].append(
                {
                    "job_id": self.slurm.job_id,
                    "started_at_epoch": time.time(),
                    "hosts": list(self.slurm.hosts),
                    "end_time_source": self.slurm.end_time_source,
                }
            )
            self._event("NEW_ALLOCATION", previous_job_id=previous)
        by_id = {task.task_id: task for task in self.config.tasks}
        for task_id, item in self._state["tasks"].items():
            task = by_id[task_id]
            last = item.get("last_attempt")
            if item["status"] == ExecutionStatus.COMPLETED.value:
                if not last or not self._completed_evidence_valid(
                    task, last, item.get("result_manifest_sha256")
                ):
                    self._set_task(
                        task_id,
                        ExecutionStatus.INCOMPLETE,
                        "completed evidence no longer validates",
                    )
            elif item["status"] == ExecutionStatus.RUNNING.value:
                self._set_task(
                    task_id,
                    ExecutionStatus.INTERRUPTED,
                    "running attempt recovered in new allocation",
                )
        self._save_state()

    def _dependency_state(self, task: ControllerTask) -> str:
        values = [self._state["tasks"][item]["status"] for item in task.depends_on]
        if any(value in {ExecutionStatus.FAILED_TERMINAL.value, ExecutionStatus.BLOCKED.value} for value in values):
            return "FAILED"
        if all(value == ExecutionStatus.COMPLETED.value for value in values):
            return "READY"
        return "WAIT"

    def _eligible(self, task: ControllerTask) -> bool:
        state = self._state["tasks"][task.task_id]
        status = ExecutionStatus(state["status"])
        return (
            status
            in {
                ExecutionStatus.PENDING,
                ExecutionStatus.RETRYABLE,
                ExecutionStatus.INTERRUPTED,
                ExecutionStatus.INCOMPLETE,
            }
            and int(state["attempts"]) < task.max_attempts
            and float(state.get("retry_not_before_epoch", 0)) <= time.time()
            and self._dependency_state(task) == "READY"
        )

    def _mark_retry_or_terminal(
        self, task: ControllerTask, reason: str, *, retryable: bool, manifest_hash: str | None = None
    ) -> None:
        state = self._state["tasks"][task.task_id]
        attempts = int(state["attempts"])
        if retryable and attempts < task.max_attempts and not self.shutdown.requested:
            delay = task.retry_backoff_seconds * max(1, attempts)
            self._set_task(
                task.task_id,
                ExecutionStatus.RETRYABLE,
                reason,
                result_manifest_sha256=manifest_hash,
                retry_not_before_epoch=time.time() + delay,
            )
        else:
            suffix = " (attempt limit reached)" if retryable else ""
            self._set_task(
                task.task_id,
                ExecutionStatus.FAILED_TERMINAL,
                reason + suffix,
                result_manifest_sha256=manifest_hash,
            )

    def _finalize(
        self,
        task: ControllerTask,
        attempt_id: str,
        attempt: Path,
        outcome: StepOutcome | None,
        error: str | None,
    ) -> None:
        if outcome is None:
            self._mark_retry_or_terminal(
                task, f"launcher failure: {error}", retryable=True
            )
            return
        manifest, record = self._write_evidence(task, attempt, outcome)
        manifest_hash = _sha_file(attempt / "result_manifest.json")
        if outcome.terminated_by_controller:
            self._set_task(
                task.task_id,
                ExecutionStatus.INTERRUPTED,
                "terminated during controlled shutdown",
                result_manifest_sha256=manifest_hash,
            )
            return
        if outcome.exit_code != 0:
            self._mark_retry_or_terminal(
                task,
                f"process exit code {outcome.exit_code}",
                retryable=outcome.exit_code in task.retryable_exit_codes,
                manifest_hash=manifest_hash,
            )
            return
        retryable_classes = {
            OutputClassification.TIMEOUT,
            OutputClassification.NODE_FAILURE,
            OutputClassification.CANCELLED,
            OutputClassification.TRUNCATED_OUTPUT,
        }
        if not record.normal_termination:
            self._mark_retry_or_terminal(
                task,
                f"no normal termination: {record.classification.value}",
                retryable=record.classification in retryable_classes,
                manifest_hash=manifest_hash,
            )
            return
        if task.require_scf_converged and not record.scf_converged:
            self._mark_retry_or_terminal(
                task,
                "SCF did not converge; identical rerun is deterministic",
                retryable=False,
                manifest_hash=manifest_hash,
            )
            return
        passed, reason, _ = self._technical_postcondition(task, attempt, record)
        if not passed:
            self._mark_retry_or_terminal(
                task,
                f"automatic technical gate blocked: {reason}",
                retryable=False,
                manifest_hash=manifest_hash,
            )
            return
        if task.postcondition:
            manifest["technical_gate_sha256"] = _sha_file(
                attempt / "technical_gate.json"
            )
            self._atomic_json(attempt / "result_manifest.json", manifest)
            manifest_hash = _sha_file(attempt / "result_manifest.json")
        self._set_task(
            task.task_id,
            ExecutionStatus.COMPLETED,
            "exit, parser, hashes, placement and technical postcondition verified",
            result_manifest_sha256=manifest_hash,
            retry_not_before_epoch=0.0,
        )

    def _write_summary(self) -> None:
        self._atomic_json(
            self.summary_path,
            {
                "campaign_id": self.config.campaign_id,
                "system_id": self.config.system_id,
                "job_id": self.slurm.job_id,
                "status": self._state["status"],
                "remaining_seconds": self.slurm.remaining_seconds(),
                "walltime_source": self.slurm.end_time_source,
                "shutdown_reason": self.shutdown.reason,
                "resource_state": self.resources.snapshot(),
                "tasks": self._state["tasks"],
                "login_node_persistent_process_required": False,
            },
        )

    def run(self, *, install_signal_handlers: bool = True) -> ExecutionStatus:
        self.root.mkdir(parents=True, exist_ok=True)
        self.slurm.validate_capacity(
            nodes=self.config.nodes,
            total_cpus=self.config.total_cpus,
            tasks_per_node=self.config.tasks_per_node,
        )
        self._state = self._load_state() if self.state_path.is_file() else self._initial_state()
        self._save_state()
        self._recover()
        self._state["status"] = ExecutionStatus.RUNNING.value
        self._save_state()
        self._event(
            "CONTROLLER_STARTED",
            max_parallel_steps=self.config.max_parallel_steps,
            launcher_backend=self.launcher.backend,
            hosts=list(self.slurm.hosts),
        )
        handler = SignalHandlers(
            self.shutdown,
            lambda reason: self._event("SHUTDOWN_SIGNAL", reason=reason),
        )
        context = handler if install_signal_handlers else _NullContext()
        active: dict[
            Future[tuple[StepOutcome | None, str | None]],
            tuple[ControllerTask, str, Path, ResourceReservation],
        ] = {}
        by_id = {task.task_id: task for task in self.config.tasks}
        with context, ThreadPoolExecutor(
            max_workers=self.config.max_parallel_steps
        ) as executor:
            while True:
                for task in self.config.tasks:
                    if self._dependency_state(task) == "FAILED":
                        state = self._state["tasks"][task.task_id]
                        if state["status"] not in {
                            ExecutionStatus.COMPLETED.value,
                            ExecutionStatus.FAILED_TERMINAL.value,
                            ExecutionStatus.BLOCKED.value,
                        }:
                            self._set_task(
                                task.task_id,
                                ExecutionStatus.BLOCKED,
                                "scientific/technical dependency failed",
                            )
                if (
                    not self.shutdown.requested
                    and self.slurm.remaining_seconds()
                    <= self.config.shutdown_margin_seconds
                ):
                    self.shutdown.request("WALLTIME_MARGIN")
                    self._event(
                        "WALLTIME_LAUNCH_STOP",
                        remaining_seconds=self.slurm.remaining_seconds(),
                    )
                launched = False
                if not self.shutdown.requested:
                    for task in self.config.tasks:
                        if len(active) >= self.config.max_parallel_steps:
                            break
                        if not self._eligible(task):
                            continue
                        required = (
                            task.estimated_runtime_seconds
                            + self.config.shutdown_margin_seconds
                        )
                        if self.slurm.remaining_seconds() <= required:
                            continue
                        reservation = self.resources.reserve(
                            task.task_id, task.mpi_processes, task.nodes_required
                        )
                        if reservation is None:
                            continue
                        try:
                            attempt_id, attempt, primary = self._prepare_attempt(
                                task, reservation
                            )
                        except Exception as exc:
                            self.resources.release(task.task_id)
                            self._mark_retry_or_terminal(
                                task,
                                f"attempt preparation failed: {exc}",
                                retryable=False,
                            )
                            continue
                        self._set_task(
                            task.task_id,
                            ExecutionStatus.RUNNING,
                            "launcher step started",
                            last_attempt=attempt_id,
                            placement=reservation.as_dict(),
                        )
                        future = executor.submit(
                            self._execute,
                            task,
                            attempt_id,
                            attempt,
                            primary,
                            reservation,
                        )
                        active[future] = (task, attempt_id, attempt, reservation)
                        launched = True
                if active:
                    if self.shutdown.requested:
                        immediate = self.shutdown.reason == "SIGTERM"
                        grace_expired = (
                            self.shutdown.elapsed_seconds
                            >= self.config.termination_grace_seconds
                        )
                        if immediate or grace_expired or self.slurm.remaining_seconds() <= 1:
                            self.launcher.terminate_all(kill=immediate)
                    done, _ = wait(
                        tuple(active),
                        timeout=self.poll_interval_seconds,
                        return_when=FIRST_COMPLETED,
                    )
                    for future in done:
                        task, attempt_id, attempt, _reservation = active.pop(future)
                        self.resources.release(task.task_id)
                        outcome, error = future.result()
                        self._finalize(task, attempt_id, attempt, outcome, error)
                        if (
                            self.config.failure_policy == "stop_all"
                            and self._state["tasks"][task.task_id]["status"]
                            == ExecutionStatus.FAILED_TERMINAL.value
                        ):
                            self.shutdown.request("TERMINAL_TASK_FAILURE")
                    continue
                unfinished = [
                    task
                    for task in self.config.tasks
                    if self._state["tasks"][task.task_id]["status"]
                    not in {
                        ExecutionStatus.COMPLETED.value,
                        ExecutionStatus.FAILED_TERMINAL.value,
                        ExecutionStatus.BLOCKED.value,
                    }
                ]
                if launched:
                    continue
                if unfinished and not self.shutdown.requested:
                    future_retry = [
                        float(self._state["tasks"][task.task_id].get("retry_not_before_epoch", 0))
                        for task in unfinished
                        if self._dependency_state(task) == "READY"
                    ]
                    if future_retry and min(future_retry) > time.time():
                        time.sleep(
                            min(
                                self.poll_interval_seconds,
                                max(0.0, min(future_retry) - time.time()),
                            )
                        )
                        continue
                break
        statuses = [
            ExecutionStatus(item["status"]) for item in self._state["tasks"].values()
        ]
        if all(status is ExecutionStatus.COMPLETED for status in statuses):
            final = ExecutionStatus.COMPLETED
        elif self.shutdown.requested:
            final = ExecutionStatus.INTERRUPTED
        elif any(status is ExecutionStatus.FAILED_TERMINAL for status in statuses):
            final = ExecutionStatus.FAILED_TERMINAL
        elif any(status is ExecutionStatus.BLOCKED for status in statuses):
            final = ExecutionStatus.BLOCKED
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


__all__ = [
    "AllocationController",
    "ControllerConfig",
    "ControllerTask",
    "ExecutionStatus",
    "load_controller_config",
]
