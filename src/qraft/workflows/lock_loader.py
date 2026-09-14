"""Strict reconstruction of a compiled workflow from its integrity envelope."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..contracts import (
    RUN_LOCK,
    WORKFLOW_LOCK,
    ArtifactReference,
    ArtifactRole,
    CompiledWorkflow,
    ContractEnvelope,
    PreparedRun,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowInputBinding,
    WorkflowOutputPort,
    WorkflowTaskKind,
    WorkflowTaskNode,
    canonical_primitive,
)


_WORKFLOW_FIELDS = {
    "schema_version",
    "workflow_id",
    "project_id",
    "definition_sha256",
    "tasks",
    "edges",
    "external_artifacts",
    "metadata",
}
_TASK_FIELDS = {
    "task_id",
    "kind",
    "capability_id",
    "dependencies",
    "inputs",
    "outputs",
    "resources",
    "settings",
}
_INPUT_FIELDS = {
    "name",
    "destination",
    "media_type",
    "external_artifact_id",
    "source_task_id",
    "source_output_name",
}
_OUTPUT_FIELDS = {
    "name",
    "relative_path",
    "artifact_type",
    "media_type",
    "required",
}
_EDGE_FIELDS = {
    "source_task_id",
    "target_task_id",
    "kind",
    "source_output_name",
    "target_input_name",
}
_ARTIFACT_FIELDS = {
    "artifact_id",
    "role",
    "relative_path",
    "sha256",
    "size_bytes",
    "media_type",
    "producer_task_id",
    "producer_attempt_id",
    "metadata",
}
_RUN_FIELDS = {
    "schema_version",
    "run_id",
    "workflow_id",
    "project_id",
    "workflow_lock_sha256",
    "execution_profile_id",
    "execution_profile_sha256",
    "controller_campaign_sha256",
    "task_ids",
    "target",
    "metadata",
    "execution_authorized",
    "submission_performed",
}


def load_workflow_lock(
    path: Path,
) -> tuple[ContractEnvelope, CompiledWorkflow]:
    envelope = _load_envelope(path, WORKFLOW_LOCK)
    payload = canonical_primitive(envelope.payload)
    if not isinstance(payload, Mapping):
        raise ValueError("workflow lock payload must be a mapping")
    _exact_fields(payload, _WORKFLOW_FIELDS, "workflow lock")
    if payload["schema_version"] != "1.0":
        raise ValueError("unsupported workflow lock payload schema")
    tasks = tuple(
        _task(item, index)
        for index, item in enumerate(_list(payload["tasks"], "tasks"))
    )
    edges = tuple(
        _edge(item, index)
        for index, item in enumerate(_list(payload["edges"], "edges"))
    )
    artifacts = tuple(
        _artifact(item, index)
        for index, item in enumerate(
            _list(payload["external_artifacts"], "external_artifacts")
        )
    )
    metadata = _mapping(payload["metadata"], "metadata")
    workflow = CompiledWorkflow(
        workflow_id=str(payload["workflow_id"]),
        project_id=str(payload["project_id"]),
        definition_sha256=str(payload["definition_sha256"]),
        tasks=tasks,
        edges=edges,
        external_artifacts=artifacts,
        metadata=dict(metadata),
    )
    if workflow.payload() != payload:
        raise ValueError(
            "workflow lock payload is not canonical for Core Contracts 1.0"
        )
    return envelope, workflow


def load_run_lock(path: Path) -> tuple[ContractEnvelope, PreparedRun]:
    envelope = _load_envelope(path, RUN_LOCK)
    payload = canonical_primitive(envelope.payload)
    if not isinstance(payload, Mapping):
        raise ValueError("run lock payload must be a mapping")
    _exact_fields(payload, _RUN_FIELDS, "run lock")
    if payload["schema_version"] != "1.0":
        raise ValueError("unsupported run lock payload schema")
    run = PreparedRun(
        run_id=str(payload["run_id"]),
        workflow_id=str(payload["workflow_id"]),
        project_id=str(payload["project_id"]),
        workflow_lock_sha256=str(payload["workflow_lock_sha256"]),
        execution_profile_id=str(payload["execution_profile_id"]),
        execution_profile_sha256=str(payload["execution_profile_sha256"]),
        controller_campaign_sha256=str(
            payload["controller_campaign_sha256"]
        ),
        task_ids=tuple(str(item) for item in _list(payload["task_ids"], "task_ids")),
        target=str(payload["target"]),
        metadata=dict(_mapping(payload["metadata"], "metadata")),
        execution_authorized=_boolean(
            payload["execution_authorized"], "execution_authorized"
        ),
        submission_performed=_boolean(
            payload["submission_performed"], "submission_performed"
        ),
    )
    if run.payload() != payload:
        raise ValueError(
            "run lock payload is not canonical for Core Contracts 1.0"
        )
    return envelope, run


def _load_envelope(path: Path, contract) -> ContractEnvelope:
    resolved = path.expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load contract envelope {resolved}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"contract envelope must be a mapping: {resolved}")
    return ContractEnvelope.from_dict(value, required_contract=contract)


def _task(value: Any, index: int) -> WorkflowTaskNode:
    raw = _mapping(value, f"tasks[{index}]")
    _exact_fields(raw, _TASK_FIELDS, f"tasks[{index}]")
    return WorkflowTaskNode(
        task_id=str(raw["task_id"]),
        kind=WorkflowTaskKind(str(raw["kind"])),
        capability_id=str(raw["capability_id"]),
        dependencies=tuple(
            str(item)
            for item in _list(
                raw["dependencies"], f"tasks[{index}].dependencies"
            )
        ),
        inputs=tuple(
            _input(item, index, item_index)
            for item_index, item in enumerate(
                _list(raw["inputs"], f"tasks[{index}].inputs")
            )
        ),
        outputs=tuple(
            _output(item, index, item_index)
            for item_index, item in enumerate(
                _list(raw["outputs"], f"tasks[{index}].outputs")
            )
        ),
        resources=dict(
            _mapping(raw["resources"], f"tasks[{index}].resources")
        ),
        settings=dict(_mapping(raw["settings"], f"tasks[{index}].settings")),
    )


def _input(value: Any, task_index: int, index: int) -> WorkflowInputBinding:
    location = f"tasks[{task_index}].inputs[{index}]"
    raw = _mapping(value, location)
    _exact_fields(raw, _INPUT_FIELDS, location)
    return WorkflowInputBinding(
        name=str(raw["name"]),
        destination=str(raw["destination"]),
        media_type=str(raw["media_type"]),
        external_artifact_id=_optional_text(raw["external_artifact_id"]),
        source_task_id=_optional_text(raw["source_task_id"]),
        source_output_name=_optional_text(raw["source_output_name"]),
    )


def _output(value: Any, task_index: int, index: int) -> WorkflowOutputPort:
    location = f"tasks[{task_index}].outputs[{index}]"
    raw = _mapping(value, location)
    _exact_fields(raw, _OUTPUT_FIELDS, location)
    return WorkflowOutputPort(
        name=str(raw["name"]),
        relative_path=str(raw["relative_path"]),
        artifact_type=str(raw["artifact_type"]),
        media_type=str(raw["media_type"]),
        required=_boolean(raw["required"], f"{location}.required"),
    )


def _edge(value: Any, index: int) -> WorkflowEdge:
    location = f"edges[{index}]"
    raw = _mapping(value, location)
    _exact_fields(raw, _EDGE_FIELDS, location)
    return WorkflowEdge(
        source_task_id=str(raw["source_task_id"]),
        target_task_id=str(raw["target_task_id"]),
        kind=WorkflowEdgeKind(str(raw["kind"])),
        source_output_name=_optional_text(raw["source_output_name"]),
        target_input_name=_optional_text(raw["target_input_name"]),
    )


def _artifact(value: Any, index: int) -> ArtifactReference:
    location = f"external_artifacts[{index}]"
    raw = _mapping(value, location)
    _exact_fields(raw, _ARTIFACT_FIELDS, location)
    size = raw["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int):
        raise ValueError(f"{location}.size_bytes must be an integer")
    return ArtifactReference(
        artifact_id=str(raw["artifact_id"]),
        role=ArtifactRole(str(raw["role"])),
        relative_path=str(raw["relative_path"]),
        sha256=str(raw["sha256"]),
        size_bytes=size,
        media_type=str(raw["media_type"]),
        producer_task_id=_optional_text(raw["producer_task_id"]),
        producer_attempt_id=_optional_text(raw["producer_attempt_id"]),
        metadata=dict(_mapping(raw["metadata"], f"{location}.metadata")),
    )


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{location} must be a mapping")
    return value


def _list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{location} must be a list")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    location: str,
) -> None:
    if set(value) != expected:
        difference = sorted(set(value) ^ expected)
        raise ValueError(f"{location} fields mismatch: {difference}")


def _boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{location} must be boolean")
    return value


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)
