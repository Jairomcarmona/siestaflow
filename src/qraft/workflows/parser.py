"""Strict parser for workflow-definition schema 1.0."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..contracts import (
    FindingScope,
    ValidationFinding,
    WorkflowOutputPort,
    WorkflowTaskKind,
    canonical_primitive,
)
from ..project_packages import load_structured
from .diagnostics import finding
from .models import InputDraft, ParsedWorkflow, TaskDraft


TOP_LEVEL_FIELDS = {
    "schema_version",
    "workflow_id",
    "project_id",
    "description",
    "metadata",
    "tasks",
}
TASK_FIELDS = {
    "task_id",
    "kind",
    "capability",
    "depends_on",
    "inputs",
    "outputs",
    "resources",
    "settings",
}
INPUT_FIELDS = {
    "name",
    "source",
    "from",
    "destination",
    "media_type",
    "sha256",
}
OUTPUT_FIELDS = {
    "name",
    "path",
    "artifact_type",
    "media_type",
    "required",
}
RESOURCE_FIELDS = {
    "nodes",
    "mpi_processes",
    "processes_per_node",
    "cpus_per_process",
    "memory_mb",
    "walltime_seconds",
}


class WorkflowDefinitionParser:
    SUPPORTED_SCHEMA = "1.0"

    def parse(
        self, path: Path
    ) -> tuple[ParsedWorkflow | None, list[ValidationFinding]]:
        source = path.resolve()
        findings: list[ValidationFinding] = []
        try:
            raw_bytes = source.read_bytes()
            data = load_structured(source)
        except (OSError, ValueError) as exc:
            findings.append(
                finding(
                    "WORKFLOW_DOCUMENT_INVALID",
                    f"Cannot load workflow definition: {exc}",
                    location=str(source),
                    hint="Provide a UTF-8 JSON or YAML mapping.",
                )
            )
            return None, findings

        self._unknown_fields(data, TOP_LEVEL_FIELDS, "workflow", findings)
        schema = str(data.get("schema_version", "")).strip()
        if schema != self.SUPPORTED_SCHEMA:
            findings.append(
                finding(
                    "WORKFLOW_SCHEMA_UNSUPPORTED",
                    f"Unsupported workflow schema {schema!r}.",
                    location="schema_version",
                    hint=f"Use schema_version {self.SUPPORTED_SCHEMA}.",
                )
            )
        workflow_id = str(data.get("workflow_id", "")).strip()
        project_id = str(data.get("project_id", "")).strip()
        if not workflow_id:
            findings.append(
                finding(
                    "WORKFLOW_ID_MISSING",
                    "workflow_id is required.",
                    location="workflow_id",
                )
            )
        if not project_id:
            findings.append(
                finding(
                    "PROJECT_ID_MISSING",
                    "project_id is required.",
                    location="project_id",
                )
            )
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            findings.append(
                finding(
                    "WORKFLOW_METADATA_INVALID",
                    "metadata must be a mapping.",
                    location="metadata",
                )
            )
            metadata = {}
        try:
            canonical_primitive(metadata)
        except (TypeError, ValueError) as exc:
            findings.append(
                finding(
                    "WORKFLOW_METADATA_INVALID",
                    f"metadata is not canonically serializable: {exc}",
                    location="metadata",
                )
            )

        tasks_raw = data.get("tasks")
        if not isinstance(tasks_raw, list) or not tasks_raw:
            findings.append(
                finding(
                    "WORKFLOW_TASKS_MISSING",
                    "A workflow requires a non-empty tasks list.",
                    location="tasks",
                )
            )
            return None, findings
        tasks: list[TaskDraft] = []
        seen: set[str] = set()
        for index, raw in enumerate(tasks_raw):
            location = f"tasks[{index}]"
            task = self._parse_task(raw, location, findings)
            if task is None:
                continue
            if task.task_id in seen:
                findings.append(
                    finding(
                        "WORKFLOW_TASK_DUPLICATE",
                        f"Duplicate task_id {task.task_id!r}.",
                        location=f"{location}.task_id",
                    )
                )
                continue
            seen.add(task.task_id)
            tasks.append(task)
        if findings or not tasks:
            return None, findings
        return (
            ParsedWorkflow(
                source=source,
                definition_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                workflow_id=workflow_id,
                project_id=project_id,
                description=str(data.get("description", "")).strip(),
                metadata=dict(metadata),
                tasks=tuple(tasks),
            ),
            findings,
        )

    def _parse_task(
        self,
        raw: Any,
        location: str,
        findings: list[ValidationFinding],
    ) -> TaskDraft | None:
        if not isinstance(raw, Mapping):
            findings.append(
                finding(
                    "WORKFLOW_TASK_INVALID",
                    "Each task must be a mapping.",
                    location=location,
                )
            )
            return None
        self._unknown_fields(raw, TASK_FIELDS, location, findings)
        task_id = str(raw.get("task_id", "")).strip()
        capability = str(raw.get("capability", "")).strip()
        try:
            kind = WorkflowTaskKind(str(raw.get("kind", "")).strip().casefold())
        except ValueError:
            findings.append(
                finding(
                    "WORKFLOW_TASK_KIND_INVALID",
                    f"Unknown task kind {raw.get('kind')!r}.",
                    location=f"{location}.kind",
                    hint="Use a task kind defined by Core Contracts 1.0.",
                )
            )
            return None
        if not task_id or not capability:
            findings.append(
                finding(
                    "WORKFLOW_TASK_IDENTITY_MISSING",
                    "task_id and capability are required.",
                    location=location,
                )
            )
            return None
        dependencies_raw = raw.get("depends_on", [])
        if not isinstance(dependencies_raw, list):
            findings.append(
                finding(
                    "WORKFLOW_DEPENDENCIES_INVALID",
                    "depends_on must be a list.",
                    location=f"{location}.depends_on",
                )
            )
            dependencies_raw = []
        dependencies = tuple(str(item).strip() for item in dependencies_raw)
        if any(not item for item in dependencies) or len(set(dependencies)) != len(
            dependencies
        ):
            findings.append(
                finding(
                    "WORKFLOW_DEPENDENCIES_INVALID",
                    "Dependencies must be non-empty and unique.",
                    location=f"{location}.depends_on",
                )
            )
        inputs_raw = raw.get("inputs", [])
        outputs_raw = raw.get("outputs", [])
        if not isinstance(inputs_raw, list) or not isinstance(outputs_raw, list):
            findings.append(
                finding(
                    "WORKFLOW_PORTS_INVALID",
                    "inputs and outputs must be lists.",
                    location=location,
                )
            )
            return None
        inputs = self._parse_inputs(inputs_raw, location, findings)
        outputs = self._parse_outputs(outputs_raw, location, findings)
        resources = raw.get("resources", {})
        settings = raw.get("settings", {})
        if not isinstance(resources, Mapping):
            findings.append(
                finding(
                    "WORKFLOW_RESOURCES_INVALID",
                    "resources must be a mapping.",
                    location=f"{location}.resources",
                )
            )
            resources = {}
        else:
            self._validate_resources(resources, f"{location}.resources", findings)
        if not isinstance(settings, Mapping):
            findings.append(
                finding(
                    "WORKFLOW_SETTINGS_INVALID",
                    "settings must be a mapping.",
                    location=f"{location}.settings",
                )
            )
            settings = {}
        try:
            canonical_primitive(settings)
            return TaskDraft(
                task_id,
                kind,
                capability,
                dependencies,
                tuple(inputs),
                tuple(outputs),
                dict(resources),
                dict(settings),
            )
        except (TypeError, ValueError) as exc:
            findings.append(
                finding("WORKFLOW_TASK_INVALID", str(exc), location=location)
            )
            return None

    def _parse_inputs(
        self,
        values: list[Any],
        task_location: str,
        findings: list[ValidationFinding],
    ) -> list[InputDraft]:
        result: list[InputDraft] = []
        seen: set[str] = set()
        for index, raw in enumerate(values):
            location = f"{task_location}.inputs[{index}]"
            item = self._parse_input(raw, location, findings)
            if item is None:
                continue
            if item.name in seen:
                findings.append(
                    finding(
                        "WORKFLOW_INPUT_DUPLICATE",
                        f"Duplicate input name {item.name!r}.",
                        location=location,
                    )
                )
            else:
                seen.add(item.name)
                result.append(item)
        return result

    def _parse_input(
        self,
        raw: Any,
        location: str,
        findings: list[ValidationFinding],
    ) -> InputDraft | None:
        if not isinstance(raw, Mapping):
            findings.append(
                finding(
                    "WORKFLOW_INPUT_INVALID",
                    "Each input must be a mapping.",
                    location=location,
                )
            )
            return None
        self._unknown_fields(raw, INPUT_FIELDS, location, findings)
        name = str(raw.get("name", "")).strip()
        source = raw.get("source")
        produced = raw.get("from")
        if not name or (source is None) == (produced is None):
            findings.append(
                finding(
                    "WORKFLOW_INPUT_SOURCE_INVALID",
                    "An input requires a name and exactly one of source or from.",
                    location=location,
                )
            )
            return None
        source_task = source_output = None
        if produced is not None:
            if not isinstance(produced, Mapping) or set(produced) != {
                "task",
                "output",
            }:
                findings.append(
                    finding(
                        "WORKFLOW_INPUT_REFERENCE_INVALID",
                        "from must contain exactly task and output.",
                        location=f"{location}.from",
                    )
                )
                return None
            source_task = str(produced.get("task", "")).strip()
            source_output = str(produced.get("output", "")).strip()
        destination = raw.get("destination")
        media_type = raw.get("media_type")
        declared = raw.get("sha256")
        return InputDraft(
            name=name,
            destination=(
                str(destination).strip() if destination is not None else None
            ),
            media_type=(
                str(media_type).strip() if media_type is not None else None
            ),
            source_path=str(source).strip() if source is not None else None,
            source_task=source_task,
            source_output=source_output,
            declared_sha256=(
                str(declared).strip().lower() if declared is not None else None
            ),
            location=location,
        )

    def _parse_outputs(
        self,
        values: list[Any],
        task_location: str,
        findings: list[ValidationFinding],
    ) -> list[WorkflowOutputPort]:
        result: list[WorkflowOutputPort] = []
        seen: set[str] = set()
        for index, raw in enumerate(values):
            location = f"{task_location}.outputs[{index}]"
            item = self._parse_output(raw, location, findings)
            if item is None:
                continue
            if item.name in seen:
                findings.append(
                    finding(
                        "WORKFLOW_OUTPUT_DUPLICATE",
                        f"Duplicate output name {item.name!r}.",
                        location=location,
                    )
                )
            else:
                seen.add(item.name)
                result.append(item)
        return result

    def _parse_output(
        self,
        raw: Any,
        location: str,
        findings: list[ValidationFinding],
    ) -> WorkflowOutputPort | None:
        if not isinstance(raw, Mapping):
            findings.append(
                finding(
                    "WORKFLOW_OUTPUT_INVALID",
                    "Each output must be a mapping.",
                    location=location,
                )
            )
            return None
        self._unknown_fields(raw, OUTPUT_FIELDS, location, findings)
        required = raw.get("required", True)
        if not isinstance(required, bool):
            findings.append(
                finding(
                    "WORKFLOW_OUTPUT_INVALID",
                    "required must be true or false.",
                    location=f"{location}.required",
                )
            )
            return None
        try:
            return WorkflowOutputPort(
                name=str(raw.get("name", "")).strip(),
                relative_path=str(raw.get("path", "")).strip(),
                artifact_type=str(raw.get("artifact_type", "")).strip(),
                media_type=str(raw.get("media_type", "")).strip(),
                required=required,
            )
        except (TypeError, ValueError) as exc:
            findings.append(
                finding("WORKFLOW_OUTPUT_INVALID", str(exc), location=location)
            )
            return None

    def _validate_resources(
        self,
        resources: Mapping[str, Any],
        location: str,
        findings: list[ValidationFinding],
    ) -> None:
        self._unknown_fields(resources, RESOURCE_FIELDS, location, findings)
        for name, value in resources.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                findings.append(
                    finding(
                        "WORKFLOW_RESOURCE_INVALID",
                        f"Resource {name!r} must be a positive integer.",
                        location=f"{location}.{name}",
                        scope=FindingScope.EXECUTION,
                    )
                )
        nodes = resources.get("nodes")
        ranks = resources.get("mpi_processes")
        ppn = resources.get("processes_per_node")
        if all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (nodes, ranks, ppn)
        ) and int(nodes) * int(ppn) != int(ranks):
            findings.append(
                finding(
                    "WORKFLOW_RESOURCE_PLACEMENT_MISMATCH",
                    "mpi_processes must equal nodes × processes_per_node.",
                    location=location,
                    scope=FindingScope.EXECUTION,
                )
            )

    @staticmethod
    def _unknown_fields(
        raw: Mapping[str, Any],
        allowed: set[str],
        location: str,
        findings: list[ValidationFinding],
    ) -> None:
        for field in sorted(set(raw) - allowed):
            findings.append(
                finding(
                    "WORKFLOW_FIELD_UNKNOWN",
                    f"Unknown field {field!r}.",
                    location=f"{location}.{field}",
                    hint="Remove the field or use a supported schema version.",
                )
            )
