"""Read-only, hash-bound export of completed SIESTA ``.bands`` artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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


def _number(raw: str, *, field: str) -> float:
    try:
        value = float(raw.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"invalid .bands {field}: {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite .bands {field}")
    return value


def _integer(raw: str, *, field: str) -> int:
    value = _number(raw, field=field)
    if not value.is_integer() or value < 1:
        raise ValueError(f".bands {field} must be a positive integer")
    return int(value)


@dataclass(frozen=True)
class BandData:
    fermi_energy_eV: float
    k_min: float
    k_max: float
    energy_min_eV: float
    energy_max_eV: float
    bands: int
    spins: int
    k_points: int
    rows: tuple[tuple[float, int, int, int, float], ...]


def parse_bands(path: Path) -> BandData:
    """Parse the documented SIESTA .bands layout, including wrapped energies."""
    tokens = path.read_text(encoding="utf-8", errors="strict").split()
    if len(tokens) < 8:
        raise ValueError(".bands file is too short")
    cursor = 0
    fermi = _number(tokens[cursor], field="Fermi energy"); cursor += 1
    k_min, k_max = (_number(tokens[cursor + offset], field="k range") for offset in range(2)); cursor += 2
    energy_min, energy_max = (_number(tokens[cursor + offset], field="energy range") for offset in range(2)); cursor += 2
    bands = _integer(tokens[cursor], field="band count")
    spins = _integer(tokens[cursor + 1], field="spin count")
    k_points = _integer(tokens[cursor + 2], field="k-point count")
    cursor += 3
    rows: list[tuple[float, int, int, int, float]] = []
    values_per_point = bands * spins
    for k_index in range(k_points):
        if cursor + 1 + values_per_point > len(tokens):
            raise ValueError(".bands file ends before all declared eigenvalues")
        distance = _number(tokens[cursor], field=f"k distance {k_index + 1}")
        cursor += 1
        for spin_index in range(1, spins + 1):
            for band_index in range(1, bands + 1):
                energy = _number(tokens[cursor], field="eigenvalue")
                cursor += 1
                rows.append((distance, k_index + 1, spin_index, band_index, energy))
    if cursor >= len(tokens):
        raise ValueError(".bands path label section is missing")
    lines = _integer(tokens[cursor], field="path line count")
    if len(tokens) <= cursor + 2 * lines:
        raise ValueError(".bands path label section is incomplete")
    return BandData(fermi, k_min, k_max, energy_min, energy_max, bands, spins, k_points, tuple(rows))


class BandResultExporter:
    """Create a portable band table after immutable package verification."""

    def __init__(self, inspector: RunInspector | None = None) -> None:
        self._inspector = inspector or RunInspector()

    def export(self, package: Path, output: Path, *, dry_run: bool = False) -> dict[str, Any]:
        inspection = self._inspector.inspect(package)
        root = Path(inspection.package_path)
        if inspection.campaign_status != ExecutionStatus.COMPLETED.value:
            raise ValueError("band export requires a completed campaign")
        config = load_controller_config(root / "campaign.yaml")
        candidates = [task for task in config.tasks if any(str(item).lower().endswith(".bands") for item in task.required_artifacts)]
        if len(candidates) != 1:
            raise ValueError("completed package must declare exactly one task with a required .bands artifact")
        task = candidates[0]
        progress = {str(item["task_id"]): item for item in read_campaign_progress(root)["tasks"]}
        item = progress[task.task_id]
        attempt_id = item.get("last_attempt")
        if item.get("status") != ExecutionStatus.COMPLETED.value or not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("band task does not have a completed attempt")
        attempt = root / "work" / task.task_id / attempt_id
        result_path = attempt / "result_manifest.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
        if not isinstance(result, Mapping) or result.get("task_id") != task.task_id:
            raise ValueError("band result manifest identity mismatch")
        if result.get("exit_code") != 0 or result.get("normal_termination") is not True or result.get("scf_converged") is not True:
            raise ValueError("band result is not a successful converged SIESTA calculation")
        name = next(str(value) for value in task.required_artifacts if str(value).lower().endswith(".bands"))
        source = attempt / name
        artifacts = result.get("artifacts")
        if not source.is_file() or source.is_symlink() or not isinstance(artifacts, Mapping) or artifacts.get(name) != _sha256(source):
            raise ValueError("band artifact hash verification failed")
        data = parse_bands(source)
        target = output.expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"result export destination already exists: {target}")
        response = {"status": "BAND_RESULT_EXPORT_READY" if dry_run else "BAND_RESULT_EXPORTED", "output": str(target),
                    "files": ["bands.csv", "bands_export.json"], "run_id": inspection.run_id, "workflow_id": inspection.workflow_id,
                    "task_id": task.task_id, "k_points": data.k_points, "bands": data.bands, "spins": data.spins,
                    "rows": len(data.rows), "scientific_interpretation": "NOT_PERFORMED"}
        if dry_run:
            return response
        target.mkdir(parents=True)
        table = target / "bands.csv"
        with table.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("k_distance", "k_point_index", "spin_index", "band_index", "energy_eV"))
            writer.writerows(data.rows)
        workflow_envelope, _ = load_workflow_lock(root / "workflow.lock.json")
        run_envelope, run = load_run_lock(root / "run.lock.json")
        source_identity = run.metadata.get("source_identity", {}) if isinstance(run.metadata, Mapping) else {}
        manifest = {
            "schema_version": "1.0", "classification": "HASH_BOUND_BAND_RESULT_EXPORT", "scientific_interpretation": "NOT_PERFORMED",
            "source": {"run_id": inspection.run_id, "workflow_id": inspection.workflow_id, "task_id": task.task_id,
                       "attempt_id": attempt_id, "source_commit": source_identity.get("source_commit"),
                       "workflow_lock_sha256": workflow_envelope.content_sha256, "run_lock_sha256": run_envelope.content_sha256,
                       "result_manifest": result_path.relative_to(root).as_posix(), "result_manifest_sha256": _sha256(result_path)},
            "bands": {"source_artifact": source.relative_to(root).as_posix(), "source_sha256": _sha256(source),
                      "table": "bands.csv", "table_sha256": _sha256(table), "fermi_energy_eV": data.fermi_energy_eV,
                      "k_range": [data.k_min, data.k_max], "energy_range_eV": [data.energy_min_eV, data.energy_max_eV],
                      "bands": data.bands, "spins": data.spins, "k_points": data.k_points, "rows": len(data.rows)},
        }
        manifest_path = target / "bands_export.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        response["table_sha256"] = _sha256(table)
        response["manifest_sha256"] = _sha256(manifest_path)
        return response
