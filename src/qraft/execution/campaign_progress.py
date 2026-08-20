"""Read-only progress reporting for allocation-controller campaigns."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .allocation_controller import ExecutionStatus, load_controller_config


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _resolve_root(value: Path) -> tuple[Path, Path]:
    selected = value.resolve()
    if selected.is_file():
        return selected.parent, selected
    for name in ("campaign.yaml", "campaign.json"):
        candidate = selected / name
        if candidate.is_file():
            return selected, candidate
    raise ValueError(f"campaign.yaml or campaign.json not found under {selected}")


def read_campaign_progress(value: Path) -> dict[str, Any]:
    """Validate persisted state and return a stable progress snapshot."""
    root, campaign_path = _resolve_root(value)
    config = load_controller_config(campaign_path)
    canonical_state = root / "state" / "workflow_runtime.json"
    legacy_state = root / "state" / "campaign_state.json"
    state_path = canonical_state if canonical_state.is_file() else legacy_state
    if not state_path.is_file():
        tasks = {
            task.task_id: {
                "status": ExecutionStatus.PENDING.value,
                "attempts": 0,
                "reason": "campaign has not started",
                "depends_on": list(task.depends_on),
            }
            for task in config.tasks
        }
        campaign_status = ExecutionStatus.PENDING.value
        current_job_id = None
        revision = 0
    else:
        wrapper = json.loads(state_path.read_text(encoding="utf-8"))
        payload = wrapper.get("payload")
        if wrapper.get("schema_version") != "1.0" or not isinstance(payload, dict):
            raise ValueError("invalid campaign state schema")
        digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        if digest != wrapper.get("sha256"):
            raise ValueError("campaign state checksum mismatch")
        tasks = payload.get("tasks", {})
        if not isinstance(tasks, dict):
            raise ValueError("campaign state tasks are invalid")
        expected_tasks = {task.task_id for task in config.tasks}
        if set(tasks) != expected_tasks:
            raise ValueError("campaign state task identity mismatch")
        if state_path == legacy_state and payload.get("campaign_id") != config.campaign_id:
            raise ValueError("campaign state identity mismatch")
        campaign_status = str(payload.get("status", "UNKNOWN"))
        current_job_id = payload.get("current_job_id")
        if state_path == canonical_state:
            summary = root / "results" / "campaign_summary.json"
            if summary.is_file():
                current_job_id = json.loads(
                    summary.read_text(encoding="utf-8")
                ).get("job_id")
        revision = int(payload.get("revision", 0))
    ordered: list[dict[str, Any]] = []
    for index, task in enumerate(config.tasks, start=1):
        item = tasks.get(task.task_id, {})
        ordered.append({
            "number": index,
            "task_id": task.task_id,
            "status": str(item.get("status", "UNKNOWN")),
            "attempts": int(item.get("attempts", 0)),
            "reason": str(item.get("reason", "")),
            "depends_on": list(task.depends_on),
            "last_attempt": item.get("last_attempt"),
            "hosts": item.get("hosts", []),
        })
    completed = sum(item["status"] == ExecutionStatus.COMPLETED.value for item in ordered)
    running = [item["task_id"] for item in ordered if item["status"] == ExecutionStatus.RUNNING.value]
    ready = [
        task.task_id
        for task in config.tasks
        if tasks.get(task.task_id, {}).get("status", ExecutionStatus.PENDING.value)
        in {
            ExecutionStatus.PENDING.value,
            ExecutionStatus.INTERRUPTED.value,
            ExecutionStatus.INCOMPLETE.value,
        }
        and all(
            tasks.get(parent, {}).get("status") == ExecutionStatus.COMPLETED.value
            for parent in task.depends_on
        )
    ]
    return {
        "schema_version": "1.0",
        "campaign_id": config.campaign_id,
        "system_id": config.system_id,
        "campaign_status": campaign_status,
        "job_id": current_job_id,
        "launcher_kind": config.launcher_kind,
        "completed": completed,
        "total": len(ordered),
        "percent": round(100.0 * completed / len(ordered), 1),
        "running": running,
        "ready": ready,
        "revision": revision,
        "tasks": ordered,
        "state_path": str(state_path),
    }


def render_campaign_progress(snapshot: dict[str, Any]) -> str:
    lines = [
        f"CAMPAIGN {snapshot['campaign_id']}  "
        f"{snapshot['completed']}/{snapshot['total']} ({snapshot['percent']:.1f}%)",
        f"STATUS {snapshot['campaign_status']}  "
        f"JOB {snapshot['job_id'] or '-'}  "
        f"LAUNCHER {snapshot['launcher_kind']}",
        "",
        "N    TASK                                     STATUS         ATTEMPTS",
        "---  ---------------------------------------  -------------  --------",
    ]
    for item in snapshot["tasks"]:
        lines.append(
            f"{item['number']:<3}  {item['task_id'][:39]:<39}  "
            f"{item['status'][:13]:<13}  {item['attempts']}"
        )
    if snapshot["running"]:
        lines.append("\nRUNNING: " + ", ".join(snapshot["running"]))
    if snapshot["ready"]:
        lines.append("READY: " + ", ".join(snapshot["ready"]))
    return "\n".join(lines)
