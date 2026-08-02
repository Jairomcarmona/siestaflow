"""Engine-neutral contracts for a resolved scientific workflow DAG."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .artifacts import ArtifactReference, require_relative_artifact_path
from .catalog import WORKFLOW_LOCK
from .serialization import ContractEnvelope, canonical_primitive
from .versioning import require_namespaced_identifier
_LOCAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def require_local_id(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not _LOCAL_ID.fullmatch(normalized):
        raise ValueError(f"{field_name} is not a valid local identifier: {value!r}")
    return normalized


class WorkflowTaskKind(str, Enum):
    CALCULATION = "calculation"
    TRANSFORMATION = "transformation"
    VALIDATION = "validation"
    SWEEP = "sweep"
    SELECTION = "selection"
    CHECKPOINT = "checkpoint"
    POSTPROCESS = "postprocess"
    COMPARISON = "comparison"
    EXPORT = "export"
    EXTERNAL = "external"


class WorkflowEdgeKind(str, Enum):
    CONTROL = "control"
    ARTIFACT = "artifact"


@dataclass(frozen=True)
class WorkflowInputBinding:
    name: str
    destination: str
    media_type: str
    external_artifact_id: str | None = None
    source_task_id: str | None = None
    source_output_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_local_id(self.name, field_name="input name"))
        object.__setattr__(
            self,
            "destination",
            require_relative_artifact_path(
                self.destination, field_name="input destination"
            ),
        )
        if not self.media_type.strip():
            raise ValueError("workflow inputs require media_type")
        external = self.external_artifact_id is not None
        produced = (
            self.source_task_id is not None
            or self.source_output_name is not None
        )
        if external == produced:
            raise ValueError(
                "workflow inputs require exactly one external or produced source"
            )
        if external:
            object.__setattr__(
                self,
                "external_artifact_id",
                require_local_id(
                    str(self.external_artifact_id),
                    field_name="external artifact id",
                ),
            )
        else:
            object.__setattr__(
                self,
                "source_task_id",
                require_local_id(
                    str(self.source_task_id), field_name="source task id"
                ),
            )
            object.__setattr__(
                self,
                "source_output_name",
                require_local_id(
                    str(self.source_output_name), field_name="source output name"
                ),
            )


@dataclass(frozen=True)
class WorkflowOutputPort:
    name: str
    relative_path: str
    artifact_type: str
    media_type: str
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", require_local_id(self.name, field_name="output name")
        )
        object.__setattr__(
            self,
            "relative_path",
            require_relative_artifact_path(
                self.relative_path, field_name="output path"
            ),
        )
        object.__setattr__(
            self,
            "artifact_type",
            require_namespaced_identifier(
                self.artifact_type, field="artifact type"
            ),
        )
        if not self.media_type.strip():
            raise ValueError("workflow outputs require media_type")


@dataclass(frozen=True)
class WorkflowEdge:
    source_task_id: str
    target_task_id: str
    kind: WorkflowEdgeKind
    source_output_name: str | None = None
    target_input_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_task_id",
            require_local_id(self.source_task_id, field_name="edge source"),
        )
        object.__setattr__(
            self,
            "target_task_id",
            require_local_id(self.target_task_id, field_name="edge target"),
        )
        if self.source_task_id == self.target_task_id:
            raise ValueError("workflow edges cannot be self-referential")
        artifact_fields = (
            self.source_output_name is not None,
            self.target_input_name is not None,
        )
        if self.kind is WorkflowEdgeKind.ARTIFACT and not all(artifact_fields):
            raise ValueError("artifact edges require source output and target input")
        if self.kind is WorkflowEdgeKind.CONTROL and any(artifact_fields):
            raise ValueError("control edges cannot declare artifact ports")
        if self.source_output_name is not None:
            object.__setattr__(
                self,
                "source_output_name",
                require_local_id(
                    self.source_output_name, field_name="edge source output"
                ),
            )
        if self.target_input_name is not None:
            object.__setattr__(
                self,
                "target_input_name",
                require_local_id(
                    self.target_input_name, field_name="edge target input"
                ),
            )


@dataclass(frozen=True)
class WorkflowTaskNode:
    task_id: str
    kind: WorkflowTaskKind
    capability_id: str
    dependencies: tuple[str, ...]
    inputs: tuple[WorkflowInputBinding, ...]
    outputs: tuple[WorkflowOutputPort, ...]
    resources: Mapping[str, Any] = field(default_factory=dict)
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "task_id", require_local_id(self.task_id, field_name="task id")
        )
        object.__setattr__(
            self,
            "capability_id",
            require_namespaced_identifier(
                self.capability_id, field="capability id"
            ),
        )
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError(f"duplicate dependencies in task {self.task_id}")
        for dependency in self.dependencies:
            require_local_id(dependency, field_name="task dependency")
            if dependency == self.task_id:
                raise ValueError(f"task {self.task_id} cannot depend on itself")
        if len({item.name for item in self.inputs}) != len(self.inputs):
            raise ValueError(f"duplicate input names in task {self.task_id}")
        if len({item.destination for item in self.inputs}) != len(self.inputs):
            raise ValueError(f"duplicate input destinations in task {self.task_id}")
        if len({item.name for item in self.outputs}) != len(self.outputs):
            raise ValueError(f"duplicate output names in task {self.task_id}")
        if len({item.relative_path for item in self.outputs}) != len(self.outputs):
            raise ValueError(f"duplicate output paths in task {self.task_id}")
        canonical_primitive(self.resources)
        canonical_primitive(self.settings)


@dataclass(frozen=True)
class CompiledWorkflow:
    workflow_id: str
    project_id: str
    definition_sha256: str
    tasks: tuple[WorkflowTaskNode, ...]
    edges: tuple[WorkflowEdge, ...]
    external_artifacts: tuple[ArtifactReference, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workflow_id",
            require_local_id(self.workflow_id, field_name="workflow id"),
        )
        object.__setattr__(
            self,
            "project_id",
            require_local_id(self.project_id, field_name="project id"),
        )
        if len(self.definition_sha256) != 64:
            raise ValueError("definition_sha256 must contain 64 hexadecimal characters")
        int(self.definition_sha256, 16)
        identifiers = [task.task_id for task in self.tasks]
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("compiled workflows require unique tasks")
        if len({item.artifact_id for item in self.external_artifacts}) != len(
            self.external_artifacts
        ):
            raise ValueError("external artifact ids must be unique")
        positions = {task.task_id: index for index, task in enumerate(self.tasks)}
        by_task = {task.task_id: task for task in self.tasks}
        external_ids = {item.artifact_id for item in self.external_artifacts}
        used_external_ids: set[str] = set()
        if len(set(self.edges)) != len(self.edges):
            raise ValueError("compiled workflow edges must be unique")
        incoming: dict[str, set[str]] = {task_id: set() for task_id in identifiers}
        for edge in self.edges:
            if (
                edge.source_task_id not in by_task
                or edge.target_task_id not in by_task
            ):
                raise ValueError("workflow edge references an unknown task")
            if positions[edge.source_task_id] >= positions[edge.target_task_id]:
                raise ValueError("compiled workflow tasks are not topologically ordered")
            incoming[edge.target_task_id].add(edge.source_task_id)
            if edge.kind is WorkflowEdgeKind.ARTIFACT:
                source = by_task[edge.source_task_id]
                target = by_task[edge.target_task_id]
                source_outputs = {item.name: item for item in source.outputs}
                target_inputs = {item.name: item for item in target.inputs}
                output = source_outputs.get(str(edge.source_output_name))
                binding = target_inputs.get(str(edge.target_input_name))
                if output is None or binding is None:
                    raise ValueError("artifact edge references an unknown task port")
                if (
                    binding.source_task_id != edge.source_task_id
                    or binding.source_output_name != edge.source_output_name
                ):
                    raise ValueError("artifact edge disagrees with its input binding")
                if binding.media_type != output.media_type:
                    raise ValueError("artifact edge media types are incompatible")
        for task in self.tasks:
            if set(task.dependencies) != incoming[task.task_id]:
                raise ValueError(
                    f"task dependencies disagree with graph edges: {task.task_id}"
                )
            for binding in task.inputs:
                if binding.external_artifact_id is not None:
                    if binding.external_artifact_id not in external_ids:
                        raise ValueError(
                            f"input references unknown external artifact: "
                            f"{binding.external_artifact_id}"
                        )
                    used_external_ids.add(binding.external_artifact_id)
        if used_external_ids != external_ids:
            raise ValueError("compiled workflow contains unused external artifacts")
        canonical_primitive(self.metadata)

    def payload(self) -> dict[str, Any]:
        return canonical_primitive(
            {
                "schema_version": "1.0",
                "workflow_id": self.workflow_id,
                "project_id": self.project_id,
                "definition_sha256": self.definition_sha256,
                "tasks": self.tasks,
                "edges": self.edges,
                "external_artifacts": self.external_artifacts,
                "metadata": self.metadata,
            }
        )

    def envelope(self, *, producer: str = "siestaflow.workflow-compiler") -> ContractEnvelope:
        return ContractEnvelope.create(
            WORKFLOW_LOCK,
            producer=producer,
            payload=self.payload(),
        )
