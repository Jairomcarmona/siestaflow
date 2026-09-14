"""Read-only, hash-bound export of completed SIESTA DOS/PDOS results.

This module deliberately exports numerical data and provenance only.  It does
not infer band gaps, peaks, orbital assignments, or scientific conclusions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .execution.allocation_controller import ExecutionStatus, load_controller_config
from .execution.campaign_progress import read_campaign_progress
from .run_inspection import RunInspector
from .workflows import load_run_lock, load_workflow_lock


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _float(token: str, *, line_number: int) -> float:
    try:
        value = float(token.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"invalid DOS numeric value at line {line_number}: {token!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite DOS numeric value at line {line_number}")
    return value


@dataclass(frozen=True)
class TotalDOS:
    columns: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]


def parse_total_dos(path: Path) -> TotalDOS:
    """Parse SIESTA total DOS rows with either non-spin or collinear-spin data."""
    rows: list[tuple[float, ...]] = []
    width: int | None = None
    previous_energy: float | None = None
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith(("#", "!")):
            continue
        values = tuple(_float(item, line_number=line_number) for item in text.split())
        if len(values) not in {2, 3}:
            raise ValueError(f"DOS row at line {line_number} must contain energy plus one or two DOS columns")
        if width is None:
            width = len(values)
        elif len(values) != width:
            raise ValueError(f"inconsistent DOS column count at line {line_number}")
        if previous_energy is not None and values[0] <= previous_energy:
            raise ValueError(f"DOS energies must be strictly increasing (line {line_number})")
        previous_energy = values[0]
        rows.append(values)
    if not rows:
        raise ValueError("DOS file contains no numeric rows")
    columns = (
        ("energy_eV", "total_dos_states_per_eV")
        if width == 2
        else ("energy_eV", "dos_spin_up_states_per_eV", "dos_spin_down_states_per_eV")
    )
    return TotalDOS(columns=columns, rows=tuple(rows))


def _dos_pdos_task(tasks: Sequence[Any]) -> Any:
    candidates: list[Any] = []
    for task in tasks:
        artifacts = tuple(str(item) for item in task.required_artifacts)
        if any(item.lower().endswith(".dos") for item in artifacts) and any(item.lower().endswith(".pdos") for item in artifacts):
            candidates.append(task)
    if len(candidates) != 1:
        raise ValueError("completed package must declare exactly one task with required DOS and PDOS artifacts")
    return candidates[0]


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class DOSPDOSResultExporter:
    """Produce a portable table and manifest from one verified completed package."""

    def __init__(self, inspector: RunInspector | None = None) -> None:
        self._inspector = inspector or RunInspector()

    def export(self, package: Path, output: Path, *, dry_run: bool = False) -> dict[str, Any]:
        inspection = self._inspector.inspect(package)
        root = Path(inspection.package_path)
        if inspection.campaign_status != ExecutionStatus.COMPLETED.value:
            raise ValueError("DOS/PDOS export requires a completed campaign")
        config = load_controller_config(root / "campaign.yaml")
        task = _dos_pdos_task(config.tasks)
        progress = {
            str(item["task_id"]): item
            for item in read_campaign_progress(root)["tasks"]
        }
        task_progress = progress[task.task_id]
        attempt_id = task_progress.get("last_attempt")
        if task_progress.get("status") != ExecutionStatus.COMPLETED.value or not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("DOS/PDOS task does not have a completed attempt")
        attempt = root / "work" / task.task_id / attempt_id
        manifest_path = attempt / "result_manifest.json"
        if not manifest_path.is_file():
            raise ValueError("DOS/PDOS result manifest is missing")
        result = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(result, Mapping) or result.get("task_id") != task.task_id:
            raise ValueError("DOS/PDOS result manifest identity mismatch")
        if result.get("exit_code") != 0 or result.get("normal_termination") is not True or result.get("scf_converged") is not True:
            raise ValueError("DOS/PDOS result is not a successful converged SIESTA calculation")
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, Mapping):
            raise ValueError("DOS/PDOS result artifact hashes are missing")
        names = tuple(str(item) for item in task.required_artifacts)
        dos_name = next(item for item in names if item.lower().endswith(".dos"))
        pdos_name = next(item for item in names if item.lower().endswith(".pdos"))
        dos_path, pdos_path = attempt / dos_name, attempt / pdos_name
        for name, path in ((dos_name, dos_path), (pdos_name, pdos_path)):
            expected = artifacts.get(name)
            if not path.is_file() or path.is_symlink() or not isinstance(expected, str) or _sha256(path) != expected:
                raise ValueError(f"DOS/PDOS artifact hash verification failed: {name}")
        transfers = result.get("transferred_inputs", [])
        if task.transfers:
            restart = result.get("restart_evidence")
            if not isinstance(restart, Mapping) or restart.get("dm_read_attempted") is not True or restart.get("dm_read_succeeded") is not True:
                raise ValueError("DOS/PDOS restart evidence is incomplete")
        total_dos = parse_total_dos(dos_path)
        target = output.expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"result export destination already exists: {target}")
        table_name = "total_dos.csv"
        manifest_name = "dos_pdos_export.json"
        workflow_envelope, _ = load_workflow_lock(root / "workflow.lock.json")
        run_envelope, run = load_run_lock(root / "run.lock.json")
        response: dict[str, Any] = {
            "status": "DOS_PDOS_RESULT_EXPORT_READY" if dry_run else "DOS_PDOS_RESULT_EXPORTED",
            "output": str(target),
            "files": [table_name, manifest_name],
            "run_id": inspection.run_id,
            "workflow_id": inspection.workflow_id,
            "task_id": task.task_id,
            "rows": len(total_dos.rows),
            "columns": list(total_dos.columns),
            "scientific_interpretation": "NOT_PERFORMED",
        }
        if dry_run:
            return response
        target.mkdir(parents=True)
        table_path = target / table_name
        with table_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(total_dos.columns)
            writer.writerows(total_dos.rows)
        source_identity = run.metadata.get("source_identity", {}) if isinstance(run.metadata, Mapping) else {}
        export_manifest = {
            "schema_version": "1.0",
            "classification": "HASH_BOUND_DOS_PDOS_RESULT_EXPORT",
            "scientific_interpretation": "NOT_PERFORMED",
            "source": {
                "run_id": inspection.run_id,
                "workflow_id": inspection.workflow_id,
                "task_id": task.task_id,
                "attempt_id": attempt_id,
                "source_commit": source_identity.get("source_commit"),
                "workflow_lock_sha256": workflow_envelope.content_sha256,
                "run_lock_sha256": run_envelope.content_sha256,
                "result_manifest": _relative(manifest_path, root),
                "result_manifest_sha256": _sha256(manifest_path),
            },
            "total_dos": {
                "source_artifact": _relative(dos_path, root),
                "source_sha256": _sha256(dos_path),
                "table": table_name,
                "table_sha256": _sha256(table_path),
                "rows": len(total_dos.rows),
                "columns": list(total_dos.columns),
            },
            "pdos": {
                "source_artifact": _relative(pdos_path, root),
                "source_sha256": _sha256(pdos_path),
                "bytes": pdos_path.stat().st_size,
                "parsed": False,
                "reason": "raw PDOS is retained as a hash-bound SIESTA artifact; no projection interpretation is automated",
            },
            "restart_provenance": {
                "required": bool(task.transfers),
                "evidence": result.get("restart_evidence") if task.transfers else None,
                "transferred_inputs": transfers,
            },
        }
        manifest_path_out = target / manifest_name
        manifest_path_out.write_text(_canonical(export_manifest), encoding="utf-8", newline="\n")
        response["table_sha256"] = _sha256(table_path)
        response["manifest_sha256"] = _sha256(manifest_path_out)
        return response
