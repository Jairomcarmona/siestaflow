"""Minimal engine-neutral contracts for a QRAFT v1 executable plan."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(value: str, field_name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64:
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a SHA-256 digest") from exc
    return normalized


@dataclass(frozen=True)
class ScientificIdentity:
    """Content identity of inputs that can change the computed result."""

    engine: str
    effective_fdf_sha256: str
    geometry_sha256: str
    species_mapping_sha256: str
    pseudopotentials: Mapping[str, str]
    components: Mapping[str, str]
    included_scientific_files: Mapping[str, str]
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.engine.strip():
            raise ValueError("scientific identity requires an engine")
        for name in (
            "effective_fdf_sha256",
            "geometry_sha256",
            "species_mapping_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        for mapping_name in (
            "pseudopotentials",
            "components",
            "included_scientific_files",
        ):
            mapping = dict(getattr(self, mapping_name))
            if any(not str(key).strip() for key in mapping):
                raise ValueError(f"{mapping_name} keys must be non-empty")
            object.__setattr__(
                self,
                mapping_name,
                {
                    str(key): _sha256(str(value), f"{mapping_name}.{key}")
                    for key, value in sorted(mapping.items())
                },
            )

    @property
    def fingerprint(self) -> str:
        return _digest(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True)
class ExecutionSpec:
    """Resolved runtime placement, deliberately separate from science."""

    partition: str
    nodes: int
    mpi_ranks: int
    cpus_per_rank: int
    memory_mb: int | None
    launcher: str
    executable: str
    walltime_seconds: int
    environment: Mapping[str, str] = field(default_factory=dict)
    executable_arguments: tuple[str, ...] = ()
    launcher_command: tuple[str, ...] = ()
    launcher_arguments: tuple[str, ...] = ()
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        for name in ("partition", "launcher", "executable"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"execution spec requires {name}")
        for name in ("nodes", "mpi_ranks", "cpus_per_rank", "walltime_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.memory_mb is not None and (
            isinstance(self.memory_mb, bool)
            or not isinstance(self.memory_mb, int)
            or self.memory_mb <= 0
        ):
            raise ValueError("memory_mb must be a positive integer when declared")
        if self.mpi_ranks % self.nodes:
            raise ValueError("mpi_ranks must be divisible by nodes")
        launcher = self.launcher.casefold()
        if not launcher.replace("-", "").replace("_", "").isalnum():
            raise ValueError("launcher must be a portable non-empty identifier")
        object.__setattr__(self, "launcher", launcher)
        object.__setattr__(
            self,
            "environment",
            {str(key): str(value) for key, value in sorted(self.environment.items())},
        )
        object.__setattr__(
            self, "executable_arguments", tuple(map(str, self.executable_arguments))
        )
        object.__setattr__(
            self, "launcher_command", tuple(map(str, self.launcher_command))
        )
        object.__setattr__(
            self, "launcher_arguments", tuple(map(str, self.launcher_arguments))
        )

    @property
    def ranks_per_node(self) -> int:
        return self.mpi_ranks // self.nodes

    @property
    def allocated_cpus(self) -> int:
        return self.mpi_ranks * self.cpus_per_rank

    @property
    def fingerprint(self) -> str:
        return _digest(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ranks_per_node"] = self.ranks_per_node
        payload["allocated_cpus"] = self.allocated_cpus
        payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True)
class DAGNode:
    node_id: str
    kind: str
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.kind.strip():
            raise ValueError("DAG nodes require node_id and kind")
        if self.node_id in self.depends_on:
            raise ValueError("a DAG node cannot depend on itself")


class ScientificDecision(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class TechnicalValidation:
    status: str
    classification: str
    reasons: tuple[str, ...]
    parser_summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = self.status.upper()
        if status not in {"PASS", "FAIL", "REVIEW", "BLOCKED"}:
            raise ValueError("invalid technical validation status")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True)
class NodeResult:
    execution_state: str
    technical_validation: TechnicalValidation
    scientific_decision: ScientificDecision = ScientificDecision.NOT_EVALUATED

    def __post_init__(self) -> None:
        if not self.execution_state.strip():
            raise ValueError("node result requires execution_state")
        object.__setattr__(
            self, "scientific_decision", ScientificDecision(self.scientific_decision)
        )


@dataclass(frozen=True)
class Attempt:
    node_id: str
    attempt_id: str
    scientific_identity_sha256: str
    execution_spec_sha256: str
    started_at: str
    finished_at: str
    stdout: str
    stderr: str
    exit_code: int | None
    artifacts: Mapping[str, str]
    result: NodeResult
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.attempt_id.strip():
            raise ValueError("attempt requires node_id and attempt_id")
        object.__setattr__(
            self,
            "scientific_identity_sha256",
            _sha256(self.scientific_identity_sha256, "scientific_identity_sha256"),
        )
        object.__setattr__(
            self,
            "execution_spec_sha256",
            _sha256(self.execution_spec_sha256, "execution_spec_sha256"),
        )
        object.__setattr__(
            self,
            "artifacts",
            {
                str(path): _sha256(digest, f"artifact.{path}")
                for path, digest in sorted(self.artifacts.items())
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
