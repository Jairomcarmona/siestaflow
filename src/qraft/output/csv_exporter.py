"""Small dependency-free CSV exporter for declared tabular output."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .model import OutputMatrix, OutputModel, OutputTable


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return normalized or "output"


class CsvExporter:
    def __init__(self, results_root: Path) -> None:
        self.results_root = results_root

    def export(self, model: OutputModel, *, large_matrix: int = 100) -> dict[str, str]:
        selected_tables = tuple(table for table in model.tables if table.export_csv and table.rows)
        selected_matrices = tuple(
            matrix for matrix in model.matrices
            if matrix.values and (matrix.export_csv or matrix.shape[0] * matrix.shape[1] > large_matrix)
        )
        if not selected_tables and not selected_matrices:
            return {}
        self.results_root.mkdir(parents=True, exist_ok=True)
        exported: dict[str, str] = {}
        for table in selected_tables:
            path = self._available_path(_slug(table.name))
            self._write_table(path, table)
            exported[f"table:{table.name}"] = str(path.resolve())
        for matrix in selected_matrices:
            path = self._available_path(_slug(matrix.name))
            self._write_matrix(path, matrix)
            exported[f"matrix:{matrix.name}"] = str(path.resolve())
        return exported

    def _available_path(self, stem: str) -> Path:
        candidate = self.results_root / f"{stem}.csv"
        index = 2
        while candidate.exists():
            candidate = self.results_root / f"{stem}-{index:03d}.csv"
            index += 1
        return candidate

    @staticmethod
    def _write_table(path: Path, table: OutputTable) -> None:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(table.columns)
            writer.writerows(table.rows)

    @staticmethod
    def _write_matrix(path: Path, matrix: OutputMatrix) -> None:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("", *matrix.column_labels))
            for label, row in zip(matrix.row_labels, matrix.values, strict=True):
                writer.writerow((label, *row))
