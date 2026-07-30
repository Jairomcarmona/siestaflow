"""Deterministic compiler for declarative, engine-neutral workflow DAGs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..contracts import (
    ArtifactReference,
    ArtifactRole,
    CompiledWorkflow,
    DecisionStatus,
    EvidenceClass,
    FindingScope,
    ValidationFinding,
    ValidationReport,
    ValidationSubject,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowInputBinding,
    WorkflowOutputPort,
    WorkflowTaskKind,
    WorkflowTaskNode,
    canonical_primitive,
    contract_sha256,
)
from ..contracts.artifacts import require_relative_artifact_path
from ..project_packages import load_structured


_TOP_LEVEL_FIELDS = {
    "schema_version",
    "workflow_id",
    "project_id",
    "description",
    "metadata",
    "tasks",
}
_TASK_FIELDS = {
    "task_id",
    "kind",
    "capability",
    "depends_on",
    "inputs",
    "outputs",
    "resources",
    "settings",
}
_INPUT_FIELDS = {
    "name",
    "source",
    "from",
    "destination",
    "media_type",
    "sha256",
}
_OUTPUT_FIELDS = {
    "name",
    "path",
    "artifact_type",
    "media_type",
    "required",
}
_RESOURCE_FIELDS = {
    "nodes",
    "mpi_processes",
    "processes_per_node",
    "cpus_per_process",
    "memory_mb",
    "walltime_seconds",
}
_RULESET = (
    "siestaflow.workflow.schema@1.0",
    "siestaflow.workflow.graph@1.0",
    "siestaflow.workflow.artifacts@1.0",
    "siestaflow.workflow.resources@1.0",
)


@dataclass(frozen=True)
class WorkflowCompilation:
    report: ValidationReport
    compiled: CompiledWorkflow | None

    @property
    def valid(self) -> bool:
        return (
            self.compiled is not None
            and self.report.status is DecisionStatus.PASS
        )

    def lock_dict(self) -> dict[str, Any]:
        if not self.valid or self.compiled is None:
            raise ValueError("cannot create a workflow lock from invalid input")
        return self.compiled.envelope().to_dict()


@dataclass
class _InputDraft:
    name: str
    destination: str | None
    media_type: str | None
    source_path: str | None
    source_task: str | None
    source_output: str | None
    declared_sha256: str | None
    location: str


@dataclass
class _TaskDraft:
    task_id: str
    kind: WorkflowTaskKind
    capability: str
    dependencies: tuple[str, ...]
    inputs: list[_InputDraft]
    outputs: tuple[WorkflowOutputPort, ...]
    resources: Mapping[str, Any]
    settings: Mapping[str, Any]


class WorkflowCompiler:
    """Validate and resolve a workflow definition without executing it."""

    SUPPORTED_SCHEMA = "1.0"

    def compile(self, path: Path) -> WorkflowCompilation:
        source = path.resolve()
        findings: list[ValidationFinding] = []
        try:
            raw_bytes = source.read_bytes()
            data = load_structured(source)
        except (OSError, ValueError) as exc:
            return self._result(
                source,
                None,
                [
                    self._finding(
                        "WORKFLOW_DOCUMENT_INVALID",
                        f"Cannot load workflow definition: {exc}",
                        location=str(source),
                        hint="Provide a UTF-8 JSON or YAML mapping.",
                    )
                ],
            )

        self._unknown_fields(data, _TOP_LEVEL_FIELDS, "workflow", findings)
        schema = str(data.get("schema_version", "")).strip()
        if schema != self.SUPPORTED_SCHEMA:
            findings.append(
                self._finding(
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
                self._finding(
                    "WORKFLOW_ID_MISSING",
                    "workflow_id is required.",
                    location="workflow_id",
                )
            )
        if not project_id:
            findings.append(
                self._finding(
                    "PROJECT_ID_MISSING",
                    "project_id is required.",
                    location="project_id",
                )
            )
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            findings.append(
                self._finding(
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
                self._finding(
                    "WORKFLOW_METADATA_INVALID",
                    f"metadata is not canonically serializable: {exc}",
                    location="metadata",
                )
            )

        tasks_raw = data.get("tasks")
        if not isinstance(tasks_raw, list) or not tasks_raw:
            findings.append(
                self._finding(
                    "WORKFLOW_TASKS_MISSING",
                    "A workflow requires a non-empty tasks list.",
                    location="tasks",
                )
            )
            return self._result(source, workflow_id or None, findings)

        drafts: list[_TaskDraft] = []
        seen_tasks: set[str] = set()
        for index, task_raw in enumerate(tasks_raw):
            location = f"tasks[{index}]"
            draft = self._parse_task(task_raw, location, findings)
            if draft is None:
                continue
            if draft.task_id in seen_tasks:
                findings.append(
                    self._finding(
                        "WORKFLOW_TASK_DUPLICATE",
                        f"Duplicate task_id {draft.task_id!r}.",
                        location=f"{location}.task_id",
                    )
                )
                continue
            seen_tasks.add(draft.task_id)
            drafts.append(draft)

        if findings or not drafts:
            return self._result(source, workflow_id or None, findings)

        compiled = self._resolve(
            source=source,
            definition_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            workflow_id=workflow_id,
            project_id=project_id,
            description=str(data.get("description", "")).strip(),
            metadata=metadata,
            drafts=drafts,
            findings=findings,
        )
        return self._result(source, workflow_id, findings, compiled)

    def _parse_task(
        self,
        raw: Any,
        location: str,
        findings: list[ValidationFinding],
    ) -> _TaskDraft | None:
        if not isinstance(raw, Mapping):
            findings.append(
                self._finding(
                    "WORKFLOW_TASK_INVALID",
                    "Each task must be a mapping.",
                    location=location,
                )
            )
            return None
        self._unknown_fields(raw, _TASK_FIELDS, location, findings)
        task_id = str(raw.get("task_id", "")).strip()
        capability = str(raw.get("capability", "")).strip()
        try:
            kind = WorkflowTaskKind(str(raw.get("kind", "")).strip().casefold())
        except ValueError:
            findings.append(
                self._finding(
                    "WORKFLOW_TASK_KIND_INVALID",
                    f"Unknown task kind {raw.get('kind')!r}.",
                    location=f"{location}.kind",
                    hint="Use one of the task kinds defined by Core Contracts 1.0.",
                )
            )
            return None
        if not task_id or not capability:
            findings.append(
                self._finding(
                    "WORKFLOW_TASK_IDENTITY_MISSING",
                    "task_id and capability are required.",
                    location=location,
                )
            )
            return None
        dependencies_raw = raw.get("depends_on", [])
        if not isinstance(dependencies_raw, list):
            findings.append(
                self._finding(
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
                self._finding(
                    "WORKFLOW_DEPENDENCIES_INVALID",
                    "Dependencies must be non-empty and unique.",
                    location=f"{location}.depends_on",
                )
            )

        inputs_raw = raw.get("inputs", [])
        outputs_raw = raw.get("outputs", [])
        if not isinstance(inputs_raw, list) or not isinstance(outputs_raw, list):
            findings.append(
                self._finding(
                    "WORKFLOW_PORTS_INVALID",
                    "inputs and outputs must be lists.",
                    location=location,
                )
            )
            return None
        inputs: list[_InputDraft] = []
        seen_inputs: set[str] = set()
        for input_index, input_raw in enumerate(inputs_raw):
            item_location = f"{location}.inputs[{input_index}]"
            item = self._parse_input(input_raw, item_location, findings)
            if item is None:
                continue
            if item.name in seen_inputs:
                findings.append(
                    self._finding(
                        "WORKFLOW_INPUT_DUPLICATE",
                        f"Duplicate input name {item.name!r}.",
                        location=item_location,
                    )
                )
            else:
                seen_inputs.add(item.name)
                inputs.append(item)

        outputs: list[WorkflowOutputPort] = []
        seen_outputs: set[str] = set()
        for output_index, output_raw in enumerate(outputs_raw):
            item_location = f"{location}.outputs[{output_index}]"
            item = self._parse_output(output_raw, item_location, findings)
            if item is None:
                continue
            if item.name in seen_outputs:
                findings.append(
                    self._finding(
                        "WORKFLOW_OUTPUT_DUPLICATE",
                        f"Duplicate output name {item.name!r}.",
                        location=item_location,
                    )
                )
            else:
                seen_outputs.add(item.name)
                outputs.append(item)

        resources = raw.get("resources", {})
        settings = raw.get("settings", {})
        if not isinstance(resources, Mapping):
            findings.append(
                self._finding(
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
                self._finding(
                    "WORKFLOW_SETTINGS_INVALID",
                    "settings must be a mapping.",
                    location=f"{location}.settings",
                )
            )
            settings = {}
        try:
            return _TaskDraft(
                task_id,
                kind,
                capability,
                dependencies,
                inputs,
                tuple(outputs),
                dict(resources),
                dict(settings),
            )
        except (TypeError, ValueError) as exc:
            findings.append(
                self._finding(
                    "WORKFLOW_TASK_INVALID",
                    str(exc),
                    location=location,
                )
            )
            return None

    def _parse_input(
        self,
        raw: Any,
        location: str,
        findings: list[ValidationFinding],
    ) -> _InputDraft | None:
        if not isinstance(raw, Mapping):
            findings.append(
                self._finding(
                    "WORKFLOW_INPUT_INVALID",
                    "Each input must be a mapping.",
                    location=location,
                )
            )
            return None
        self._unknown_fields(raw, _INPUT_FIELDS, location, findings)
        name = str(raw.get("name", "")).strip()
        source = raw.get("source")
        produced = raw.get("from")
        if not name or (source is None) == (produced is None):
            findings.append(
                self._finding(
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
                    self._finding(
                        "WORKFLOW_INPUT_REFERENCE_INVALID",
                        "from must contain exactly task and output.",
                        location=f"{location}.from",
                    )
                )
                return None
            source_task = str(produced.get("task", "")).strip()
            source_output = str(produced.get("output", "")).strip()
        destination = raw.get("destination")
        declared = raw.get("sha256")
        return _InputDraft(
            name=name,
            destination=(
                str(destination).strip() if destination is not None else None
            ),
            media_type=(
                str(raw.get("media_type")).strip()
                if raw.get("media_type") is not None
                else None
            ),
            source_path=str(source).strip() if source is not None else None,
            source_task=source_task,
            source_output=source_output,
            declared_sha256=(
                str(declared).strip().lower() if declared is not None else None
            ),
            location=location,
        )

    def _parse_output(
        self,
        raw: Any,
        location: str,
        findings: list[ValidationFinding],
    ) -> WorkflowOutputPort | None:
        if not isinstance(raw, Mapping):
            findings.append(
                self._finding(
                    "WORKFLOW_OUTPUT_INVALID",
                    "Each output must be a mapping.",
                    location=location,
                )
            )
            return None
        self._unknown_fields(raw, _OUTPUT_FIELDS, location, findings)
        required = raw.get("required", True)
        if not isinstance(required, bool):
            findings.append(
                self._finding(
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
                self._finding(
                    "WORKFLOW_OUTPUT_INVALID",
                    str(exc),
                    location=location,
                )
            )
            return None

    def _resolve(
        self,
        *,
        source: Path,
        definition_sha256: str,
        workflow_id: str,
        project_id: str,
        description: str,
        metadata: Mapping[str, Any],
        drafts: list[_TaskDraft],
        findings: list[ValidationFinding],
    ) -> CompiledWorkflow | None:
        by_id = {task.task_id: task for task in drafts}
        outputs = {
            (task.task_id, output.name): output
            for task in drafts
            for output in task.outputs
        }
        dependencies: dict[str, set[str]] = {
            task.task_id: set(task.dependencies) for task in drafts
        }
        external: dict[str, ArtifactReference] = {}
        bindings: dict[str, list[WorkflowInputBinding]] = {
            task.task_id: [] for task in drafts
        }
        edges: list[WorkflowEdge] = []

        for task in drafts:
            for dependency in task.dependencies:
                if dependency not in by_id:
                    findings.append(
                        self._finding(
                            "WORKFLOW_DEPENDENCY_UNKNOWN",
                            f"Task {task.task_id!r} depends on unknown task {dependency!r}.",
                            location=f"tasks.{task.task_id}.depends_on",
                        )
                    )
                elif dependency == task.task_id:
                    findings.append(
                        self._finding(
                            "WORKFLOW_SELF_DEPENDENCY",
                            f"Task {task.task_id!r} depends on itself.",
                            location=f"tasks.{task.task_id}.depends_on",
                        )
                    )
                else:
                    edges.append(
                        WorkflowEdge(
                            dependency,
                            task.task_id,
                            WorkflowEdgeKind.CONTROL,
                        )
                    )
            for item in task.inputs:
                if item.source_path is not None:
                    binding = self._resolve_external_input(
                        source.parent, task.task_id, item, external, findings
                    )
                else:
                    key = (str(item.source_task), str(item.source_output))
                    output = outputs.get(key)
                    if item.source_task not in by_id:
                        findings.append(
                            self._finding(
                                "WORKFLOW_INPUT_TASK_UNKNOWN",
                                f"Input {item.name!r} references unknown task "
                                f"{item.source_task!r}.",
                                location=item.location,
                            )
                        )
                        continue
                    if output is None:
                        findings.append(
                            self._finding(
                                "WORKFLOW_INPUT_OUTPUT_UNKNOWN",
                                f"Input {item.name!r} references unknown output "
                                f"{item.source_task}.{item.source_output}.",
                                location=item.location,
                            )
                        )
                        continue
                    dependencies[task.task_id].add(str(item.source_task))
                    destination = item.destination or PurePosixPath(
                        output.relative_path
                    ).name
                    try:
                        binding = WorkflowInputBinding(
                            name=item.name,
                            destination=destination,
                            media_type=item.media_type or output.media_type,
                            source_task_id=item.source_task,
                            source_output_name=item.source_output,
                        )
                        edges.append(
                            WorkflowEdge(
                                str(item.source_task),
                                task.task_id,
                                WorkflowEdgeKind.ARTIFACT,
                                str(item.source_output),
                                item.name,
                            )
                        )
                    except ValueError as exc:
                        findings.append(
                            self._finding(
                                "WORKFLOW_INPUT_INVALID",
                                str(exc),
                                location=item.location,
                            )
                        )
                        continue
                if binding is not None:
                    bindings[task.task_id].append(binding)

        order = self._topological_order(dependencies, findings)
        if findings or order is None:
            return None
        nodes: list[WorkflowTaskNode] = []
        for task_id in order:
            task = by_id[task_id]
            try:
                nodes.append(
                    WorkflowTaskNode(
                        task_id=task.task_id,
                        kind=task.kind,
                        capability_id=task.capability,
                        dependencies=tuple(sorted(dependencies[task_id])),
                        inputs=tuple(sorted(bindings[task_id], key=lambda item: item.name)),
                        outputs=tuple(sorted(task.outputs, key=lambda item: item.name)),
                        resources=dict(task.resources),
                        settings=dict(task.settings),
                    )
                )
            except (TypeError, ValueError) as exc:
                findings.append(
                    self._finding(
                        "WORKFLOW_TASK_INVALID",
                        str(exc),
                        location=f"tasks.{task_id}",
                    )
                )
        if findings:
            return None
        lock_metadata = dict(metadata)
        if description:
            lock_metadata["description"] = description
        return CompiledWorkflow(
            workflow_id=workflow_id,
            project_id=project_id,
            definition_sha256=definition_sha256,
            tasks=tuple(nodes),
            edges=tuple(
                sorted(
                    set(edges),
                    key=lambda item: (
                        item.source_task_id,
                        item.target_task_id,
                        item.kind.value,
                        item.source_output_name or "",
                        item.target_input_name or "",
                    ),
                )
            ),
            external_artifacts=tuple(
                sorted(external.values(), key=lambda item: item.artifact_id)
            ),
            metadata=lock_metadata,
        )

    def _resolve_external_input(
        self,
        root: Path,
        task_id: str,
        item: _InputDraft,
        external: dict[str, ArtifactReference],
        findings: list[ValidationFinding],
    ) -> WorkflowInputBinding | None:
        try:
            relative = require_relative_artifact_path(
                str(item.source_path), field_name="external input source"
            )
            candidate = (root / Path(*PurePosixPath(relative).parts)).resolve()
            if not candidate.is_relative_to(root.resolve()):
                raise ValueError("external input resolves outside workflow directory")
            if not candidate.is_file():
                raise ValueError(f"external input does not exist: {relative}")
            digest = self._sha_file(candidate)
            if item.declared_sha256 is not None:
                if (
                    len(item.declared_sha256) != 64
                    or any(
                        char not in "0123456789abcdef"
                        for char in item.declared_sha256
                    )
                ):
                    raise ValueError(f"invalid declared SHA-256 for {relative}")
                if item.declared_sha256 != digest:
                    raise ValueError(f"declared SHA-256 mismatch for {relative}")
            artifact_id = "input-" + contract_sha256({"path": relative})[:16]
            media_type = item.media_type or "application/octet-stream"
            existing = external.get(artifact_id)
            reference = ArtifactReference(
                artifact_id=artifact_id,
                role=ArtifactRole.INPUT,
                relative_path=relative,
                sha256=digest,
                size_bytes=candidate.stat().st_size,
                media_type=media_type,
            )
            if existing is not None and existing != reference:
                raise ValueError(f"external artifact identity collision: {relative}")
            external[artifact_id] = reference
            return WorkflowInputBinding(
                name=item.name,
                destination=item.destination or PurePosixPath(relative).name,
                media_type=media_type,
                external_artifact_id=artifact_id,
            )
        except (OSError, TypeError, ValueError) as exc:
            findings.append(
                self._finding(
                    "WORKFLOW_EXTERNAL_INPUT_INVALID",
                    str(exc),
                    location=item.location,
                    hint="Use a relative path inside the workflow directory.",
                    scope=FindingScope.PROVENANCE,
                )
            )
            return None

    def _topological_order(
        self,
        dependencies: Mapping[str, set[str]],
        findings: list[ValidationFinding],
    ) -> tuple[str, ...] | None:
        if any(
            dependency not in dependencies
            for values in dependencies.values()
            for dependency in values
        ):
            return None
        remaining = {key: set(value) for key, value in dependencies.items()}
        order: list[str] = []
        while remaining:
            ready = sorted(key for key, value in remaining.items() if not value)
            if not ready:
                cycle_nodes = sorted(remaining)
                findings.append(
                    self._finding(
                        "WORKFLOW_CYCLE_DETECTED",
                        "Workflow dependency cycle detected among: "
                        + ", ".join(cycle_nodes),
                        location="tasks",
                        hint="Remove at least one dependency in the reported cycle.",
                    )
                )
                return None
            for task_id in ready:
                order.append(task_id)
                remaining.pop(task_id)
            for value in remaining.values():
                value.difference_update(ready)
        return tuple(order)

    def _validate_resources(
        self,
        resources: Mapping[str, Any],
        location: str,
        findings: list[ValidationFinding],
    ) -> None:
        self._unknown_fields(resources, _RESOURCE_FIELDS, location, findings)
        for name, value in resources.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                findings.append(
                    self._finding(
                        "WORKFLOW_RESOURCE_INVALID",
                        f"Resource {name!r} must be a positive integer.",
                        location=f"{location}.{name}",
                        scope=FindingScope.EXECUTION,
                    )
                )
        nodes = resources.get("nodes")
        ranks = resources.get("mpi_processes")
        ppn = resources.get("processes_per_node")
        if nodes is not None and ranks is not None and ppn is not None:
            if (
                isinstance(nodes, int)
                and not isinstance(nodes, bool)
                and isinstance(ranks, int)
                and not isinstance(ranks, bool)
                and isinstance(ppn, int)
                and not isinstance(ppn, bool)
                and nodes * ppn != ranks
            ):
                findings.append(
                    self._finding(
                        "WORKFLOW_RESOURCE_PLACEMENT_MISMATCH",
                        "mpi_processes must equal nodes × processes_per_node.",
                        location=location,
                        scope=FindingScope.EXECUTION,
                    )
                )

    def _unknown_fields(
        self,
        raw: Mapping[str, Any],
        allowed: set[str],
        location: str,
        findings: list[ValidationFinding],
    ) -> None:
        for field in sorted(set(raw) - allowed):
            findings.append(
                self._finding(
                    "WORKFLOW_FIELD_UNKNOWN",
                    f"Unknown field {field!r}.",
                    location=f"{location}.{field}",
                    hint="Remove the field or use a supported schema version.",
                )
            )

    def _result(
        self,
        source: Path,
        workflow_id: str | None,
        findings: list[ValidationFinding],
        compiled: CompiledWorkflow | None = None,
    ) -> WorkflowCompilation:
        subject = ValidationSubject(
            subject_id=workflow_id or source.name,
            subject_type="siestaflow.workflow-definition",
            source=str(source),
        )
        report = ValidationReport.build(
            report_id=f"workflow-validation:{workflow_id or source.name}",
            subject=subject,
            findings=tuple(
                replace(item, subject_id=subject.subject_id)
                for item in findings
            ),
            ruleset_sha256=contract_sha256({"rules": _RULESET}),
            produced_by="siestaflow.workflow-compiler",
            metadata={"schema_version": self.SUPPORTED_SCHEMA},
        )
        return WorkflowCompilation(report, compiled)

    @staticmethod
    def _finding(
        code: str,
        message: str,
        *,
        location: str,
        hint: str | None = None,
        scope: FindingScope = FindingScope.STRUCTURE,
    ) -> ValidationFinding:
        return ValidationFinding(
            rule_id="siestaflow.workflow.compiler",
            code=code,
            status=DecisionStatus.BLOCKED,
            message=message,
            evidence_class=EvidenceClass.MATHEMATICAL_CONSISTENCY,
            scope=scope,
            subject_id="workflow",
            location=location,
            hint=hint,
        )

    @staticmethod
    def _sha_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def write_workflow_lock(
    compilation: WorkflowCompilation,
    output: Path,
    *,
    overwrite: bool = False,
) -> str:
    """Atomically write a compiled lock and return its content hash."""
    data = compilation.lock_dict()
    if output.exists() and not overwrite:
        raise FileExistsError(f"workflow lock already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            data,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(encoded, encoding="utf-8", newline="\n")
    temporary.replace(output)
    return str(data["content_sha256"])
