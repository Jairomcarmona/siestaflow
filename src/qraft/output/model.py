"""Versioned, protocol-neutral models for the human QRAFT output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


Scalar = str | int | float | bool | None


def _text(value: object, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


@dataclass(frozen=True)
class DagEntry:
    node_id: str
    node_type: str
    status: str
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "node_id"))
        object.__setattr__(self, "node_type", _text(self.node_type, "node_type"))
        object.__setattr__(self, "status", _text(self.status, "status").upper())
        object.__setattr__(self, "depends_on", tuple(map(str, self.depends_on)))


@dataclass(frozen=True)
class NodeEntry:
    node_id: str
    node_type: str
    status: str
    attempt_id: str | None = None
    workdir: str | None = None
    input_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    evidence_path: str | None = None
    resources: Mapping[str, Scalar] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "node_id"))
        object.__setattr__(self, "node_type", _text(self.node_type, "node_type"))
        object.__setattr__(self, "status", _text(self.status, "status").upper())
        object.__setattr__(self, "depends_on", tuple(map(str, self.depends_on)))
        object.__setattr__(self, "resources", dict(self.resources))


@dataclass(frozen=True)
class OutputTable:
    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]
    unit: str | None = None
    export_csv: bool = True
    artifact_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "table name"))
        columns = tuple(map(str, self.columns))
        if not columns or any(not item.strip() for item in columns):
            raise ValueError("table columns must be non-empty")
        rows = tuple(tuple(row) for row in self.rows)
        if any(len(row) != len(columns) for row in rows):
            raise ValueError("table rows must match the declared columns")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)


@dataclass(frozen=True)
class OutputMatrix:
    name: str
    row_labels: tuple[str, ...]
    column_labels: tuple[str, ...]
    values: tuple[tuple[Scalar, ...], ...]
    unit: str | None = None
    export_csv: bool = True
    artifact_path: str | None = None
    summary: Mapping[str, Scalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "matrix name"))
        rows = tuple(map(str, self.row_labels))
        columns = tuple(map(str, self.column_labels))
        values = tuple(tuple(row) for row in self.values)
        if len(values) != len(rows) or any(len(row) != len(columns) for row in values):
            raise ValueError("matrix dimensions do not match labels")
        object.__setattr__(self, "row_labels", rows)
        object.__setattr__(self, "column_labels", columns)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "summary", dict(self.summary))

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.row_labels), len(self.column_labels)


@dataclass(frozen=True)
class OutputMessage:
    severity: str
    text: str
    code: str | None = None
    node_id: str | None = None
    attempt_id: str | None = None
    paths: Mapping[str, str] = field(default_factory=dict)
    details: Mapping[str, Scalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        severity = _text(self.severity, "message severity").upper()
        if severity not in {"WARNING", "ERROR", "REVIEW_REQUIRED", "BLOCKED"}:
            raise ValueError(f"unsupported output severity: {severity}")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "text", _text(self.text, "message text"))
        object.__setattr__(self, "paths", {str(key): str(value) for key, value in self.paths.items()})
        object.__setattr__(self, "details", dict(self.details))


@dataclass(frozen=True)
class OutputModel:
    """Generic payload rendered by the one official human-output writer."""

    header: Mapping[str, Scalar] = field(default_factory=dict)
    configuration: Mapping[str, Scalar] = field(default_factory=dict)
    dag: tuple[DagEntry, ...] = ()
    nodes: tuple[NodeEntry, ...] = ()
    metrics: Mapping[str, Scalar] = field(default_factory=dict)
    paths: Mapping[str, str] = field(default_factory=dict)
    artifacts: Mapping[str, str] = field(default_factory=dict)
    tables: tuple[OutputTable, ...] = ()
    matrices: tuple[OutputMatrix, ...] = ()
    messages: tuple[OutputMessage, ...] = ()
    decisions: Mapping[str, Scalar] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    summary: Mapping[str, Scalar] = field(default_factory=dict)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("unsupported qraft output schema")
        for name in ("header", "configuration", "metrics", "paths", "artifacts", "decisions", "summary"):
            object.__setattr__(self, name, dict(getattr(self, name)))
        for name in ("dag", "nodes", "tables", "matrices", "messages", "notes"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @classmethod
    def combine(cls, models: Sequence["OutputModel"]) -> "OutputModel":
        mappings = ("header", "configuration", "metrics", "paths", "artifacts", "decisions", "summary")
        sequences = ("dag", "nodes", "tables", "matrices", "messages", "notes")
        values: dict[str, Any] = {name: {} for name in mappings}
        values.update({name: [] for name in sequences})
        for model in models:
            for name in mappings:
                values[name].update(getattr(model, name))
            for name in sequences:
                values[name].extend(getattr(model, name))
        return cls(**values)
