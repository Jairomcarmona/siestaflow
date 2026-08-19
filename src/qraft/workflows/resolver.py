"""Artifact resolution and deterministic topological compilation."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from ..contracts import (
    ArtifactReference,
    ArtifactRole,
    CompiledWorkflow,
    FindingScope,
    ValidationFinding,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowInputBinding,
    WorkflowTaskNode,
    contract_sha256,
)
from ..contracts.artifacts import require_relative_artifact_path
from .diagnostics import finding
from .models import InputDraft, ParsedWorkflow


class WorkflowResolver:
    def resolve(
        self,
        parsed: ParsedWorkflow,
        findings: list[ValidationFinding],
    ) -> CompiledWorkflow | None:
        drafts = parsed.tasks
        by_id = {task.task_id: task for task in drafts}
        outputs = {
            (task.task_id, output.name): output
            for task in drafts
            for output in task.outputs
        }
        dependencies = {
            task.task_id: set(task.dependencies) for task in drafts
        }
        external: dict[str, ArtifactReference] = {}
        bindings: dict[str, list[WorkflowInputBinding]] = {
            task.task_id: [] for task in drafts
        }
        edges: list[WorkflowEdge] = []
        for task in drafts:
            self._resolve_control_dependencies(
                task.task_id,
                task.dependencies,
                by_id,
                edges,
                findings,
            )
            for item in task.inputs:
                if item.source_path is not None:
                    binding = self._resolve_external_input(
                        parsed.source.parent,
                        item,
                        external,
                        findings,
                    )
                else:
                    binding = self._resolve_produced_input(
                        task.task_id,
                        item,
                        by_id,
                        outputs,
                        dependencies,
                        edges,
                        findings,
                    )
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
                        inputs=tuple(
                            sorted(bindings[task_id], key=lambda item: item.name)
                        ),
                        outputs=tuple(
                            sorted(task.outputs, key=lambda item: item.name)
                        ),
                        resources=dict(task.resources),
                        settings=dict(task.settings),
                    )
                )
            except (TypeError, ValueError) as exc:
                findings.append(
                    finding(
                        "WORKFLOW_TASK_INVALID",
                        str(exc),
                        location=f"tasks.{task_id}",
                    )
                )
        if findings:
            return None
        metadata = dict(parsed.metadata)
        if parsed.description:
            metadata["description"] = parsed.description
        try:
            return CompiledWorkflow(
                workflow_id=parsed.workflow_id,
                project_id=parsed.project_id,
                definition_sha256=parsed.definition_sha256,
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
                metadata=metadata,
            )
        except ValueError as exc:
            findings.append(
                finding(
                    "WORKFLOW_CONTRACT_INVALID",
                    str(exc),
                    location="workflow",
                )
            )
            return None

    @staticmethod
    def _resolve_control_dependencies(
        task_id,
        dependencies,
        by_id,
        edges,
        findings,
    ) -> None:
        for dependency in dependencies:
            if dependency not in by_id:
                findings.append(
                    finding(
                        "WORKFLOW_DEPENDENCY_UNKNOWN",
                        f"Task {task_id!r} depends on unknown task {dependency!r}.",
                        location=f"tasks.{task_id}.depends_on",
                    )
                )
            elif dependency == task_id:
                findings.append(
                    finding(
                        "WORKFLOW_SELF_DEPENDENCY",
                        f"Task {task_id!r} depends on itself.",
                        location=f"tasks.{task_id}.depends_on",
                    )
                )
            else:
                edges.append(
                    WorkflowEdge(
                        dependency, task_id, WorkflowEdgeKind.CONTROL
                    )
                )

    @staticmethod
    def _resolve_produced_input(
        task_id,
        item,
        by_id,
        outputs,
        dependencies,
        edges,
        findings,
    ) -> WorkflowInputBinding | None:
        key = (str(item.source_task), str(item.source_output))
        output = outputs.get(key)
        if item.source_task not in by_id:
            findings.append(
                finding(
                    "WORKFLOW_INPUT_TASK_UNKNOWN",
                    f"Input {item.name!r} references unknown task "
                    f"{item.source_task!r}.",
                    location=item.location,
                )
            )
            return None
        if output is None:
            findings.append(
                finding(
                    "WORKFLOW_INPUT_OUTPUT_UNKNOWN",
                    f"Input {item.name!r} references unknown output "
                    f"{item.source_task}.{item.source_output}.",
                    location=item.location,
                )
            )
            return None
        dependencies[task_id].add(str(item.source_task))
        destination = item.destination or PurePosixPath(output.relative_path).name
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
                    task_id,
                    WorkflowEdgeKind.ARTIFACT,
                    str(item.source_output),
                    item.name,
                )
            )
            return binding
        except ValueError as exc:
            findings.append(
                finding(
                    "WORKFLOW_INPUT_INVALID",
                    str(exc),
                    location=item.location,
                )
            )
            return None

    def _resolve_external_input(
        self,
        root: Path,
        item: InputDraft,
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
                self._require_declared_hash(
                    relative, item.declared_sha256, digest
                )
            artifact_id = "input-" + contract_sha256({"path": relative})[:16]
            media_type = item.media_type or "application/octet-stream"
            reference = ArtifactReference(
                artifact_id=artifact_id,
                role=ArtifactRole.INPUT,
                relative_path=relative,
                sha256=digest,
                size_bytes=candidate.stat().st_size,
                media_type=media_type,
            )
            existing = external.get(artifact_id)
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
                finding(
                    "WORKFLOW_EXTERNAL_INPUT_INVALID",
                    str(exc),
                    location=item.location,
                    hint="Use a relative path inside the workflow directory.",
                    scope=FindingScope.PROVENANCE,
                )
            )
            return None

    @staticmethod
    def _require_declared_hash(
        relative: str, declared: str, observed: str
    ) -> None:
        if len(declared) != 64 or any(
            char not in "0123456789abcdef" for char in declared
        ):
            raise ValueError(f"invalid declared SHA-256 for {relative}")
        if declared != observed:
            raise ValueError(f"declared SHA-256 mismatch for {relative}")

    @staticmethod
    def _topological_order(
        dependencies: dict[str, set[str]],
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
                findings.append(
                    finding(
                        "WORKFLOW_CYCLE_DETECTED",
                        "Workflow dependency cycle detected among: "
                        + ", ".join(sorted(remaining)),
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

    @staticmethod
    def _sha_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
