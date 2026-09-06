"""Read-only projections for the core status and results commands.

These adapters deliberately expose recorded state and artifacts only.  They
do not execute work, validate new scientific claims, or persist observations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .application import ApplicationConfiguration, QraftApplication
from .execution.allocation_controller import load_controller_config
from .run_inspection import RunInspector
from .target_classifier import TargetClassification, TargetKind, classify_target


def status_view(
    target: Path | None, *, runs_root: Path,
) -> dict[str, Any]:
    """Return a stable, read-only status projection for one supported target."""
    if target is None:
        return _runs_status(runs_root, target=None)
    classification = classify_target(target)
    base = _target_metadata(classification)
    if classification.kind is TargetKind.PREPARED_RUN_PACKAGE:
        package = RunInspector().status(classification.path)
        run = package["run"]
        progress = package["progress"]
        return {
            **base,
            "state": str(package["status"]),
            "progress": {
                "completed": progress["completed"], "total": progress["total"],
                "percent": progress["percent"],
            },
            "last_step": str(run.campaign_status),
            "next_action": _package_next_action(str(run.campaign_status), classification.path),
            "recorded": {"package": _primitive(package)},
        }
    if classification.kind is TargetKind.RUNS_ROOT:
        return _runs_status(classification.path, target=base)
    if classification.kind in {TargetKind.CAMPAIGN_SPEC, TargetKind.FDF}:
        return _runs_status(runs_root, target=base)
    return {
        **base,
        "state": "NO_RECORDED_STATUS",
        "progress": None,
        "last_step": None,
        "next_action": f"qraft check {classification.path}",
        "recorded": {},
    }


def results_view(
    target: Path | None, *, runs_root: Path,
) -> dict[str, Any]:
    """Inventory recorded artifacts without treating their presence as science."""
    if target is None:
        return _runs_results(runs_root, target=None)
    classification = classify_target(target)
    base = _target_metadata(classification)
    if classification.kind is TargetKind.PREPARED_RUN_PACKAGE:
        return _package_results(classification, base)
    if classification.kind is TargetKind.RUNS_ROOT:
        return _runs_results(classification.path, target=base)
    if classification.kind in {TargetKind.CAMPAIGN_SPEC, TargetKind.FDF}:
        return _runs_results(runs_root, target=base)
    return {
        **base,
        "inventory_status": "NOT_EVALUATED",
        "artifacts": [],
        "next_action": f"qraft status {classification.path}",
    }


def render_status(data: Mapping[str, Any]) -> str:
    """Render the frozen concise, task-oriented status layout."""
    progress = data.get("progress")
    progress_text = "NOT RECORDED"
    if isinstance(progress, Mapping):
        progress_text = f"{progress.get('completed', 0)}/{progress.get('total', 0)}"
    target = Path(str(data.get("target", data.get("runs_root", ".qraft-runs")))).name
    lines = [
        f"QRAFT STATUS — {target}", "",
        f"STATE        {data.get('state', 'NOT_EVALUATED')}",
        f"PROGRESS     {progress_text}",
        f"LAST STEP    {data.get('last_step') or 'NOT RECORDED'}",
        f"NEXT ACTION  {data.get('next_action') or 'NONE'}",
    ]
    if data.get("next_action"):
        lines.extend(("", f"Next: {data['next_action']}"))
    return "\n".join(lines)


def render_results(data: Mapping[str, Any]) -> str:
    """Render a concise artifact inventory without scientific interpretation."""
    target = Path(str(data.get("target", data.get("runs_root", ".qraft-runs")))).name
    lines = [f"QRAFT RESULTS — {target}", ""]
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        lines.append("ARTIFACTS    NOT EVALUATED — no recorded result artifacts")
    else:
        for item in artifacts:
            if isinstance(item, Mapping):
                lines.append(f"{item.get('status', 'NOT_EVALUATED'):<12} {item.get('path', item.get('name', 'artifact'))}")
    lines.extend(("", f"Next: {data.get('next_action', 'qraft status')}"))
    return "\n".join(lines)


def _runs_status(runs_root: Path, *, target: Mapping[str, Any] | None) -> dict[str, Any]:
    application = QraftApplication(ApplicationConfiguration(runs_root=runs_root))
    recorded = application.status()
    campaign = recorded.get("campaign")
    if not isinstance(campaign, Mapping):
        return {
            **(target or {"target": str(runs_root.resolve()), "target_kind": "RUNS_ROOT"}),
            "root": recorded["root"], "runs_root": recorded["root"], "state": "NOT_STARTED", "progress": None,
            "last_step": None, "next_action": "qraft run <campaign.yaml>",
            "campaign": None, "runtime": recorded.get("runtime"),
            "recorded": {"states": recorded.get("states", [])},
        }
    points = campaign.get("points") if isinstance(campaign.get("points"), list) else []
    completed = sum(
        1 for point in points
        if isinstance(point, Mapping) and point.get("technical_status") == "PASS"
    )
    state = str(campaign.get("execution_state", "UNKNOWN"))
    return {
        **(target or {"target": str(runs_root.resolve()), "target_kind": "RUNS_ROOT"}),
        "root": recorded["root"], "runs_root": recorded["root"], "state": state,
        "progress": {"completed": completed, "total": len(points)},
        "last_step": str(campaign.get("technical_validation", "NOT_EVALUATED")),
        "next_action": _campaign_next_action(state),
        "campaign": campaign, "runtime": recorded.get("runtime"),
        "recorded": {"campaign": campaign, "runtime": recorded.get("runtime")},
    }


def _runs_results(runs_root: Path, *, target: Mapping[str, Any] | None) -> dict[str, Any]:
    root = runs_root.resolve()
    names = ("campaign-result.json", "events.jsonl")
    artifacts = [
        {"name": name, "path": str(root / name),
         "status": "PRESENT" if (root / name).is_file() else "NOT_EVALUATED"}
        for name in names
    ]
    return {
        **(target or {"target": str(root), "target_kind": "RUNS_ROOT"}),
        "runs_root": str(root), "inventory_status": "RECORDED" if any(
            item["status"] == "PRESENT" for item in artifacts
        ) else "NOT_EVALUATED",
        "artifacts": artifacts,
        "next_action": f"qraft status {root}",
    }


def _package_results(
    classification: TargetClassification, base: Mapping[str, Any],
) -> dict[str, Any]:
    inspection = RunInspector().inspect(classification.path)
    config = load_controller_config(classification.path / "campaign.yaml")
    artifacts: list[dict[str, str]] = []
    for task in config.tasks:
        for name in task.required_artifacts:
            matches = sorted((classification.path / "work" / task.task_id).glob(f"*/{name}"))
            artifacts.append({
                "name": name,
                "path": str(matches[-1]) if matches else str(classification.path / "work" / task.task_id / name),
                "status": "PRESENT" if matches else "MISSING",
            })
    return {
        **base, "inventory_status": "RECORDED", "run_id": inspection.run_id,
        "campaign_status": inspection.campaign_status, "artifacts": artifacts,
        "next_action": f"qraft status {classification.path}",
    }


def _target_metadata(classification: TargetClassification) -> dict[str, Any]:
    return {
        "target": str(classification.path), "target_kind": classification.kind.value,
        "authority": classification.authority, "reference": classification.reference,
    }


def _campaign_next_action(state: str) -> str:
    if state == "INTERRUPTED":
        return "qraft resume"
    if state in {"COMPLETED", "FAILED"}:
        return "qraft results"
    return "qraft status"


def _package_next_action(state: str, path: Path) -> str:
    if state == "COMPLETED":
        return f"qraft results {path}"
    return f"qraft advanced execution resume {path}"


def _primitive(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {name: _primitive(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_primitive(item) for item in value]
    return value
