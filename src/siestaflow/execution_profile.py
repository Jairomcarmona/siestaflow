"""Strict external execution profiles for prepared Slurm run packages."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .contracts import contract_sha256
from .contracts.workflow import require_local_id
from .project_packages import load_structured


_SAFE_DIRECTIVE = re.compile(r"^[A-Za-z0-9_.:+-]+$")
_SAFE_MODULE = re.compile(r"^[A-Za-z0-9._/+:-]+$")
_SAFE_ENVIRONMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MEMORY = re.compile(r"^[1-9][0-9]*(?:[KMGT])?$", re.IGNORECASE)
_WALLTIME = re.compile(
    r"^(?:(?P<days>[0-9]+)-)?(?P<hours>[0-9]{1,2}):"
    r"(?P<minutes>[0-9]{2}):(?P<seconds>[0-9]{2})$"
)


@dataclass(frozen=True)
class SlurmExecutionProfile:
    profile_id: str
    partition: str
    account: str
    qos: str
    nodes: int
    total_cpus: int
    memory: str
    walltime: str
    max_parallel_steps: int
    shutdown_margin_seconds: int
    termination_grace_seconds: int
    module_commands: tuple[str, ...]
    siesta_executable: str
    executable_arguments: tuple[str, ...]
    launcher_kind: str
    launcher_command: tuple[str, ...]
    launcher_arguments: tuple[str, ...]
    launcher_bootstrap: str
    processes_per_node: int | None
    exclusive: bool
    environment: Mapping[str, str]
    max_attempts: int
    require_scf_converged: bool
    schema_version: str = "1.0"
    target: str = "slurm"

    def __post_init__(self) -> None:
        require_local_id(self.profile_id, field_name="profile_id")
        if self.schema_version != "1.0" or self.target != "slurm":
            raise ValueError("execution profile must use schema 1.0 and target slurm")
        for name in ("partition", "account", "qos"):
            value = str(getattr(self, name))
            if not _SAFE_DIRECTIVE.fullmatch(value):
                raise ValueError(f"unsafe or empty Slurm field: {name}")
        for name in (
            "nodes",
            "total_cpus",
            "max_parallel_steps",
            "max_attempts",
        ):
            _positive_integer(getattr(self, name), name)
        for name in (
            "shutdown_margin_seconds",
            "termination_grace_seconds",
        ):
            _nonnegative_integer(getattr(self, name), name)
        if not _MEMORY.fullmatch(self.memory):
            raise ValueError("memory must be a positive Slurm memory value")
        total_walltime = _walltime_seconds(self.walltime)
        if self.shutdown_margin_seconds >= total_walltime:
            raise ValueError("shutdown margin must be smaller than walltime")
        if self.termination_grace_seconds > self.shutdown_margin_seconds:
            raise ValueError(
                "termination grace cannot exceed the shutdown margin"
            )
        if not self.siesta_executable.strip():
            raise ValueError("siesta_executable must be non-empty")
        if self.launcher_kind not in {"srun", "hydra"}:
            raise ValueError("launcher kind must be srun or hydra")
        if not self.launcher_command or any(
            not item.strip() for item in self.launcher_command
        ):
            raise ValueError("launcher command must be non-empty")
        if self.launcher_bootstrap != "ssh":
            raise ValueError("the supported Hydra bootstrap is ssh")
        if self.launcher_kind == "hydra":
            if self.processes_per_node is None:
                raise ValueError("Hydra profiles require processes_per_node")
            _positive_integer(
                self.processes_per_node,
                "processes_per_node",
            )
            if self.nodes * self.processes_per_node != self.total_cpus:
                raise ValueError(
                    "Hydra allocation requires nodes * processes_per_node "
                    "to equal total_cpus"
                )
        elif self.processes_per_node is not None:
            _positive_integer(
                self.processes_per_node,
                "processes_per_node",
            )
        for command in self.module_commands:
            _validate_module_command(command)
        for name in self.environment:
            if not _SAFE_ENVIRONMENT.fullmatch(name):
                raise ValueError(f"unsafe environment variable name: {name}")

    @classmethod
    def load(cls, path: Path) -> "SlurmExecutionProfile":
        data = load_structured(path.expanduser().resolve())
        _exact_fields(
            data,
            {
                "schema_version",
                "profile_id",
                "target",
                "slurm",
                "allocation",
                "runtime",
                "task_policy",
            },
            "execution profile",
        )
        slurm = _mapping(data["slurm"], "slurm")
        allocation = _mapping(data["allocation"], "allocation")
        runtime = _mapping(data["runtime"], "runtime")
        policy = _mapping(data["task_policy"], "task_policy")
        _exact_fields(slurm, {"partition", "account", "qos"}, "slurm")
        _exact_fields(
            allocation,
            {
                "nodes",
                "total_cpus",
                "memory",
                "walltime",
                "max_parallel_steps",
                "shutdown_margin_seconds",
                "termination_grace_seconds",
            },
            "allocation",
        )
        _exact_fields(
            runtime,
            {
                "module_commands",
                "siesta_executable",
                "executable_arguments",
                "launcher",
                "exclusive",
                "environment",
            },
            "runtime",
        )
        _exact_fields(
            policy,
            {"max_attempts", "require_scf_converged"},
            "task_policy",
        )
        launcher = _mapping(runtime["launcher"], "runtime.launcher")
        _exact_fields(
            launcher,
            {
                "kind",
                "command",
                "arguments",
                "bootstrap",
                "processes_per_node",
            },
            "runtime.launcher",
        )
        modules = _string_list(
            runtime["module_commands"], "runtime.module_commands"
        )
        executable_arguments = _string_list(
            runtime["executable_arguments"],
            "runtime.executable_arguments",
        )
        launcher_command = _string_list(
            launcher["command"], "runtime.launcher.command"
        )
        launcher_arguments = _string_list(
            launcher["arguments"], "runtime.launcher.arguments"
        )
        environment_raw = _mapping(
            runtime["environment"], "runtime.environment"
        )
        if not isinstance(runtime["exclusive"], bool):
            raise ValueError("runtime.exclusive must be boolean")
        if not isinstance(policy["require_scf_converged"], bool):
            raise ValueError(
                "task_policy.require_scf_converged must be boolean"
            )
        processes = launcher["processes_per_node"]
        if processes is not None and (
            isinstance(processes, bool) or not isinstance(processes, int)
        ):
            raise ValueError("processes_per_node must be an integer or null")
        return cls(
            schema_version=str(data["schema_version"]),
            profile_id=str(data["profile_id"]),
            target=str(data["target"]),
            partition=str(slurm["partition"]),
            account=str(slurm["account"]),
            qos=str(slurm["qos"]),
            nodes=_integer(allocation["nodes"], "allocation.nodes"),
            total_cpus=_integer(
                allocation["total_cpus"], "allocation.total_cpus"
            ),
            memory=str(allocation["memory"]),
            walltime=str(allocation["walltime"]),
            max_parallel_steps=_integer(
                allocation["max_parallel_steps"],
                "allocation.max_parallel_steps",
            ),
            shutdown_margin_seconds=_integer(
                allocation["shutdown_margin_seconds"],
                "allocation.shutdown_margin_seconds",
            ),
            termination_grace_seconds=_integer(
                allocation["termination_grace_seconds"],
                "allocation.termination_grace_seconds",
            ),
            module_commands=modules,
            siesta_executable=str(runtime["siesta_executable"]),
            executable_arguments=executable_arguments,
            launcher_kind=str(launcher["kind"]).casefold(),
            launcher_command=launcher_command,
            launcher_arguments=launcher_arguments,
            launcher_bootstrap=str(launcher["bootstrap"]),
            processes_per_node=processes,
            exclusive=runtime["exclusive"],
            environment={
                str(name): str(value)
                for name, value in environment_raw.items()
            },
            max_attempts=_integer(
                policy["max_attempts"], "task_policy.max_attempts"
            ),
            require_scf_converged=policy["require_scf_converged"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "target": self.target,
            "slurm": {
                "partition": self.partition,
                "account": self.account,
                "qos": self.qos,
            },
            "allocation": {
                "nodes": self.nodes,
                "total_cpus": self.total_cpus,
                "memory": self.memory,
                "walltime": self.walltime,
                "max_parallel_steps": self.max_parallel_steps,
                "shutdown_margin_seconds": self.shutdown_margin_seconds,
                "termination_grace_seconds": (
                    self.termination_grace_seconds
                ),
            },
            "runtime": {
                "module_commands": list(self.module_commands),
                "siesta_executable": self.siesta_executable,
                "executable_arguments": list(self.executable_arguments),
                "launcher": {
                    "kind": self.launcher_kind,
                    "command": list(self.launcher_command),
                    "arguments": list(self.launcher_arguments),
                    "bootstrap": self.launcher_bootstrap,
                    "processes_per_node": self.processes_per_node,
                },
                "exclusive": self.exclusive,
                "environment": dict(self.environment),
            },
            "task_policy": {
                "max_attempts": self.max_attempts,
                "require_scf_converged": self.require_scf_converged,
            },
        }

    @property
    def sha256(self) -> str:
        return contract_sha256(self.to_dict())

    def resolved(
        self,
        *,
        partition: str,
        account: str,
        qos: str,
        nodes: int,
        ranks_per_node: int,
        walltime: str,
    ) -> "SlurmExecutionProfile":
        """Return an immutable run-specific profile without changing science."""
        if self.launcher_kind == "hydra":
            processes_per_node: int | None = ranks_per_node
        else:
            processes_per_node = self.processes_per_node
        return replace(
            self,
            profile_id=f"{self.profile_id}-resolved",
            partition=partition,
            account=account,
            qos=qos,
            nodes=nodes,
            total_cpus=nodes * ranks_per_node,
            walltime=walltime,
            processes_per_node=processes_per_node,
        )


def _validate_module_command(command: str) -> None:
    tokens = command.split()
    if tokens == ["module", "purge"]:
        return
    if (
        len(tokens) >= 3
        and tokens[:2] == ["module", "load"]
        and all(_SAFE_MODULE.fullmatch(item) for item in tokens[2:])
    ):
        return
    raise ValueError(
        "module_commands permits only 'module purge' or safe 'module load ...'"
    )


def _walltime_seconds(value: str) -> int:
    match = _WALLTIME.fullmatch(value)
    if match is None:
        raise ValueError("walltime must use [D-]HH:MM:SS")
    days = int(match.group("days") or 0)
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    if minutes >= 60 or seconds >= 60 or (days and hours >= 24):
        raise ValueError("walltime contains an invalid time component")
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError("walltime must be positive")
    return total


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{location} must be a mapping")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    location: str,
) -> None:
    if set(value) != expected:
        difference = sorted(set(value) ^ expected)
        raise ValueError(f"{location} fields mismatch: {difference}")


def _string_list(value: Any, location: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{location} must be a list of non-empty strings")
    return tuple(value)


def _integer(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{location} must be an integer")
    return value


def _positive_integer(value: Any, location: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{location} must be a positive integer")


def _nonnegative_integer(value: Any, location: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{location} must be a nonnegative integer")
