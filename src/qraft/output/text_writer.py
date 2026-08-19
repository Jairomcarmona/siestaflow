"""Deterministic append-only writer for the official human ``qraft.out``."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Iterable, Mapping

from .csv_exporter import CsvExporter
from .model import NodeEntry, OutputMatrix, OutputMessage, OutputModel, OutputTable, Scalar


_RULE = "=" * 64


def _display(value: Scalar) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value).replace("\n", " ")


def _mapping(lines: list[str], values: Mapping[str, Scalar]) -> None:
    if not values:
        return
    width = min(24, max(len(str(key)) for key in values))
    for key, value in values.items():
        lines.append(f"{str(key):<{width}} : {_display(value)}")


class QraftOutputWriter:
    """The single process-local authority that appends complete output blocks."""

    def __init__(
        self, path: Path, *, matrix_cell_limit: int = 100, table_row_limit: int = 50
    ) -> None:
        self.path = path.resolve()
        self.matrix_cell_limit = matrix_cell_limit
        self.table_row_limit = table_row_limit
        self.csv_exporter = CsvExporter(self.path.parent / "results")
        self._lock = threading.RLock()

    @property
    def exists(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def initialize(self, model: OutputModel) -> tuple[str, ...]:
        lines = [
            _RULE,
            "                           Q R A F T",
            "       Quantum Reproducible Automation & Flow Toolkit",
            _RULE,
            "qraft-output-schema : 1.0",
        ]
        _mapping(lines, model.header)
        lines.append(_RULE)
        lines.extend(self._render_model(model, include_header=False))
        return self._append(lines, model)

    def append(self, title: str, model: OutputModel) -> tuple[str, ...]:
        lines = ["", f"[{title.strip().upper()}]", ""]
        lines.extend(self._render_model(model, include_header=True))
        return self._append(lines, model)

    def append_recovery(self, values: Mapping[str, Scalar]) -> tuple[str, ...]:
        lines = ["", "[RECOVERY]", ""]
        _mapping(lines, values)
        return self._append(lines, OutputModel())

    def finish(self, summary: Mapping[str, Scalar]) -> tuple[str, ...]:
        lines = ["", _RULE, "QRAFT CAMPAIGN SUMMARY", _RULE]
        _mapping(lines, summary)
        lines.append(_RULE)
        return self._append(lines, OutputModel())

    def _append(self, lines: Iterable[str], model: OutputModel) -> tuple[str, ...]:
        with self._lock:
            warnings: list[str] = []
            try:
                exported = self.csv_exporter.export(
                    model, large_matrix=self.matrix_cell_limit
                )
            except Exception as exc:  # Optional derivative output cannot invalidate science.
                exported = {}
                warnings.append(f"CSV_EXPORT_WARNING:{type(exc).__name__}:{exc}")
            rendered = list(lines)
            if exported:
                rendered.extend(("", "[CSV ARTIFACTS]"))
                _mapping(rendered, exported)
            for warning in warnings:
                rendered.extend(("", f"WARNING : {warning}"))
            block = "\n".join(rendered).rstrip() + "\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
            return tuple(warnings)

    def _render_model(self, model: OutputModel, *, include_header: bool) -> list[str]:
        lines: list[str] = []
        if include_header and model.header:
            _mapping(lines, model.header)
        if model.configuration:
            lines.extend(("", "[RESOLVED CONFIGURATION]"))
            _mapping(lines, model.configuration)
        if model.dag:
            lines.extend(("", "[DAG]", ""))
            for index, node in enumerate(model.dag, 1):
                parents = f" <- {','.join(node.depends_on)}" if node.depends_on else ""
                lines.append(f"N{index:03d} {node.node_id:<36} {node.status}{parents}")
        for node in model.nodes:
            lines.extend(self._render_node(node))
        if model.metrics:
            lines.extend(("", "[METRICS]"))
            _mapping(lines, model.metrics)
        if model.paths:
            lines.extend(("", "[PATHS]"))
            _mapping(lines, model.paths)
        if model.artifacts:
            lines.extend(("", "[ARTIFACTS]"))
            _mapping(lines, model.artifacts)
        for table in model.tables:
            lines.extend(self._render_table(table))
        for matrix in model.matrices:
            lines.extend(self._render_matrix(matrix))
        for message in model.messages:
            lines.extend(self._render_message(message))
        if model.decisions:
            lines.extend(("", "[DECISIONS]"))
            _mapping(lines, model.decisions)
        if model.notes:
            lines.extend(("", "[NOTES]"))
            lines.extend(f"- {note}" for note in model.notes)
        if model.summary:
            lines.extend(("", "[SUMMARY]"))
            _mapping(lines, model.summary)
        return lines

    @staticmethod
    def _render_node(node: NodeEntry) -> list[str]:
        values: dict[str, Scalar] = {
            "Node type": node.node_type,
            "Attempt": node.attempt_id,
            "Status": node.status,
            "Workdir": node.workdir,
            "Input": node.input_path,
            "stdout": node.stdout_path,
            "stderr": node.stderr_path,
            "Evidence": node.evidence_path,
            "Dependencies": ",".join(node.depends_on) if node.depends_on else "-",
            **node.resources,
        }
        lines = ["", f"[NODE {node.node_id}]", ""]
        _mapping(lines, values)
        return lines

    def _render_table(self, table: OutputTable) -> list[str]:
        suffix = f" [{table.unit}]" if table.unit else ""
        lines = ["", f"[TABLE {table.name}]{suffix}", ""]
        if len(table.rows) > self.table_row_limit:
            lines.extend((
                f"Rows       : {len(table.rows)}",
                f"Columns    : {len(table.columns)}",
                f"Full table : {table.artifact_path or 'CSV artifact emitted by writer'}",
            ))
            return lines
        lines.append(" | ".join(table.columns))
        lines.append("-+-".join("-" * len(item) for item in table.columns))
        lines.extend(" | ".join(_display(value) for value in row) for row in table.rows)
        if table.artifact_path:
            lines.append(f"Full table : {table.artifact_path}")
        return lines

    def _render_matrix(self, matrix: OutputMatrix) -> list[str]:
        suffix = f" [{matrix.unit}]" if matrix.unit else ""
        rows, columns = matrix.shape
        lines = ["", f"[MATRIX {matrix.name}]{suffix}", ""]
        if rows * columns > self.matrix_cell_limit:
            lines.append(f"Dimensions  : {rows} x {columns}")
            _mapping(lines, matrix.summary)
            lines.append(f"Full matrix : {matrix.artifact_path or 'CSV artifact emitted by writer'}")
            return lines
        width = max(10, *(len(label) + 2 for label in (*matrix.row_labels, *matrix.column_labels)))
        lines.append(" " * width + "".join(f"{label:>{width}}" for label in matrix.column_labels))
        for label, row in zip(matrix.row_labels, matrix.values, strict=True):
            lines.append(f"{label:<{width}}" + "".join(f"{_display(value):>{width}}" for value in row))
        _mapping(lines, matrix.summary)
        return lines

    @staticmethod
    def _render_message(message: OutputMessage) -> list[str]:
        title = message.severity + (f" {message.code}" if message.code else "")
        lines = ["", f"[{title}]", f"Message : {message.text}"]
        details: dict[str, Scalar] = {
            "Node": message.node_id,
            "Attempt": message.attempt_id,
            **message.details,
            **message.paths,
        }
        _mapping(lines, {key: value for key, value in details.items() if value is not None})
        return lines
