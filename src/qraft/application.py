"""Shared application API for the non-interactive CLI and ``qraft>`` REPL."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .execution.adapters import launcher_registry
from .execution_profiles import ExecutionProfile, ProfileStore
from .output import OutputContributor
from .protocols.single_fdf import build_fdf_plan, execute_fdf_plan


PlanFunction = Callable[..., dict[str, Any]]
RunFunction = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ProtocolAdapter:
    name: str
    planner: PlanFunction
    runner: RunFunction
    help: str
    accepted_parameters: tuple[str, ...] = ()
    output_contributor: type[OutputContributor] | None = None


class ProtocolRegistry:
    def __init__(self) -> None:
        self._protocols: dict[str, ProtocolAdapter] = {}

    def register(self, adapter: ProtocolAdapter, *, replace: bool = False) -> None:
        name = str(adapter.name).strip().casefold()
        if not name:
            raise ValueError("protocol name must be non-empty")
        if name in self._protocols and not replace:
            raise ValueError(f"protocol already registered: {name}")
        self._protocols[name] = adapter

    def require(self, name: str) -> ProtocolAdapter:
        normalized = str(name).strip().casefold()
        try:
            return self._protocols[normalized]
        except KeyError as exc:
            raise ValueError(
                f"unknown protocol: {name}; available: {', '.join(self.names())}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._protocols))


protocol_registry = ProtocolRegistry()
protocol_registry.register(ProtocolAdapter(
    "single_fdf", build_fdf_plan, execute_fdf_plan,
    "validate, plan and execute one SIESTA FDF",
    accepted_parameters=(
        "fdf", "profile", "partition", "nodes", "mpi_ranks",
        "cpus_per_rank", "launcher", "executable", "walltime_seconds",
    ),
))


@dataclass
class ApplicationConfiguration:
    fdf: Path | None = None
    profile: str | Path | None = None
    protocol: str = "single_fdf"
    campaign: str | None = None
    pseudo_manifest: Path | None = None
    project_config: Path | None = None
    recipe: Path | None = None
    runs_root: Path = Path(".qraft-runs")
    overrides: dict[str, Any] = field(default_factory=dict)


class QraftApplication:
    """Resolve and execute commands once, regardless of their user interface."""

    def __init__(
        self, configuration: ApplicationConfiguration | None = None, *,
        profile_store: ProfileStore | None = None,
        protocols: ProtocolRegistry | None = None,
    ) -> None:
        self.configuration = configuration or ApplicationConfiguration()
        self.profile_store = profile_store or ProfileStore()
        self.protocols = protocols or protocol_registry

    def reset(self) -> None:
        self.configuration = ApplicationConfiguration()

    def set_value(self, name: str, value: Any) -> None:
        normalized = name.strip().replace("-", "_").casefold()
        if normalized == "fdf":
            self.configuration.fdf = Path(value)
        elif normalized == "profile":
            self.configuration.profile = value
        elif normalized == "protocol":
            self.protocols.require(str(value))
            self.configuration.protocol = str(value).casefold()
        elif normalized == "campaign":
            self.configuration.campaign = str(value)
        elif normalized == "runs_root":
            self.configuration.runs_root = Path(value)
        elif normalized in {
            "partition", "launcher", "executable", "nodes", "mpi_ranks",
            "cpus_per_rank", "memory_mb", "walltime_seconds",
            "executable_arguments", "launcher_command", "launcher_arguments",
            "environment",
        }:
            if normalized in {"nodes", "mpi_ranks", "cpus_per_rank", "memory_mb", "walltime_seconds"}:
                value = int(value)
            if normalized == "launcher":
                launcher_registry.require(str(value))
                value = str(value).casefold()
            self.configuration.overrides[normalized] = value
        else:
            raise ValueError(f"unknown QRAFT setting: {name}")

    def unset(self, name: str) -> None:
        normalized = name.strip().replace("-", "_").casefold()
        if normalized in {"fdf", "profile", "campaign"}:
            setattr(self.configuration, normalized, None)
        elif normalized == "protocol":
            self.configuration.protocol = "single_fdf"
        elif normalized == "runs_root":
            self.configuration.runs_root = Path(".qraft-runs")
        else:
            self.configuration.overrides.pop(normalized, None)

    def _profile(self) -> ExecutionProfile | None:
        reference = self.configuration.profile
        return self.profile_store.load(reference) if reference is not None else None

    def _resolved_inputs(
        self, command_overrides: Mapping[str, Any] | None = None
    ) -> tuple[Path, ProtocolAdapter, ExecutionProfile | None, dict[str, Any]]:
        if self.configuration.fdf is None:
            raise ValueError("no FDF selected; use fdf PATH or pass an FDF to the command")
        protocol = self.protocols.require(self.configuration.protocol)
        profile = self._profile()
        overrides = dict(self.configuration.overrides)
        overrides.update({
            key: value for key, value in dict(command_overrides or {}).items()
            if value is not None
        })
        return self.configuration.fdf, protocol, profile, overrides

    def plan(
        self, *, command_overrides: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        fdf, protocol, profile, overrides = self._resolved_inputs(command_overrides)
        result = protocol.planner(
            fdf,
            pseudo_manifest=self.configuration.pseudo_manifest,
            profile=profile.execution_layer() if profile else None,
            project_config=self.configuration.project_config,
            recipe=self.configuration.recipe,
            overrides=overrides,
        )
        if profile:
            from .core import ExecutionSpec

            payload = dict(result["execution_spec"])
            spec = ExecutionSpec(**{
                key: value for key, value in payload.items()
                if key not in {"fingerprint", "ranks_per_node", "allocated_cpus"}
            })
            profile.validate_spec(spec)
            result["profile"] = {
                "name": profile.name,
                "scheduler": profile.scheduler,
                "source": str(profile.source) if profile.source else None,
            }
        else:
            result["profile"] = {
                "name": None,
                "scheduler": launcher_registry.require(
                    str(result["execution_spec"]["launcher"])
                ).scheduler,
                "source": None,
            }
        result["submitted"] = False
        return result

    def run(
        self, *, command_overrides: Mapping[str, Any] | None = None,
        force_new_attempt: bool = False, invocation: str | None = None,
    ) -> dict[str, Any]:
        fdf, protocol, profile, overrides = self._resolved_inputs(command_overrides)
        if profile:
            preview = self.plan(command_overrides=command_overrides)
            profile_metadata = preview["profile"]
        else:
            preview = self.plan(command_overrides=command_overrides)
            profile_metadata = preview["profile"]
        return protocol.runner(
            fdf,
            pseudo_manifest=self.configuration.pseudo_manifest,
            profile=profile.execution_layer() if profile else None,
            project_config=self.configuration.project_config,
            recipe=self.configuration.recipe,
            overrides=overrides,
            runs_root=self.configuration.runs_root,
            force_new_attempt=force_new_attempt,
            invocation=invocation or self.invocation("run", command_overrides),
            profile_metadata=profile_metadata,
        )

    def invocation(
        self, action: str, command_overrides: Mapping[str, Any] | None = None
    ) -> str:
        values = dict(command_overrides or {})
        tokens = ["qraft", action]
        if self.configuration.fdf is not None:
            tokens.append(str(self.configuration.fdf))
        for key, value in values.items():
            if value is not None:
                tokens.extend((f"--{key.replace('_', '-')}", str(value)))
        return shlex.join(tokens)

    def show(self, *, resolved: bool = False) -> dict[str, Any]:
        active = {
            "fdf": str(self.configuration.fdf) if self.configuration.fdf else None,
            "profile": str(self.configuration.profile) if self.configuration.profile else None,
            "protocol": self.configuration.protocol,
            "campaign": self.configuration.campaign,
            "runs_root": str(self.configuration.runs_root),
            "overrides": dict(self.configuration.overrides),
            "state": "CONFIGURED" if self.configuration.fdf else "UNCONFIGURED",
        }
        if not resolved or self.configuration.fdf is None:
            return active
        plan = self.plan()
        return {
            **active,
            "execution": plan["execution_spec"],
            "profile_resolved": plan["profile"],
            "scientific_identity": plan["scientific_identity"]["fingerprint"],
        }

    def status(self) -> dict[str, Any]:
        states: list[dict[str, Any]] = []
        root = self.configuration.runs_root.resolve()
        if root.is_dir():
            for path in sorted(root.glob("*/state.json")):
                try:
                    states.append({"path": str(path), **json.loads(path.read_text(encoding="utf-8"))})
                except (OSError, json.JSONDecodeError, TypeError):
                    states.append({"path": str(path), "technical_status": "UNREADABLE"})
        return {"root": str(root), "states": states}

    def attempts(self) -> tuple[dict[str, Any], ...]:
        root = self.configuration.runs_root.resolve()
        attempts: list[dict[str, Any]] = []
        if root.is_dir():
            for path in sorted(root.glob("*/*/attempt.json")):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    attempts.append({
                        "attempt_id": value.get("attempt_id"),
                        "node_id": value.get("node_id"),
                        "exit_code": value.get("exit_code"),
                        "path": str(path),
                    })
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
        return tuple(attempts)

    def errors(self) -> tuple[dict[str, Any], ...]:
        path = self.configuration.runs_root.resolve() / "events.jsonl"
        errors: list[dict[str, Any]] = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = str(value.get("event", ""))
                if any(token in event for token in ("FAIL", "ERROR", "BLOCK")):
                    errors.append(value)
        return tuple(errors)


def render_plan(plan: Mapping[str, Any]) -> str:
    execution = plan["execution_spec"]
    profile = plan.get("profile", {})
    lines = [
        "DAG",
        *(f"  {node['node_id']} <- {','.join(node['depends_on']) or '-'}" for node in plan["dag"]),
        "",
        "Execution",
        f"  Engine    : SIESTA",
        f"  Scheduler : {profile.get('scheduler', 'local')}",
        f"  Launcher  : {execution['launcher']}",
        f"  Partition : {execution['partition']}",
        f"  Nodes     : {execution['nodes']}",
        f"  MPI ranks : {execution['mpi_ranks']}",
        "",
        "No jobs submitted.",
    ]
    return "\n".join(lines)
