"""Prepare a compiled workflow as a self-contained, manually submitted run."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .contracts import DecisionStatus, PreparedRun
from .contracts.workflow import require_local_id
from .controller_package import ControllerPackageBuilder
from .engines.siesta.fdf_parser import FDFParser
from .execution_profile import SlurmExecutionProfile
from .siesta_validation import SiestaContextualValidator
from .workflows import load_workflow_lock


_FDF_MEDIA_TYPES = {
    "application/x-siesta-fdf",
    "text/x-siesta-fdf",
}
_RESOURCE_FIELDS = {
    "nodes",
    "mpi_processes",
    "processes_per_node",
    "cpus_per_process",
    "walltime_seconds",
}
_ADAPTIVE_GATE_SCRIPT = "src/siestaflow/execution/adaptive_gate.py"
_EVIDENCE_EVALUATORS = {
    "siestaflow.siesta.mesh-evidence-evaluator": {
        "script": "src/siestaflow/scientific_convergence.py",
        "script_name": "scientific_convergence.py",
        "artifact_type": "siestaflow.mesh-convergence-report",
    },
    "siestaflow.siesta.kgrid-evidence-evaluator": {
        "script": "src/siestaflow/scientific_kgrid.py",
        "script_name": "scientific_kgrid.py",
        "artifact_type": "siestaflow.kgrid-convergence-report",
    },
}
_OBSERVATION_PRODUCER = "siestaflow.siesta.observation-producer"
_ADAPTIVE_CAPABILITIES = {
    "sweep": "siestaflow.gate.deterministic-metric",
    "selection_minimum": "siestaflow.gate.minimum-selector",
    "selection_maximum": "siestaflow.gate.maximum-selector",
    "consumer": "siestaflow.gate.selection-consumer",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _relative_path(value: str, *, field: str) -> Path:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe relative path in {field}: {value!r}")
    return Path(*path.parts)


def _integer(value: Any, *, field: str, positive: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if (positive and value <= 0) or (not positive and value < 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{field} must be a {qualifier} integer")
    return value


@dataclass(frozen=True)
class RunPreparationRequest:
    workflow_lock: Path
    source_root: Path
    execution_profile: Path
    output_root: Path
    run_id: str
    dry_run: bool = False
    resolved_profile: SlurmExecutionProfile | None = None
    execution_resolution: Mapping[str, Any] | None = None
    cluster_snapshot: Path | None = None
    compatibility_evidence: Path | None = None


@dataclass(frozen=True)
class RunPreparationResult:
    status: str
    run_id: str
    package_path: str
    zip_path: str
    zip_sha256: str
    file_count: int
    task_count: int
    workflow_lock_sha256: str
    execution_profile_sha256: str
    run_lock_sha256: str
    controller_campaign_sha256: str
    validation_status: str
    validation_review_codes: tuple[str, ...]
    execution_authorized: bool = False
    submission_performed: bool = False


class RunPreparer:
    """Strict adapter from Core Contracts workflow lock to controller package."""

    def __init__(
        self,
        repository_root: Path,
        *,
        validator: SiestaContextualValidator | None = None,
        task_adapters: Mapping[str, Callable[..., dict[str, Any]]] | None = None,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.validator = validator or SiestaContextualValidator()
        self._task_adapters: dict[str, Callable[..., dict[str, Any]]] = {
            capability: partial(self._evidence_evaluator_task, evaluator=evaluator)
            for capability, evaluator in _EVIDENCE_EVALUATORS.items()
        }
        self._task_adapters[_OBSERVATION_PRODUCER] = self._observation_producer_task
        for capability_id, adapter in (task_adapters or {}).items():
            if capability_id in self._task_adapters:
                raise ValueError(f"run task adapter already registered: {capability_id}")
            if not callable(adapter):
                raise TypeError(f"run task adapter must be callable: {capability_id}")
            self._task_adapters[capability_id] = adapter

    @property
    def task_adapter_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._task_adapters))

    def prepare(self, request: RunPreparationRequest) -> RunPreparationResult:
        lock_path = request.workflow_lock.expanduser().resolve()
        source_root = request.source_root.expanduser().resolve()
        profile_path = request.execution_profile.expanduser().resolve()
        if not source_root.is_dir():
            raise ValueError(f"workflow source root is not a directory: {source_root}")

        envelope, workflow = load_workflow_lock(lock_path)
        profile = request.resolved_profile or SlurmExecutionProfile.load(profile_path)
        resolution = dict(request.execution_resolution or {
            "resolution_mode": "PROFILE_ALREADY_RESOLVED",
            "human_confirmed": None,
            "selection_status": "PROFILE_ALREADY_RESOLVED",
        })
        source_identity = self._source_identity()
        artifacts = {item.artifact_id: item for item in workflow.external_artifacts}
        resolved_sources: dict[str, Path] = {}
        for artifact in workflow.external_artifacts:
            path = (
                source_root
                / _relative_path(
                    artifact.relative_path,
                    field=f"external artifact {artifact.artifact_id}",
                )
            ).resolve()
            try:
                path.relative_to(source_root)
            except ValueError as exc:
                raise ValueError(
                    f"external artifact escapes source root: {artifact.artifact_id}"
                ) from exc
            if not path.is_file() or path.is_symlink():
                raise ValueError(
                    f"external artifact is missing or not regular: {path}"
                )
            if path.stat().st_size != artifact.size_bytes:
                raise ValueError(
                    f"external artifact size mismatch: {artifact.artifact_id}"
                )
            if _sha256(path) != artifact.sha256:
                raise ValueError(
                    f"external artifact hash mismatch: {artifact.artifact_id}"
                )
            resolved_sources[artifact.artifact_id] = path

        review_codes = self._validate_fdf_inputs(workflow, resolved_sources)
        campaign, protected_sources = self._campaign(
            request.run_id,
            workflow,
            profile,
            artifacts,
            resolved_sources,
        )
        campaign_bytes = _json_bytes(campaign)
        campaign_sha256 = hashlib.sha256(campaign_bytes).hexdigest()
        prepared = PreparedRun(
            run_id=request.run_id,
            workflow_id=workflow.workflow_id,
            project_id=workflow.project_id,
            workflow_lock_sha256=envelope.content_sha256,
            execution_profile_id=profile.profile_id,
            execution_profile_sha256=profile.sha256,
            controller_campaign_sha256=campaign_sha256,
            task_ids=tuple(task.task_id for task in workflow.tasks),
            target="slurm",
            metadata={
                "validation_status": (
                    DecisionStatus.REVIEW.value
                    if review_codes
                    else DecisionStatus.PASS.value
                ),
                "validation_review_codes": review_codes,
                "manual_submission_required": True,
                "execution_resolution": resolution,
                "source_identity": source_identity,
            },
        )
        run_envelope = prepared.envelope()

        with tempfile.TemporaryDirectory(prefix="siestaflow-run-") as temporary:
            staging = Path(temporary)
            campaign_path = staging / "campaign.json"
            campaign_path.write_bytes(campaign_bytes)
            normalized_profile = staging / "execution-profile.json"
            normalized_profile.write_bytes(_json_bytes(profile.to_dict()))
            resolution_path = staging / "execution-resolution.json"
            resolution_path.write_bytes(_json_bytes(resolution))
            run_lock = staging / "run.lock.json"
            run_lock.write_bytes(_json_bytes(run_envelope.to_dict()))
            for relative, source in protected_sources.items():
                target = staging / _relative_path(relative, field="protected input")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

            provenance = {
                "workflow.lock.json": lock_path,
                "execution-profile.json": normalized_profile,
                "run.lock.json": run_lock,
                "execution-resolution.json": resolution_path,
            }
            if request.cluster_snapshot is not None:
                snapshot_path = request.cluster_snapshot.expanduser().resolve()
                if not snapshot_path.is_file():
                    raise ValueError(f"cluster snapshot is missing: {snapshot_path}")
                provenance["cluster-snapshot.json"] = snapshot_path
            if request.compatibility_evidence is not None:
                evidence_path = request.compatibility_evidence.expanduser().resolve()
                if not evidence_path.is_file():
                    raise ValueError(f"compatibility evidence is missing: {evidence_path}")
                provenance["execution-compatibility.json"] = evidence_path
            package = ControllerPackageBuilder(self.repository_root).build(
                campaign_path,
                request.output_root,
                dry_run=request.dry_run,
                provenance_files=provenance,
            )
        status = (
            "DRY_RUN_NO_SIDE_EFFECTS"
            if request.dry_run
            else "RUN_PACKAGE_READY_FOR_MANUAL_TRANSFER"
        )
        return RunPreparationResult(
            status=status,
            run_id=request.run_id,
            package_path=package.destination,
            zip_path=package.zip_path,
            zip_sha256=package.zip_sha256,
            file_count=package.file_count,
            task_count=len(workflow.tasks),
            workflow_lock_sha256=envelope.content_sha256,
            execution_profile_sha256=profile.sha256,
            run_lock_sha256=run_envelope.content_sha256,
            controller_campaign_sha256=campaign_sha256,
            validation_status=(
                DecisionStatus.REVIEW.value
                if review_codes
                else DecisionStatus.PASS.value
            ),
            validation_review_codes=review_codes,
        )

    def _source_identity(self) -> dict[str, Any]:
        """Capture repository identity without making Git a runtime dependency."""
        def run(*args: str) -> str | None:
            result = subprocess.run(
                ["git", *args], cwd=self.repository_root,
                text=True, capture_output=True, check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        commit = run("rev-parse", "HEAD")
        dirty = run("status", "--porcelain")
        return {
            "source_commit": commit,
            "source_tree_dirty": None if dirty is None else bool(dirty),
        }

    def _validate_fdf_inputs(
        self,
        workflow,
        resolved_sources: Mapping[str, Path],
    ) -> tuple[str, ...]:
        review: set[str] = set()
        for artifact in workflow.external_artifacts:
            if artifact.media_type.casefold() not in _FDF_MEDIA_TYPES:
                continue
            document = FDFParser().parse_path(
                resolved_sources[artifact.artifact_id]
            )
            report = self.validator.validate(
                document,
                subject_id=artifact.artifact_id,
            )
            blocking = [
                item.code
                for item in report.findings
                if item.status in {DecisionStatus.FAIL, DecisionStatus.BLOCKED}
            ]
            if blocking:
                raise ValueError(
                    "SIESTA input preflight failed for "
                    f"{artifact.relative_path}: {sorted(set(blocking))}"
                )
            review.update(
                item.code
                for item in report.findings
                if item.status is DecisionStatus.REVIEW
            )
        return tuple(sorted(review))

    @staticmethod
    def _gate_resources(task: Any, profile: SlurmExecutionProfile) -> tuple[int, int]:
        """Validate the declared small-gate footprint before local execution."""
        resources = dict(task.resources)
        if set(resources) != _RESOURCE_FIELDS:
            difference = sorted(set(resources) ^ _RESOURCE_FIELDS)
            raise ValueError(
                f"task resource fields mismatch for {task.task_id}: {difference}"
            )
        nodes = _integer(resources["nodes"], field=f"{task.task_id}.nodes")
        ranks = _integer(
            resources["mpi_processes"], field=f"{task.task_id}.mpi_processes"
        )
        ppn = _integer(
            resources["processes_per_node"], field=f"{task.task_id}.processes_per_node")
        cpus = _integer(
            resources["cpus_per_process"], field=f"{task.task_id}.cpus_per_process")
        walltime = _integer(
            resources["walltime_seconds"], field=f"{task.task_id}.walltime_seconds")
        if (nodes, ranks, ppn, cpus) != (1, 1, 1, 1):
            raise ValueError(
                "adaptive gate tasks require nodes=1, mpi_processes=1, "
                f"processes_per_node=1, cpus_per_process=1: {task.task_id}"
            )
        if ranks > profile.total_cpus:
            raise ValueError(f"task exceeds execution allocation: {task.task_id}")
        return walltime, cpus

    @staticmethod
    def _gate_output(task: Any, *, name: str) -> str:
        outputs = [item for item in task.outputs if item.required]
        if len(outputs) != 1 or outputs[0].name != name:
            raise ValueError(
                f"adaptive {task.kind.value} task requires one required {name!r} output: "
                f"{task.task_id}"
            )
        if outputs[0].media_type != "application/json":
            raise ValueError(
                f"adaptive {task.kind.value} output must use application/json: "
                f"{task.task_id}"
            )
        return outputs[0].relative_path

    @staticmethod
    def _local_setting(value: Any, *, field: str) -> str:
        try:
            return require_local_id(str(value), field_name=field)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    def _adaptive_gate_task(
        self,
        task: Any,
        *,
        by_task: Mapping[str, Any],
        profile: SlurmExecutionProfile,
        protected: dict[str, Path],
    ) -> dict[str, Any]:
        """Translate the deliberately narrow Phase 4.1 contract to a gate."""
        if any(item.external_artifact_id is not None for item in task.inputs):
            raise ValueError(
                f"adaptive gate tasks cannot consume external scientific inputs: {task.task_id}"
            )
        script = self.repository_root / _ADAPTIVE_GATE_SCRIPT
        if not script.is_file():
            raise ValueError("adaptive gate runtime script is missing")
        script_relative = (
            PurePosixPath("protected") / task.task_id / "adaptive_gate.py"
        ).as_posix()
        protected[script_relative] = script
        hashes = {script_relative: _sha256(script)}
        destinations = {script_relative: "adaptive_gate.py"}
        walltime, cpus = self._gate_resources(task, profile)
        common: dict[str, Any] = {
            "task_id": task.task_id,
            "kind": "gate",
            "input": script_relative,
            "input_hashes": hashes,
            "input_destinations": destinations,
            "mpi_processes": 1,
            "cpus_per_process": cpus,
            "nodes": 0,
            "estimated_runtime_seconds": walltime,
            "max_attempts": profile.max_attempts,
            "require_scf_converged": False,
            "depends_on": list(task.dependencies),
            "optional_artifacts": [],
        }
        settings = dict(task.settings)
        if task.kind.value == "sweep":
            if task.capability_id != _ADAPTIVE_CAPABILITIES["sweep"]:
                raise ValueError(f"unsupported sweep capability: {task.capability_id}")
            if set(settings) != {"variant_id", "metric_name", "metric_value"}:
                raise ValueError(f"invalid deterministic sweep settings: {task.task_id}")
            variant_id = self._local_setting(settings["variant_id"], field="variant_id")
            metric_name = self._local_setting(settings["metric_name"], field="metric_name")
            value = settings["metric_value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"metric_value must be finite numeric: {task.task_id}")
            common.update({
                "required_artifacts": [self._gate_output(task, name="metric")],
                "transfers": [],
                "command": [
                    "python3", "adaptive_gate.py", "metric", "--output",
                    self._gate_output(task, name="metric"), "--variant-id", variant_id,
                    "--metric-name", metric_name, "--metric-value", str(value),
                ],
            })
            return common
        if task.kind.value == "selection":
            goal = (
                "minimum"
                if task.capability_id == _ADAPTIVE_CAPABILITIES["selection_minimum"]
                else "maximum"
                if task.capability_id == _ADAPTIVE_CAPABILITIES["selection_maximum"]
                else None
            )
            if goal is None:
                raise ValueError(f"unsupported selection capability: {task.capability_id}")
            if set(settings) != {"metric_name"}:
                raise ValueError(f"invalid selector settings: {task.task_id}")
            metric_name = self._local_setting(settings["metric_name"], field="metric_name")
            if not 2 <= len(task.inputs) <= 3:
                raise ValueError(f"selector requires two or three sweep inputs: {task.task_id}")
            transfers: list[dict[str, str]] = []
            arguments: list[str] = []
            for binding in sorted(task.inputs, key=lambda item: item.name):
                parent = by_task[str(binding.source_task_id)]
                if (
                    parent.kind.value != "sweep"
                    or binding.source_output_name != "metric"
                ):
                    raise ValueError(f"selector input is not a sweep metric: {task.task_id}.{binding.name}")
                transfers.append({
                    "from_task": parent.task_id,
                    "artifact": self._gate_output(parent, name="metric"),
                    "destination": binding.destination,
                })
                arguments.extend(("--input", binding.destination))
            common.update({
                "required_artifacts": [self._gate_output(task, name="decision")],
                "transfers": transfers,
                "command": [
                    "python3", "adaptive_gate.py", "select", "--output",
                    self._gate_output(task, name="decision"), *arguments,
                    "--metric-name", metric_name, "--goal", goal,
                ],
            })
            return common
        if task.kind.value == "transformation":
            if task.capability_id != _ADAPTIVE_CAPABILITIES["consumer"]:
                raise ValueError(f"unsupported transformation capability: {task.capability_id}")
            if settings or len(task.inputs) != 1:
                raise ValueError(f"invalid selection consumer settings: {task.task_id}")
            binding = task.inputs[0]
            parent = by_task[str(binding.source_task_id)]
            if parent.kind.value != "selection" or binding.source_output_name != "decision":
                raise ValueError(f"consumer input is not a selector decision: {task.task_id}")
            common.update({
                "required_artifacts": [self._gate_output(task, name="result")],
                "transfers": [{
                    "from_task": parent.task_id,
                    "artifact": self._gate_output(parent, name="decision"),
                    "destination": binding.destination,
                }],
                "command": [
                    "python3", "adaptive_gate.py", "consume", "--output",
                    self._gate_output(task, name="result"), "--selection", binding.destination,
                ],
            })
            return common
        raise ValueError(f"unsupported adaptive task kind: {task.kind.value}")

    def _evidence_evaluator_task(
        self,
        task: Any,
        *,
        evaluator: Mapping[str, str],
        by_task: Mapping[str, Any],
        artifacts: Mapping[str, Any],
        resolved_sources: Mapping[str, Path],
        profile: SlurmExecutionProfile,
        protected: dict[str, Path],
    ) -> dict[str, Any]:
        if task.kind.value != "validation" or task.capability_id not in _EVIDENCE_EVALUATORS:
            raise ValueError(f"unsupported scientific evaluator: {task.task_id}")
        if set(task.settings) != {"rule_id"}:
            raise ValueError(f"scientific evaluator settings mismatch: {task.task_id}")
        self._local_setting(task.settings["rule_id"], field="rule_id")
        output = self._gate_output(task, name="report")
        port = next(item for item in task.outputs if item.name == "report")
        if port.artifact_type != evaluator["artifact_type"]:
            raise ValueError(f"scientific evaluator report artifact type mismatch: {task.task_id}")
        script = self.repository_root / evaluator["script"]
        if not script.is_file():
            raise ValueError("scientific evaluator runtime script is missing")
        script_relative = (
            PurePosixPath("protected") / task.task_id / evaluator["script_name"]
        ).as_posix()
        protected[script_relative] = script
        hashes = {script_relative: _sha256(script)}
        destinations = {script_relative: evaluator["script_name"]}
        transfers: list[dict[str, str]] = []
        rule_destination: str | None = None
        observation_destinations: list[str] = []
        for binding in sorted(task.inputs, key=lambda item: item.name):
            if binding.name == "rule":
                rule_destination = binding.destination
            elif binding.name.startswith("observation_"):
                observation_destinations.append(binding.destination)
            else:
                raise ValueError(f"unexpected scientific evaluator input: {binding.name}")
            if binding.media_type != "application/json":
                raise ValueError(f"scientific evaluator inputs must use application/json: {binding.name}")
            if binding.external_artifact_id is not None:
                artifact = artifacts[binding.external_artifact_id]
                package_source = (
                    PurePosixPath("protected")
                    / task.task_id
                    / binding.name
                    / PurePosixPath(artifact.relative_path).name
                ).as_posix()
                protected[package_source] = resolved_sources[artifact.artifact_id]
                hashes[package_source] = artifact.sha256
                destinations[package_source] = binding.destination
            else:
                parent = by_task[str(binding.source_task_id)]
                parent_output = next(
                    (item for item in parent.outputs if item.name == binding.source_output_name),
                    None,
                )
                if parent_output is None or not parent_output.required:
                    raise ValueError(f"scientific evaluator input is not a required parent output: {binding.name}")
                transfers.append({
                    "from_task": parent.task_id,
                    "artifact": parent_output.relative_path,
                    "destination": binding.destination,
                })
        if rule_destination is None or not observation_destinations:
            raise ValueError("scientific evaluator requires one rule and observation inputs")
        arguments: list[str] = []
        for destination in sorted(observation_destinations):
            arguments.extend(("--observation", destination))
        walltime, cpus = self._gate_resources(task, profile)
        return {
            "task_id": task.task_id,
            "kind": "gate",
            "input": script_relative,
            "input_hashes": hashes,
            "input_destinations": destinations,
            "required_artifacts": [output],
            "optional_artifacts": [],
            "depends_on": list(task.dependencies),
            "transfers": transfers,
            "nodes": 0,
            "mpi_processes": 1,
            "cpus_per_process": cpus,
            "estimated_runtime_seconds": walltime,
            "max_attempts": profile.max_attempts,
            "require_scf_converged": False,
            "command": [
                "python3", evaluator["script_name"], "evaluate",
                "--rule", rule_destination, *arguments, "--output", output,
            ],
        }

    def _observation_producer_task(
        self,
        task: Any,
        *,
        by_task: Mapping[str, Any],
        artifacts: Mapping[str, Any],
        resolved_sources: Mapping[str, Path],
        profile: SlurmExecutionProfile,
        protected: dict[str, Path],
    ) -> dict[str, Any]:
        """Package the pure parser as a small postprocessing gate."""
        if task.kind.value != "postprocess" or task.capability_id != _OBSERVATION_PRODUCER:
            raise ValueError(f"unsupported observation producer: {task.task_id}")
        if set(task.settings) != {"axis", "observation_id"} or task.settings["axis"] not in {"mesh", "kgrid"}:
            raise ValueError(f"observation producer settings mismatch: {task.task_id}")
        axis = str(task.settings["axis"])
        observation_id = self._local_setting(task.settings["observation_id"], field="observation_id")
        output = self._gate_output(task, name="observation")
        port = next(item for item in task.outputs if item.name == "observation")
        if port.artifact_type != f"siestaflow.{axis}-observation":
            raise ValueError(f"observation producer output artifact type mismatch: {task.task_id}")
        required = {"fdf", "stdout", "force_stress", "pseudopotential_manifest"}
        if {item.name for item in task.inputs} != required or any(item.external_artifact_id is None for item in task.inputs):
            raise ValueError("observation producer currently consumes four external immutable artifacts")
        script = self.repository_root / "src/siestaflow/scientific_observations.py"
        if not script.is_file():
            raise ValueError("scientific observation runtime script is missing")
        script_relative = (PurePosixPath("protected") / task.task_id / "scientific_observations.py").as_posix()
        protected[script_relative] = script
        hashes = {script_relative: _sha256(script)}
        destinations = {script_relative: "scientific_observations.py"}
        for binding in task.inputs:
            artifact = artifacts[binding.external_artifact_id]
            package_source = (PurePosixPath("protected") / task.task_id / binding.name / PurePosixPath(artifact.relative_path).name).as_posix()
            protected[package_source] = resolved_sources[artifact.artifact_id]
            hashes[package_source] = artifact.sha256
            destinations[package_source] = binding.destination
        walltime, cpus = self._gate_resources(task, profile)
        return {
            "task_id": task.task_id, "kind": "gate", "input": script_relative,
            "input_hashes": hashes, "input_destinations": destinations,
            "required_artifacts": [output], "optional_artifacts": [],
            "depends_on": list(task.dependencies), "transfers": [], "nodes": 0,
            "mpi_processes": 1, "cpus_per_process": cpus,
            "estimated_runtime_seconds": walltime, "max_attempts": profile.max_attempts,
            "require_scf_converged": False,
            "command": ["python3", "scientific_observations.py", "--axis", axis,
                        "--observation-id", observation_id, "--fdf", "input/fdf",
                        "--stdout", "input/stdout", "--force-stress", "input/force_stress",
                        "--pseudopotential-manifest", "input/pseudopotential_manifest",
                        "--output", output],
        }

    def _campaign(
        self,
        run_id: str,
        workflow,
        profile: SlurmExecutionProfile,
        artifacts: Mapping[str, Any],
        resolved_sources: Mapping[str, Path],
    ) -> tuple[dict[str, Any], dict[str, Path]]:
        tasks: list[dict[str, Any]] = []
        protected: dict[str, Path] = {}
        by_task = {task.task_id: task for task in workflow.tasks}
        for task in workflow.tasks:
            adapter = self._task_adapters.get(task.capability_id)
            if adapter is not None:
                tasks.append(adapter(
                    task,
                    by_task=by_task,
                    artifacts=artifacts,
                    resolved_sources=resolved_sources,
                    profile=profile,
                    protected=protected,
                ))
                continue
            if task.kind.value in {"sweep", "selection", "transformation"}:
                tasks.append(
                    self._adaptive_gate_task(
                        task,
                        by_task=by_task,
                        profile=profile,
                        protected=protected,
                    )
                )
                continue
            if task.kind.value != "calculation":
                raise ValueError(
                    f"run adapter does not yet execute task kind {task.kind.value}: "
                    f"{task.task_id}"
                )
            if task.capability_id != "siestaflow.engine.siesta":
                raise ValueError(
                    f"unsupported execution capability: {task.capability_id}"
                )
            if task.settings:
                raise ValueError(
                    f"task settings require an explicit engine adapter: {task.task_id}"
                )
            resources = dict(task.resources)
            if set(resources) != _RESOURCE_FIELDS:
                difference = sorted(set(resources) ^ _RESOURCE_FIELDS)
                raise ValueError(
                    f"task resource fields mismatch for {task.task_id}: {difference}"
                )
            nodes = _integer(resources["nodes"], field=f"{task.task_id}.nodes")
            ranks = _integer(
                resources["mpi_processes"],
                field=f"{task.task_id}.mpi_processes",
            )
            ppn = _integer(
                resources["processes_per_node"],
                field=f"{task.task_id}.processes_per_node",
            )
            cpus = _integer(
                resources["cpus_per_process"],
                field=f"{task.task_id}.cpus_per_process",
            )
            walltime = _integer(
                resources["walltime_seconds"],
                field=f"{task.task_id}.walltime_seconds",
            )
            if nodes > profile.nodes or ranks * cpus > profile.total_cpus:
                raise ValueError(
                    f"task exceeds execution allocation: {task.task_id}"
                )
            if ranks != nodes * ppn:
                raise ValueError(
                    f"task rank placement mismatch: {task.task_id}"
                )
            if profile.launcher_kind == "hydra" and profile.processes_per_node != ppn:
                if ranks != profile.total_cpus:
                    raise ValueError(
                        f"task and Hydra profile processes_per_node disagree: "
                        f"{task.task_id}"
                    )
                # The workflow retains its scientific resource declaration;
                # a full-allocation run may remap the same rank count across
                # the resolved Slurm allocation without changing the DAG.
                nodes = profile.nodes
            if cpus != 1:
                raise ValueError(
                    "prepared Slurm packages currently require "
                    f"cpus_per_process=1: {task.task_id}"
                )

            hashes: dict[str, str] = {}
            destinations: dict[str, str] = {}
            primary: str | None = None
            transfers: list[dict[str, str]] = []
            for binding in task.inputs:
                if binding.external_artifact_id is not None:
                    artifact = artifacts[binding.external_artifact_id]
                    suffix = PurePosixPath(artifact.relative_path).name
                    package_source = (
                        PurePosixPath("protected")
                        / task.task_id
                        / binding.name
                        / suffix
                    ).as_posix()
                    hashes[package_source] = artifact.sha256
                    destinations[package_source] = binding.destination
                    protected[package_source] = resolved_sources[
                        artifact.artifact_id
                    ]
                    if artifact.media_type.casefold() in _FDF_MEDIA_TYPES:
                        if primary is not None:
                            raise ValueError(
                                f"multiple FDF inputs for task {task.task_id}"
                            )
                        primary = package_source
                else:
                    parent = by_task[str(binding.source_task_id)]
                    output = next(
                        (
                            item
                            for item in parent.outputs
                            if item.name == binding.source_output_name
                        ),
                        None,
                    )
                    if output is None or not output.required:
                        raise ValueError(
                            f"produced input is not a required parent output: "
                            f"{task.task_id}.{binding.name}"
                        )
                    transfers.append(
                        {
                            "from_task": parent.task_id,
                            "artifact": output.relative_path,
                            "destination": binding.destination,
                        }
                    )
            if primary is None:
                raise ValueError(
                    f"SIESTA task has no external FDF input: {task.task_id}"
                )
            tasks.append(
                {
                    "task_id": task.task_id,
                    "kind": "siesta",
                    "input": primary,
                    "input_hashes": hashes,
                    "input_destinations": destinations,
                    "required_artifacts": [
                        item.relative_path for item in task.outputs if item.required
                    ],
                    "optional_artifacts": [
                        item.relative_path
                        for item in task.outputs
                        if not item.required
                    ],
                    "depends_on": list(task.dependencies),
                    "transfers": transfers,
                    "nodes": nodes,
                    "mpi_processes": ranks,
                    "cpus_per_process": cpus,
                    "estimated_runtime_seconds": walltime,
                    "max_attempts": profile.max_attempts,
                    "require_scf_converged": profile.require_scf_converged,
                }
            )
        campaign = {
            "schema_version": "2.0",
            "campaign_id": run_id,
            "system_id": workflow.workflow_id,
            "slurm": {
                "partition": profile.partition,
                "account": profile.account,
                "qos": profile.qos,
            },
            "resources": {
                "nodes": profile.nodes,
                "total_cpus": profile.total_cpus,
                "memory": profile.memory,
                "walltime": profile.walltime,
                "max_parallel_steps": profile.max_parallel_steps,
                "shutdown_margin_seconds": profile.shutdown_margin_seconds,
                "termination_grace_seconds": (
                    profile.termination_grace_seconds
                ),
            },
            "runtime": {
                "module_commands": list(profile.module_commands),
                "siesta_executable": profile.siesta_executable,
                "executable_arguments": list(profile.executable_arguments),
                "launcher": {
                    "kind": profile.launcher_kind,
                    "command": list(profile.launcher_command),
                    "arguments": list(profile.launcher_arguments),
                    "bootstrap": profile.launcher_bootstrap,
                    "processes_per_node": profile.processes_per_node,
                },
                "exclusive": profile.exclusive,
                "environment": dict(profile.environment),
            },
            "tasks": tasks,
        }
        return campaign, protected
