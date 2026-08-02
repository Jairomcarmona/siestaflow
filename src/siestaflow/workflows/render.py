"""Human and machine renderers for compiled workflow plans."""

from __future__ import annotations

from typing import Any

from ..contracts import CompiledWorkflow, WorkflowEdgeKind, canonical_primitive


def workflow_plan(compiled: CompiledWorkflow) -> dict[str, Any]:
    tasks = []
    total_requested_cpu_seconds = 0
    for index, task in enumerate(compiled.tasks, 1):
        resources = dict(task.resources)
        ranks = int(resources.get("mpi_processes", 1))
        cpus_per_process = int(resources.get("cpus_per_process", 1))
        walltime = int(resources.get("walltime_seconds", 0))
        total_requested_cpu_seconds += ranks * cpus_per_process * walltime
        tasks.append(
            {
                "order": index,
                "task_id": task.task_id,
                "kind": task.kind.value,
                "capability": task.capability_id,
                "dependencies": list(task.dependencies),
                "inputs": [item.name for item in task.inputs],
                "outputs": [item.name for item in task.outputs],
                "resources": resources,
            }
        )
    return {
        "workflow_id": compiled.workflow_id,
        "project_id": compiled.project_id,
        "definition_sha256": compiled.definition_sha256,
        "tasks": tasks,
        "task_count": len(tasks),
        "edge_count": len(compiled.edges),
        "external_artifact_count": len(compiled.external_artifacts),
        "requested_cpu_seconds_upper_bound": total_requested_cpu_seconds,
        "execution_authorized": False,
    }


def render_workflow_plan(compiled: CompiledWorkflow) -> str:
    plan = workflow_plan(compiled)
    lines = [
        f"WORKFLOW {plan['workflow_id']}  PROJECT {plan['project_id']}",
        (
            f"TASKS {plan['task_count']}  EDGES {plan['edge_count']}  "
            f"EXTERNAL_INPUTS {plan['external_artifact_count']}"
        ),
        "",
        "N    TASK                           KIND            DEPENDS ON",
        "---  -----------------------------  --------------  -------------------------",
    ]
    for item in plan["tasks"]:
        dependencies = ",".join(item["dependencies"]) or "-"
        lines.append(
            f"{item['order']:<4} {item['task_id']:<29} "
            f"{item['kind']:<15} {dependencies}"
        )
    lines.extend(
        [
            "",
            "EXECUTION_AUTHORIZED: NO",
            f"DEFINITION_SHA256: {plan['definition_sha256']}",
        ]
    )
    return "\n".join(lines)


def workflow_graph(compiled: CompiledWorkflow) -> dict[str, Any]:
    return {
        "workflow_id": compiled.workflow_id,
        "nodes": [
            {
                "task_id": task.task_id,
                "kind": task.kind.value,
                "capability": task.capability_id,
            }
            for task in compiled.tasks
        ],
        "edges": canonical_primitive(compiled.edges),
    }


def render_workflow_graph(
    compiled: CompiledWorkflow, *, output_format: str = "text"
) -> str:
    if output_format == "mermaid":
        lines = ["flowchart TD"]
        for task in compiled.tasks:
            label = f"{task.task_id}\\n({task.kind.value})".replace('"', "'")
            lines.append(f'    {task.task_id}["{label}"]')
        for edge in compiled.edges:
            if edge.kind is WorkflowEdgeKind.ARTIFACT:
                label = f"{edge.source_output_name} -> {edge.target_input_name}"
                lines.append(
                    f'    {edge.source_task_id} -->|"{label}"| {edge.target_task_id}'
                )
            else:
                lines.append(
                    f"    {edge.source_task_id} -.-> {edge.target_task_id}"
                )
        return "\n".join(lines)
    lines = [f"WORKFLOW {compiled.workflow_id}"]
    incoming = {task.task_id: [] for task in compiled.tasks}
    for edge in compiled.edges:
        label = edge.source_task_id
        if edge.kind is WorkflowEdgeKind.ARTIFACT:
            label += f"[{edge.source_output_name}->{edge.target_input_name}]"
        incoming[edge.target_task_id].append(label)
    for index, task in enumerate(compiled.tasks, 1):
        parents = ", ".join(sorted(incoming[task.task_id])) or "ROOT"
        lines.append(f"{index:>3}. {task.task_id} <- {parents}")
    return "\n".join(lines)
