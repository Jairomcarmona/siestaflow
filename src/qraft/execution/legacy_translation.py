"""Translate accepted allocation-controller schema into canonical contracts.

The translator is the only new-production boundary allowed to understand old
field names.  It creates no attempts and performs no scheduling.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..contracts import (
    ArtifactReference,
    ArtifactRole,
    CompiledWorkflow,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowInputBinding,
    WorkflowOutputPort,
    WorkflowTaskKind,
    WorkflowTaskNode,
)
from ..core import ExecutionSpec, ScientificIdentity
from .allocation_controller_compat import ControllerConfig, ControllerTask
from .capability_plugins import (
    GENERIC_COMMAND_CAPABILITY,
    SIESTA_ENGINE_CAPABILITY,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _local_id(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-.")
    return normalized or fallback


def _media_type(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    return {
        ".fdf": "application/x-siesta-fdf",
        ".psml": "application/x-psml",
        ".psf": "application/x-siesta-psf",
        ".xyz": "chemical/x-xyz",
        ".json": "application/json",
        ".csv": "text/csv",
        ".txt": "text/plain",
    }.get(suffix, "application/octet-stream")


def _topological(tasks: tuple[ControllerTask, ...]) -> tuple[ControllerTask, ...]:
    remaining = {task.task_id: task for task in tasks}
    emitted: list[ControllerTask] = []
    complete: set[str] = set()
    while remaining:
        ready = [
            task
            for task in tasks
            if task.task_id in remaining and set(task.depends_on) <= complete
        ]
        if not ready:
            raise ValueError("legacy controller graph cannot be topologically translated")
        for task in ready:
            emitted.append(task)
            complete.add(task.task_id)
            remaining.pop(task.task_id)
    return tuple(emitted)


@dataclass(frozen=True)
class CanonicalLegacyPlan:
    workflow: CompiledWorkflow
    scientific_identities: Mapping[str, ScientificIdentity]
    execution_specs: Mapping[str, ExecutionSpec]


def translate_controller_config(
    config: ControllerConfig, *, root: Path
) -> CanonicalLegacyPlan:
    """Translate a validated schema-1/2 config without executing it."""

    root = root.resolve()
    tasks = _topological(config.tasks)
    external_artifacts: list[ArtifactReference] = []
    nodes: list[WorkflowTaskNode] = []
    edges: list[WorkflowEdge] = []
    identities: dict[str, ScientificIdentity] = {}
    executions: dict[str, ExecutionSpec] = {}
    output_names: dict[tuple[str, str], str] = {}

    for task in tasks:
        for index, relative in enumerate(
            (*task.required_artifacts, *task.optional_artifacts), start=1
        ):
            output_names[(task.task_id, relative)] = f"artifact_{index:03d}"

    for task in tasks:
        bindings: list[WorkflowInputBinding] = []
        primary_name = "primary"
        ordered_inputs = [task.input_path] + sorted(
            relative for relative in task.input_hashes if relative != task.input_path
        )
        for index, relative in enumerate(ordered_inputs, start=1):
            name = primary_name if relative == task.input_path else f"input_{index:03d}"
            artifact_id = _local_id(
                f"{task.task_id}-input-{index:03d}", fallback=f"input-{index:03d}"
            )
            path = root / relative
            if not path.is_file():
                raise ValueError(f"legacy protected input missing: {relative}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != task.input_hashes[relative]:
                raise ValueError(f"legacy protected input hash mismatch: {relative}")
            external_artifacts.append(
                ArtifactReference(
                    artifact_id=artifact_id,
                    role=ArtifactRole.INPUT,
                    relative_path=relative,
                    sha256=digest,
                    size_bytes=path.stat().st_size,
                    media_type=_media_type(relative),
                    metadata={"legacy_task_id": task.task_id},
                )
            )
            bindings.append(
                WorkflowInputBinding(
                    name=name,
                    destination=task.input_destinations[relative],
                    media_type=_media_type(relative),
                    external_artifact_id=artifact_id,
                )
            )

        transfers_by_parent: dict[str, int] = {}
        for index, transfer in enumerate(task.transfers, start=1):
            name = f"transfer_{index:03d}"
            source_name = output_names[(transfer.from_task, transfer.artifact)]
            bindings.append(
                WorkflowInputBinding(
                    name=name,
                    destination=transfer.destination,
                    media_type=_media_type(transfer.artifact),
                    source_task_id=transfer.from_task,
                    source_output_name=source_name,
                )
            )
            edges.append(
                WorkflowEdge(
                    transfer.from_task,
                    task.task_id,
                    WorkflowEdgeKind.ARTIFACT,
                    source_name,
                    name,
                )
            )
            transfers_by_parent[transfer.from_task] = (
                transfers_by_parent.get(transfer.from_task, 0) + 1
            )
        for dependency in task.depends_on:
            if dependency not in transfers_by_parent:
                edges.append(
                    WorkflowEdge(
                        dependency, task.task_id, WorkflowEdgeKind.CONTROL
                    )
                )

        outputs = tuple(
            WorkflowOutputPort(
                name=output_names[(task.task_id, relative)],
                relative_path=relative,
                artifact_type="qraft.legacy.output",
                media_type=_media_type(relative),
                required=relative in task.required_artifacts,
            )
            for relative in (*task.required_artifacts, *task.optional_artifacts)
        )
        is_command = task.task_kind == "gate"
        settings: dict[str, Any] = {
            "primary_input": primary_name,
            "legacy_task_kind": task.task_kind,
            "declared_outputs": [item.relative_path for item in outputs],
        }
        if is_command:
            settings["command"] = list(task.command)
        else:
            settings["require_scf_converged"] = task.require_scf_converged
        nodes.append(
            WorkflowTaskNode(
                task_id=task.task_id,
                kind=(
                    WorkflowTaskKind.TRANSFORMATION
                    if is_command
                    else WorkflowTaskKind.CALCULATION
                ),
                capability_id=(
                    GENERIC_COMMAND_CAPABILITY
                    if is_command
                    else SIESTA_ENGINE_CAPABILITY
                ),
                dependencies=task.depends_on,
                inputs=tuple(bindings),
                outputs=outputs,
                resources={
                    "max_attempts": task.max_attempts,
                    "estimated_runtime_seconds": task.estimated_runtime_seconds,
                },
                settings=settings,
            )
        )

        primary_digest = task.input_hashes[task.input_path]
        geometry_digest = next(
            (
                digest
                for path, digest in sorted(task.input_hashes.items())
                if Path(path).suffix.casefold() == ".xyz"
            ),
            primary_digest,
        )
        pseudos = {
            path: digest
            for path, digest in sorted(task.input_hashes.items())
            if Path(path).suffix.casefold() in {".psml", ".psf"}
        }
        scientific_inputs = dict(sorted(task.input_hashes.items()))
        protected_content_digest = _digest(sorted(scientific_inputs.values()))
        identities[task.task_id] = ScientificIdentity(
            engine="command" if is_command else "siesta",
            effective_fdf_sha256=primary_digest,
            geometry_sha256=geometry_digest,
            species_mapping_sha256=protected_content_digest,
            pseudopotentials=pseudos,
            components={"protected_scientific_inputs": protected_content_digest},
            included_scientific_files=scientific_inputs,
        )
        requested_nodes = task.nodes if task.nodes > 0 else 1
        execution_nodes = (
            requested_nodes
            if task.mpi_processes % requested_nodes == 0
            else 1
        )
        executions[task.task_id] = ExecutionSpec(
            partition=config.partition,
            nodes=execution_nodes,
            mpi_ranks=task.mpi_processes,
            cpus_per_rank=task.cpus_per_process,
            memory_mb=None,
            launcher="direct" if is_command else config.launcher_kind,
            executable=task.command[0] if is_command else config.siesta_executable,
            walltime_seconds=max(1, int(math.ceil(task.estimated_runtime_seconds))),
            environment=config.environment,
            executable_arguments=(
                task.command[1:] if is_command else config.executable_arguments
            ),
            launcher_command=(() if is_command else config.srun_command),
            launcher_arguments=(() if is_command else config.srun_arguments),
        )

    definition = {
        "campaign_id": config.campaign_id,
        "system_id": config.system_id,
        "tasks": [
            {
                "task_id": task.task_id,
                "inputs": dict(sorted(task.input_hashes.items())),
                "depends_on": list(task.depends_on),
                "kind": task.task_kind,
            }
            for task in tasks
        ],
    }
    workflow = CompiledWorkflow(
        workflow_id=_local_id(config.campaign_id, fallback="legacy-workflow"),
        project_id=_local_id(config.system_id, fallback="legacy-project"),
        definition_sha256=_digest(definition),
        tasks=tuple(nodes),
        edges=tuple(edges),
        external_artifacts=tuple(external_artifacts),
        metadata={
            "source": "allocation-controller-compatibility-translation",
            "legacy_campaign_id": config.campaign_id,
        },
    )
    return CanonicalLegacyPlan(workflow, identities, executions)
