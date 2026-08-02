"""Read-only integrity, progress, and resubmission planning for run packages."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .execution.allocation_controller import ExecutionStatus, load_controller_config
from .execution.campaign_progress import read_campaign_progress
from .execution_profile import SlurmExecutionProfile
from .workflows import load_run_lock, load_workflow_lock


_CHECKSUM_LINE = re.compile(r"([0-9a-f]{64})\s+(.+)")
_MUTABLE_DIRECTORIES = {"evidence", "results", "state", "work"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, value: str) -> Path:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe package path: {value!r}")
    target = root.joinpath(*path.parts)
    if not target.is_file() or target.is_symlink():
        raise ValueError(f"missing or non-regular package file: {value}")
    return target


@dataclass(frozen=True)
class PreparedRunInspection:
    status: str
    package_path: str
    run_id: str
    workflow_id: str
    project_id: str
    execution_profile_id: str
    task_count: int
    immutable_file_count: int
    campaign_status: str
    completed: int
    total: int
    percent: float
    running: tuple[str, ...]
    ready: tuple[str, ...]
    execution_authorized: bool = False
    submission_performed: bool = False


@dataclass(frozen=True)
class ResumePlan:
    status: str
    run_id: str
    campaign_status: str
    resubmission_required: bool
    command: str | None
    retryable_tasks: tuple[str, ...]
    exhausted_tasks: tuple[str, ...]
    prior_job_terminal_required: bool
    terminal_confirmation_received: bool
    submission_performed: bool = False


class RunInspector:
    """Verify immutable provenance before trusting mutable campaign state."""

    def inspect(self, package: Path) -> PreparedRunInspection:
        root = package.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"prepared run package is not a directory: {root}")
        immutable = self._verify_package(root)
        workflow_envelope, workflow = load_workflow_lock(
            root / "workflow.lock.json"
        )
        _, run = load_run_lock(root / "run.lock.json")
        profile = SlurmExecutionProfile.load(root / "execution-profile.json")
        campaign_path = root / "campaign.yaml"
        config = load_controller_config(campaign_path)

        if run.run_id != config.campaign_id:
            raise ValueError("run lock and controller campaign ids disagree")
        if run.workflow_id != workflow.workflow_id:
            raise ValueError("run lock and workflow ids disagree")
        if run.project_id != workflow.project_id:
            raise ValueError("run lock and workflow project ids disagree")
        if run.workflow_lock_sha256 != workflow_envelope.content_sha256:
            raise ValueError("run lock workflow checksum mismatch")
        if run.execution_profile_id != profile.profile_id:
            raise ValueError("run lock and execution profile ids disagree")
        if run.execution_profile_sha256 != profile.sha256:
            raise ValueError("run lock execution profile checksum mismatch")
        if run.controller_campaign_sha256 != _sha256(campaign_path):
            raise ValueError("run lock controller campaign checksum mismatch")
        configured = tuple(task.task_id for task in config.tasks)
        compiled = tuple(task.task_id for task in workflow.tasks)
        if run.task_ids != compiled or run.task_ids != configured:
            raise ValueError("run task identities disagree across contracts")
        resolution = run.metadata.get("execution_resolution")
        if isinstance(resolution, Mapping) and resolution.get("resolution_mode") != "PROFILE_ALREADY_RESOLVED":
            resolution_path = _safe_path(root, "execution-resolution.json")
            persisted = json.loads(resolution_path.read_text(encoding="utf-8"))
            if persisted != resolution or resolution.get("human_confirmed") is not True:
                raise ValueError("resolved execution confirmation is not immutable")
            expected = {
                "selected_partition": profile.partition,
                "selected_account": profile.account,
                "selected_qos": profile.qos,
                "selected_nodes": profile.nodes,
                "selected_total_ranks": profile.total_cpus,
                "selected_walltime": profile.walltime,
            }
            if any(resolution.get(key) != value for key, value in expected.items()):
                raise ValueError("resolved execution and submit configuration disagree")

        progress = read_campaign_progress(root)
        return PreparedRunInspection(
            status="PREPARED_RUN_VERIFIED",
            package_path=str(root),
            run_id=run.run_id,
            workflow_id=run.workflow_id,
            project_id=run.project_id,
            execution_profile_id=run.execution_profile_id,
            task_count=len(run.task_ids),
            immutable_file_count=len(immutable),
            campaign_status=str(progress["campaign_status"]),
            completed=int(progress["completed"]),
            total=int(progress["total"]),
            percent=float(progress["percent"]),
            running=tuple(map(str, progress["running"])),
            ready=tuple(map(str, progress["ready"])),
        )

    def status(self, package: Path) -> dict[str, Any]:
        inspection = self.inspect(package)
        progress = read_campaign_progress(package)
        return {
            "status": "PREPARED_RUN_STATUS_VERIFIED",
            "run": inspection,
            "progress": progress,
        }

    def resume(
        self,
        package: Path,
        *,
        previous_job_terminal: bool = False,
    ) -> ResumePlan:
        inspection = self.inspect(package)
        root = Path(inspection.package_path)
        config = load_controller_config(root / "campaign.yaml")
        progress = read_campaign_progress(root)
        task_state = {
            str(item["task_id"]): item for item in progress["tasks"]
        }
        retryable: list[str] = []
        exhausted: list[str] = []
        retryable_states = {
            ExecutionStatus.PENDING.value,
            ExecutionStatus.RUNNING.value,
            ExecutionStatus.INTERRUPTED.value,
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.INCOMPLETE.value,
        }
        for task in config.tasks:
            item = task_state[task.task_id]
            if item["status"] not in retryable_states:
                continue
            if int(item["attempts"]) < task.max_attempts:
                retryable.append(task.task_id)
            else:
                exhausted.append(task.task_id)

        campaign_status = str(progress["campaign_status"])
        if campaign_status == ExecutionStatus.COMPLETED.value:
            status = "NO_RESUBMISSION_REQUIRED"
            command = None
            required = False
            prior_terminal = False
        elif campaign_status != ExecutionStatus.PENDING.value and (
            not previous_job_terminal
        ):
            status = "PREVIOUS_JOB_TERMINAL_CONFIRMATION_REQUIRED"
            command = None
            required = False
            prior_terminal = True
        elif retryable:
            status = (
                "INITIAL_SUBMISSION_REQUIRED"
                if campaign_status == ExecutionStatus.PENDING.value
                else "RESUBMISSION_REQUIRED"
            )
            command = "sbatch submit.slurm"
            required = True
            prior_terminal = campaign_status != ExecutionStatus.PENDING.value
        else:
            status = "BLOCKED_REVIEW_REQUIRED"
            command = None
            required = False
            prior_terminal = False
        return ResumePlan(
            status=status,
            run_id=inspection.run_id,
            campaign_status=campaign_status,
            resubmission_required=required,
            command=command,
            retryable_tasks=tuple(retryable),
            exhausted_tasks=tuple(exhausted),
            prior_job_terminal_required=prior_terminal,
            terminal_confirmation_received=previous_job_terminal,
        )

    def _verify_package(self, root: Path) -> Mapping[str, str]:
        manifest_path = _safe_path(root, "manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, Mapping):
            raise ValueError("package manifest must be a mapping")
        immutable = manifest.get("immutable_files")
        if not isinstance(immutable, Mapping) or not immutable:
            raise ValueError("package immutable file manifest is missing")
        normalized: dict[str, str] = {}
        for name, expected_raw in immutable.items():
            expected = str(expected_raw).lower()
            if len(expected) != 64 or any(
                item not in "0123456789abcdef" for item in expected
            ):
                raise ValueError(f"invalid immutable checksum: {name}")
            target = _safe_path(root, str(name))
            if _sha256(target) != expected:
                raise ValueError(f"immutable package checksum mismatch: {name}")
            normalized[str(name)] = expected
        mandatory = {
            "campaign.yaml",
            "execution-profile.json",
            "run.lock.json",
            "workflow.lock.json",
        }
        if not mandatory.issubset(normalized):
            missing = sorted(mandatory - set(normalized))
            raise ValueError(f"prepared run provenance is incomplete: {missing}")

        checksum_path = _safe_path(root, "checksums.sha256")
        checksums: dict[str, str] = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            match = _CHECKSUM_LINE.fullmatch(line)
            if match is None:
                raise ValueError(f"invalid checksum line: {line!r}")
            expected, name = match.groups()
            if name in checksums:
                raise ValueError(f"duplicate package checksum: {name}")
            target = _safe_path(root, name)
            if _sha256(target) != expected:
                raise ValueError(f"package checksum mismatch: {name}")
            checksums[name] = expected
        expected_checksum_names = set(normalized) | {"manifest.json"}
        if set(checksums) != expected_checksum_names:
            difference = sorted(set(checksums) ^ expected_checksum_names)
            raise ValueError(f"package checksum coverage mismatch: {difference}")

        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
            and path.relative_to(root).parts[0] not in _MUTABLE_DIRECTORIES
            and not path.name.startswith(("OUT.", "ERROR."))
        }
        expected_actual = set(checksums) | {"checksums.sha256"}
        if actual != expected_actual:
            difference = sorted(actual ^ expected_actual)
            raise ValueError(f"immutable package coverage mismatch: {difference}")
        return normalized
