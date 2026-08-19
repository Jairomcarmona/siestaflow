"""Portable user/project execution profiles for QRAFT installations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ImportError:  # pragma: no cover - QRAFT requires Python >= 3.11.
    tomllib = None  # type: ignore[assignment]

from .core import ExecutionSpec
from .execution.adapters import launcher_registry, scheduler_registry


def _positive(value: object | None, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _strings(value: object | None, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return tuple(value)


def _walltime(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and ":" in value:
        day_text, clock = (value.split("-", 1) if "-" in value else ("0", value))
        parts = clock.split(":")
        if len(parts) != 3 or any(not item.isdigit() for item in (day_text, *parts)):
            raise ValueError("walltime must use [D-]HH:MM:SS")
        days, hours, minutes, seconds = map(int, (day_text, *parts))
        if minutes >= 60 or seconds >= 60 or (days and hours >= 24):
            raise ValueError("walltime contains an invalid component")
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    return _positive(value, "walltime_seconds")


@dataclass(frozen=True)
class ExecutionProfile:
    """Optional external defaults; scientific identity is deliberately absent."""

    name: str
    scheduler: str = "local"
    launcher: str | None = None
    partition: str | None = None
    nodes: int | None = None
    cpus_per_node: int | None = None
    mpi_ranks: int | None = None
    cpus_per_rank: int | None = None
    memory_mb: int | None = None
    walltime_seconds: int | None = None
    executable: str | None = None
    executable_arguments: tuple[str, ...] = ()
    launcher_command: tuple[str, ...] = ()
    launcher_arguments: tuple[str, ...] = ()
    module_commands: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    scheduler_settings: Mapping[str, Any] = field(default_factory=dict)
    source: Path | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError(f"unsupported execution profile schema: {self.schema_version}")
        name = str(self.name).strip()
        if not name:
            raise ValueError("execution profile name must be non-empty")
        object.__setattr__(self, "name", name)
        scheduler = str(self.scheduler).strip().casefold()
        scheduler_registry.require(scheduler)
        object.__setattr__(self, "scheduler", scheduler)
        if self.launcher is not None:
            launcher = str(self.launcher).strip().casefold()
            launcher_registry.require(launcher)
            object.__setattr__(self, "launcher", launcher)
        for field_name in (
            "nodes", "cpus_per_node", "mpi_ranks", "cpus_per_rank",
            "memory_mb", "walltime_seconds",
        ):
            object.__setattr__(
                self, field_name, _positive(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "environment", {
            str(key): str(value) for key, value in self.environment.items()
        })
        object.__setattr__(self, "scheduler_settings", dict(self.scheduler_settings))
        if self.nodes and self.cpus_per_node and self.mpi_ranks:
            cpus_per_rank = self.cpus_per_rank or 1
            capacity = self.nodes * self.cpus_per_node // cpus_per_rank
            if self.mpi_ranks > capacity:
                raise ValueError(
                    f"profile MPI ranks exceed capacity: {self.mpi_ranks}>{capacity}"
                )

    @classmethod
    def load(cls, path: Path) -> "ExecutionProfile":
        if not path.is_file():
            raise FileNotFoundError(f"execution profile does not exist: {path}")
        if path.suffix.casefold() == ".toml":
            if tomllib is None:
                raise RuntimeError("TOML profiles require Python 3.11+")
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("execution profile must be a mapping")
        return cls.from_mapping(value, source=path.resolve())

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, source: Path | None = None
    ) -> "ExecutionProfile":
        data = dict(value)
        execution = data.get("execution")
        if execution is not None:
            if not isinstance(execution, Mapping):
                raise ValueError("profile execution section must be a mapping")
            execution_data = dict(execution)
        else:
            execution_data = dict(data.get("defaults", {}))
            for key in (
                "partition", "nodes", "cpus_per_node", "mpi_ranks",
                "cpus_per_rank", "memory_mb", "walltime_seconds", "executable",
                "executable_arguments", "launcher_command", "launcher_arguments",
                "environment",
            ):
                if key in data:
                    execution_data[key] = data[key]
            if "walltime" in data and "walltime_seconds" not in execution_data:
                execution_data["walltime_seconds"] = data["walltime"]
        launcher_value = data.get("launcher", execution_data.get("launcher"))
        launcher_name: str | None
        if isinstance(launcher_value, Mapping):
            launcher_name = str(launcher_value.get("name") or launcher_value.get("kind") or "") or None
            execution_data.setdefault("launcher_command", launcher_value.get("command", ()))
            execution_data.setdefault("launcher_arguments", launcher_value.get("arguments", ()))
        else:
            launcher_name = str(launcher_value) if launcher_value is not None else None
        engine = data.get("engine", {})
        if engine and not isinstance(engine, Mapping):
            raise ValueError("profile engine section must be a mapping")
        environment_section = data.get("environment_setup", {})
        if environment_section and not isinstance(environment_section, Mapping):
            raise ValueError("environment_setup must be a mapping")
        executable = execution_data.get("executable")
        executable_arguments = execution_data.get("executable_arguments")
        if isinstance(engine, Mapping):
            executable = engine.get("executable", executable)
            executable_arguments = engine.get("arguments", executable_arguments)
        variables = execution_data.get("environment", {})
        if isinstance(environment_section, Mapping):
            variables = environment_section.get("variables", variables)
        if variables is None:
            variables = {}
        if not isinstance(variables, Mapping):
            raise ValueError("profile environment variables must be a mapping")
        scheduler = str(
            data.get("scheduler")
            or (launcher_registry.require(launcher_name).scheduler if launcher_name else "local")
        )
        return cls(
            name=str(data.get("name") or data.get("profile_name") or data.get("profile_id") or (source.stem if source else "profile")),
            scheduler=scheduler,
            launcher=launcher_name,
            partition=execution_data.get("partition"),
            nodes=execution_data.get("nodes"),
            cpus_per_node=execution_data.get("cpus_per_node"),
            mpi_ranks=execution_data.get("mpi_ranks"),
            cpus_per_rank=execution_data.get("cpus_per_rank"),
            memory_mb=execution_data.get("memory_mb"),
            walltime_seconds=_walltime(execution_data.get("walltime_seconds")),
            executable=str(executable) if executable is not None else None,
            executable_arguments=_strings(executable_arguments, "executable_arguments"),
            launcher_command=_strings(execution_data.get("launcher_command"), "launcher_command"),
            launcher_arguments=_strings(execution_data.get("launcher_arguments"), "launcher_arguments"),
            module_commands=_strings(
                environment_section.get("module_commands") if isinstance(environment_section, Mapping) else data.get("module_commands"),
                "module_commands",
            ),
            environment={str(key): str(item) for key, item in variables.items()},
            scheduler_settings=dict(data.get("scheduler_settings", {})),
            source=source,
            schema_version=str(data.get("schema_version", "1.0")),
        )

    def execution_layer(self) -> dict[str, Any]:
        values = {
            "partition": self.partition,
            "nodes": self.nodes,
            "mpi_ranks": self.mpi_ranks,
            "cpus_per_rank": self.cpus_per_rank,
            "memory_mb": self.memory_mb,
            "launcher": self.launcher,
            "executable": self.executable,
            "walltime_seconds": self.walltime_seconds,
            "environment": dict(self.environment) or None,
            "executable_arguments": self.executable_arguments or None,
            "launcher_command": self.launcher_command or None,
            "launcher_arguments": self.launcher_arguments or None,
        }
        return {key: value for key, value in values.items() if value is not None}

    def validate_spec(self, spec: ExecutionSpec) -> None:
        launcher_registry.require(spec.launcher)
        if self.cpus_per_node:
            capacity = spec.nodes * self.cpus_per_node
            if spec.allocated_cpus > capacity:
                raise ValueError(
                    "resolved resources exceed profile capacity: "
                    f"{spec.allocated_cpus}>{capacity} CPUs"
                )


class ProfileStore:
    """Resolve explicit, project, then user profiles without cluster knowledge."""

    def __init__(
        self, *, project_root: Path | None = None, user_config_root: Path | None = None
    ) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()
        if user_config_root is None:
            xdg = os.environ.get("XDG_CONFIG_HOME")
            user_config_root = Path(xdg) if xdg else Path.home() / ".config"
        self.user_config_root = user_config_root.resolve()

    @property
    def search_roots(self) -> tuple[Path, ...]:
        return (
            self.project_root / ".qraft" / "profiles",
            self.user_config_root / "qraft" / "profiles",
        )

    def resolve(self, reference: str | Path) -> Path:
        explicit = Path(reference).expanduser()
        if explicit.is_file():
            return explicit.resolve()
        name = str(reference).strip()
        if not name or any(separator in name for separator in ("/", "\\")):
            raise FileNotFoundError(f"execution profile does not exist: {reference}")
        candidates = tuple(
            root / candidate
            for root in self.search_roots
            for candidate in (name, f"{name}.json", f"{name}.toml")
        )
        matches = tuple(path.resolve() for path in candidates if path.is_file())
        if not matches:
            searched = ", ".join(str(root) for root in self.search_roots)
            raise FileNotFoundError(
                f"execution profile not found: {name}; searched: {searched}"
            )
        return matches[0]

    def load(self, reference: str | Path) -> ExecutionProfile:
        return ExecutionProfile.load(self.resolve(reference))
