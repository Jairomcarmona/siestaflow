"""Shared application API for the non-interactive CLI and ``qraft>`` REPL."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .environment_inspection import EnvironmentInspector, EnvironmentReport, ProbeStatus
from .errors import PreflightError
from .execution.adapters import launcher_registry
from .execution_profiles import ExecutionProfile, ProfileStore
from .output import OutputContributor
from .protocols.single_fdf import (
    build_fdf_plan, execute_fdf_plan, resolve_execution_spec,
)


PlanFunction = Callable[..., dict[str, Any]]
RunFunction = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ProtocolAdapter:
    name: str
    planner: PlanFunction
    runner: RunFunction
    help: str
    engine: str
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
    "siesta",
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
        environment_inspector: EnvironmentInspector | None = None,
    ) -> None:
        self.configuration = configuration or ApplicationConfiguration()
        self.profile_store = profile_store or ProfileStore()
        self.protocols = protocols or protocol_registry
        self.environment_inspector = environment_inspector or EnvironmentInspector()

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

    def profiles(self) -> tuple[dict[str, str], ...]:
        return self.profile_store.list()

    def profile(self, reference: str | Path | None = None) -> dict[str, Any]:
        selected = reference if reference is not None else self.configuration.profile
        if selected is None:
            raise ValueError("no execution profile selected")
        profile = self.profile_store.load(selected)
        return {
            "name": profile.name,
            "source": str(profile.source) if profile.source else None,
            "scheduler": profile.scheduler,
            "execution": profile.execution_layer(),
            "module_commands": list(profile.module_commands),
            "scheduler_settings": dict(profile.scheduler_settings),
            "valid": True,
        }

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
        preflight_callback: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        fdf, protocol, profile, overrides = self._resolved_inputs(command_overrides)
        preview = self.plan(command_overrides=command_overrides)
        profile_metadata = preview["profile"]
        preflight = self._preflight(preview)
        if preflight_callback is not None:
            preflight_callback(preflight)
        if preflight["status"] != "PASS":
            failed = ", ".join(
                item["name"] for item in preflight["checks"] if item["status"] != "PASS"
            )
            raise PreflightError(f"preflight blocked execution: {failed}", preflight)
        self._save_session(overrides, profile)
        result = protocol.runner(
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
        result["preflight"] = preflight
        return result

    def environment(
        self, *, command_overrides: Mapping[str, Any] | None = None
    ) -> EnvironmentReport:
        protocol = self.protocols.require(self.configuration.protocol)
        profile_error: str | None = None
        try:
            profile = self._profile()
        except (OSError, ValueError, RuntimeError) as exc:
            profile = None
            profile_error = str(exc)
        overrides = dict(self.configuration.overrides)
        overrides.update({
            key: value for key, value in dict(command_overrides or {}).items()
            if value is not None
        })
        spec, _ = resolve_execution_spec(
            profile=profile.execution_layer() if profile else None,
            project_config=self.configuration.project_config,
            recipe=self.configuration.recipe,
            overrides=overrides,
        )
        if profile:
            profile.validate_spec(spec)
        scheduler = (
            profile.scheduler if profile else launcher_registry.require(spec.launcher).scheduler
        )
        config_paths = [*self.profile_store.search_roots]
        config_paths.extend(
            path for path in (self.configuration.project_config, self.configuration.recipe)
            if path is not None
        )
        return self.environment_inspector.inspect(
            engine_name=protocol.engine,
            engine_executable=spec.executable,
            launcher_name=spec.launcher,
            launcher_command=spec.launcher_command,
            scheduler_name=scheduler,
            workspace=self.configuration.runs_root.resolve().parent,
            profile_name=(
                profile.name if profile else
                str(self.configuration.profile) if self.configuration.profile else None
            ),
            profile_valid=profile_error is None,
            profile_detail=(
                profile_error or str(profile.source)
                if profile and profile.source else profile_error
            ),
            config_paths=config_paths,
        )

    def config(
        self, *, command_overrides: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        profile = self._profile()
        overrides = dict(self.configuration.overrides)
        overrides.update({
            key: value for key, value in dict(command_overrides or {}).items()
            if value is not None
        })
        spec, provenance = resolve_execution_spec(
            profile=profile.execution_layer() if profile else None,
            project_config=self.configuration.project_config,
            recipe=self.configuration.recipe,
            overrides=overrides,
        )
        if profile:
            profile.validate_spec(spec)
        scheduler = (
            profile.scheduler if profile else launcher_registry.require(spec.launcher).scheduler
        )
        return {
            "precedence": [
                "package defaults", "user config", "project config", "profile",
                "recipe", "REPL overrides", "command overrides",
            ],
            "active_profile": profile.name if profile else None,
            "profile_source": str(profile.source) if profile and profile.source else None,
            "protocol": self.configuration.protocol,
            "engine": self.protocols.require(self.configuration.protocol).engine,
            "scheduler": scheduler,
            "execution": spec.to_dict(),
            "sources": provenance,
            "workspace": str(self.configuration.runs_root.resolve().parent),
            "runs_root": str(self.configuration.runs_root.resolve()),
            "project_config": (
                str(self.configuration.project_config.resolve())
                if self.configuration.project_config else None
            ),
            "recipe": str(self.configuration.recipe.resolve()) if self.configuration.recipe else None,
        }

    def validate(
        self, *, command_overrides: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._preflight(self.plan(command_overrides=command_overrides))

    def _preflight(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        report = self.environment(command_overrides={
            key: value for key, value in plan["execution_spec"].items()
            if key not in {
                "fingerprint", "ranks_per_node", "allocated_cpus", "schema_version",
            }
        })
        selected_launcher = next(
            item for item in report.launchers
            if item.name.startswith("launcher:selected:")
        )
        acceptable = {ProbeStatus.AVAILABLE, ProbeStatus.NOT_REQUIRED}
        checks = (
            ("Input", True, str(plan["fdf"])),
            ("Engine", report.engine.status in acceptable, report.engine.detail),
            ("Launcher", selected_launcher.status in acceptable, selected_launcher.detail),
            ("Scheduler", report.scheduler.status in acceptable, report.scheduler.detail),
            ("Execution profile", report.profile.status in acceptable, report.profile.detail),
            ("Resources", True, f"{plan['execution_spec']['mpi_ranks']} ranks"),
            ("Workspace", report.filesystem.status in acceptable, report.filesystem.detail),
        )
        rendered = [
            {"name": name, "status": "PASS" if passed else "BLOCKED", "detail": detail}
            for name, passed, detail in checks
        ]
        return {
            "status": "PASS" if all(item[1] for item in checks) else "BLOCKED",
            "checks": rendered,
            "environment": report.to_dict(),
            "execution_fingerprint": plan["execution_spec"]["fingerprint"],
        }

    def _save_session(
        self, overrides: Mapping[str, Any], profile: ExecutionProfile | None
    ) -> None:
        root = self.configuration.runs_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = root / "session.json"
        temporary = root / ".session.json.tmp"
        payload = {
            "schema_version": "1.0",
            "fdf": str(self.configuration.fdf.resolve()) if self.configuration.fdf else None,
            "profile": (
                str(profile.source) if profile and profile.source
                else str(self.configuration.profile) if self.configuration.profile else None
            ),
            "protocol": self.configuration.protocol,
            "pseudo_manifest": (
                str(self.configuration.pseudo_manifest.resolve())
                if self.configuration.pseudo_manifest else None
            ),
            "project_config": (
                str(self.configuration.project_config.resolve())
                if self.configuration.project_config else None
            ),
            "recipe": str(self.configuration.recipe.resolve()) if self.configuration.recipe else None,
            "runs_root": str(root),
            "overrides": dict(overrides),
        }
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)

    @classmethod
    def from_session(cls, runs_root: Path) -> "QraftApplication":
        path = runs_root.resolve() / "session.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"no resumable QRAFT session at {path}; pass an FDF or use --runs-root"
            )
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != "1.0":
            raise ValueError("unsupported QRAFT session schema")
        return cls(ApplicationConfiguration(
            fdf=Path(value["fdf"]) if value.get("fdf") else None,
            profile=value.get("profile"),
            protocol=str(value.get("protocol", "single_fdf")),
            pseudo_manifest=(
                Path(value["pseudo_manifest"]) if value.get("pseudo_manifest") else None
            ),
            project_config=(
                Path(value["project_config"]) if value.get("project_config") else None
            ),
            recipe=Path(value["recipe"]) if value.get("recipe") else None,
            runs_root=Path(value.get("runs_root", runs_root)),
            overrides=dict(value.get("overrides", {})),
        ))

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


def render_config(config: Mapping[str, Any]) -> str:
    execution = config["execution"]
    sources = config["sources"]
    lines = ["QRAFT CONFIGURATION", "", f"Profile    : {config['active_profile'] or 'none'}"]
    for label, key in (
        ("Engine", "engine"), ("Scheduler", None), ("Launcher", "launcher"),
        ("Partition", "partition"), ("Nodes", "nodes"), ("MPI ranks", "mpi_ranks"),
        ("CPUs/rank", "cpus_per_rank"), ("Walltime", "walltime_seconds"),
    ):
        if key == "engine":
            value, source = config["engine"], "protocol"
        elif key is None:
            value = config["scheduler"]
            source = "profile/launcher"
        else:
            value, source = execution[key], sources.get(key, "defaults")
        lines.append(f"{label:<11}: {value}  [{source}]")
    lines.extend((f"Workspace  : {config['workspace']}", f"Runs root  : {config['runs_root']}"))
    return "\n".join(lines)


def render_preflight(report: Mapping[str, Any]) -> str:
    lines = ["PRE-FLIGHT", ""]
    for item in report["checks"]:
        lines.append(f"{item['name']:<24} {item['status']}")
    lines.extend(("", "Starting campaign..." if report["status"] == "PASS" else "Execution blocked."))
    return "\n".join(lines)
