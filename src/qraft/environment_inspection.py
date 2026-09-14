"""Fast, read-only and adapter-driven inspection of an installed environment."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import __version__
from .engines.registry import EngineRegistry, engine_registry
from .execution.adapters import (
    LauncherRegistry, SchedulerRegistry, launcher_registry, scheduler_registry,
)
from .runtime_compatibility import (
    COMPATIBLE, INCOMPATIBLE, UNKNOWN, evaluate_runtime_compatibility,
)
from .runtime_evidence import RuntimeEvidenceProbe, observe_runtime_evidence


class ProbeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    COMPATIBLE = COMPATIBLE
    NOT_FOUND = "NOT_FOUND"
    NOT_REQUIRED = "NOT_REQUIRED"
    INVALID = "INVALID"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: ProbeStatus
    executable: str | None = None
    version: str | None = None
    detail: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        if not value["data"]:
            value.pop("data")
        return value


@dataclass(frozen=True)
class EnvironmentReport:
    qraft_version: str
    python_version: str
    platform: str
    installation_path: str
    engine: ProbeResult
    scheduler: ProbeResult
    launchers: tuple[ProbeResult, ...]
    profile: ProbeResult
    filesystem: ProbeResult
    compatibility: ProbeResult
    workspace: str
    config_paths: tuple[str, ...]

    @property
    def ready(self) -> bool:
        acceptable = {ProbeStatus.AVAILABLE, ProbeStatus.NOT_REQUIRED}
        selected_launcher = next(
            (item for item in self.launchers if item.name.startswith("launcher:selected:")),
            None,
        )
        return all((
            self.engine.status in acceptable,
            self.scheduler.status in acceptable,
            selected_launcher is not None and selected_launcher.status in acceptable,
            self.profile.status in acceptable,
            self.filesystem.status in acceptable,
            self.compatibility.status in {ProbeStatus.COMPATIBLE, ProbeStatus.UNKNOWN},
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "qraft": {
                "version": self.qraft_version,
                "python": self.python_version,
                "platform": self.platform,
                "installation": self.installation_path,
            },
            "engine": self.engine.to_dict(),
            "scheduler": self.scheduler.to_dict(),
            "launchers": [item.to_dict() for item in self.launchers],
            "profile": self.profile.to_dict(),
            "filesystem": self.filesystem.to_dict(),
            "compatibility": self.compatibility.to_dict(),
            "workspace": self.workspace,
            "config_paths": list(self.config_paths),
            "result": "READY" if self.ready else "INCOMPLETE",
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]
class EnvironmentInspector:
    """Inspect registered external capabilities without running scientific work."""

    def __init__(
        self, *, engines: EngineRegistry | None = None,
        launchers: LauncherRegistry | None = None,
        schedulers: SchedulerRegistry | None = None,
        which: Which = shutil.which, runner: Runner = subprocess.run,
        environ: Mapping[str, str] | None = None,
        runtime_evidence_probe: RuntimeEvidenceProbe | None = None,
    ) -> None:
        self.engines = engines or engine_registry
        self.launchers = launchers or launcher_registry
        self.schedulers = schedulers or scheduler_registry
        self._which = which
        self._runner = runner
        self._environ = dict(os.environ if environ is None else environ)
        self._runtime_evidence_probe = runtime_evidence_probe

    def inspect(
        self, *, engine_name: str, engine_executable: str,
        launcher_name: str, launcher_command: Sequence[str],
        scheduler_name: str, workspace: Path,
        profile_name: str | None = None, profile_valid: bool = True,
        profile_detail: str | None = None,
        config_paths: Sequence[Path] = (),
    ) -> EnvironmentReport:
        engine = self.engines.require(engine_name)
        engine_probe = self._external_probe(
            f"engine:{engine.name}", engine_executable or engine.default_executable,
            engine.version_arguments, parser=engine.version_parser,
        )
        selected = self.launchers.require(launcher_name)
        launcher_probes: list[ProbeResult] = []
        for name in self.launchers.names():
            adapter = self.launchers.require(name)
            command = (
                tuple(map(str, launcher_command))
                if name == selected.name and launcher_command else adapter.default_command
            )
            probe_name = (
                f"launcher:selected:{name}" if name == selected.name else f"launcher:{name}"
            )
            launcher_probes.append(self._adapter_probe(
                probe_name, command, adapter.version_arguments, adapter.probe_required,
            ))
        scheduler = self.schedulers.require(scheduler_name)
        scheduler_probe = self._scheduler_probe(scheduler)
        selected_launcher_probe = next(
            item for item in launcher_probes
            if item.name.startswith("launcher:selected:")
        )
        if self._runtime_evidence_probe is None:
            components, conflicts = observe_runtime_evidence(
                engine_probe.executable,
                selected_launcher_probe.executable,
                self._environ,
                which=self._which,
                runner=self._runner,
            )
        else:
            components, conflicts = self._runtime_evidence_probe(
                engine_probe.executable,
                selected_launcher_probe.executable,
                self._environ,
            )
        compatibility = evaluate_runtime_compatibility(components, conflicts)
        compatibility_probe = ProbeResult(
            "runtime:compatibility",
            ProbeStatus(compatibility["status"]),
            detail={
                COMPATIBLE: "selected runtime facts are compatible",
                INCOMPATIBLE: "explicit runtime evidence is contradictory",
                UNKNOWN: "runtime compatibility evidence is incomplete",
            }[compatibility["status"]],
            data=compatibility,
        )
        resolved_workspace = workspace.expanduser().resolve()
        writable = (
            resolved_workspace.is_dir()
            and os.access(resolved_workspace, os.R_OK | os.W_OK)
        )
        filesystem_probe = ProbeResult(
            "filesystem:workspace",
            ProbeStatus.AVAILABLE if writable else ProbeStatus.INVALID,
            detail=(
                f"readable and writable: {resolved_workspace}"
                if writable else f"missing or not writable: {resolved_workspace}"
            ),
        )
        profile_probe = ProbeResult(
            "profile",
            (ProbeStatus.AVAILABLE if profile_name and profile_valid else
             ProbeStatus.NOT_REQUIRED if not profile_name else ProbeStatus.INVALID),
            detail=profile_detail or profile_name or "no profile selected",
        )
        import qraft

        return EnvironmentReport(
            qraft_version=__version__,
            python_version=platform.python_version(),
            platform=f"{platform.system()} {platform.release()}".strip(),
            installation_path=str(Path(qraft.__file__).resolve().parent),
            engine=engine_probe,
            scheduler=scheduler_probe,
            launchers=tuple(launcher_probes),
            profile=profile_probe,
            filesystem=filesystem_probe,
            compatibility=compatibility_probe,
            workspace=str(resolved_workspace),
            config_paths=tuple(str(path.expanduser().resolve()) for path in config_paths),
        )

    def _adapter_probe(
        self, name: str, command: Sequence[str], version_arguments: Sequence[str],
        required: bool,
    ) -> ProbeResult:
        if not required:
            return ProbeResult(name, ProbeStatus.NOT_REQUIRED, detail="built into QRAFT")
        if not command:
            return ProbeResult(name, ProbeStatus.INVALID, detail="adapter has no command")
        return self._external_probe(name, str(command[0]), version_arguments)

    def _scheduler_probe(self, scheduler: Any) -> ProbeResult:
        if not scheduler.probe_required:
            return ProbeResult(
                f"scheduler:{scheduler.name}", ProbeStatus.NOT_REQUIRED,
                detail=scheduler.describe(),
            )
        for marker in scheduler.environment_markers:
            if self._environ.get(marker):
                return ProbeResult(
                    f"scheduler:{scheduler.name}", ProbeStatus.AVAILABLE,
                    detail=f"active environment marker: {marker}",
                )
        return self._adapter_probe(
            f"scheduler:{scheduler.name}", scheduler.command,
            scheduler.version_arguments, scheduler.probe_required,
        )

    def _external_probe(
        self, name: str, requested: str, version_arguments: Sequence[str],
        parser: Callable[[str], str | None] | None = None,
    ) -> ProbeResult:
        resolved = self._resolve(requested)
        if resolved is None:
            return ProbeResult(name, ProbeStatus.NOT_FOUND, detail=f"not found: {requested}")
        if not version_arguments:
            return ProbeResult(name, ProbeStatus.AVAILABLE, executable=resolved)
        try:
            result = self._runner(
                [resolved, *map(str, version_arguments)], capture_output=True,
                text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProbeResult(
                name, ProbeStatus.AVAILABLE, executable=resolved,
                detail=f"available; version unknown: {exc}",
            )
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        version = parser(output) if parser else self._first_line(output)
        detail = None if result.returncode == 0 else f"version probe exited {result.returncode}"
        return ProbeResult(
            name, ProbeStatus.AVAILABLE, executable=resolved,
            version=version, detail=detail,
        )

    def _resolve(self, requested: str) -> str | None:
        if any(separator in requested for separator in ("/", "\\")):
            path = Path(requested).expanduser()
            return str(path.resolve()) if path.is_file() else None
        return self._which(requested)

    @staticmethod
    def _first_line(output: str) -> str | None:
        return next((line.strip() for line in output.splitlines() if line.strip()), None)


def render_environment(report: EnvironmentReport) -> str:
    value = report.to_dict()
    selected_launcher = next(
        item for item in report.launchers if item.name.startswith("launcher:selected:")
    )
    return "\n".join((
        "QRAFT ENVIRONMENT", "", "QRAFT",
        f"  Version          : {report.qraft_version}",
        f"  Python           : {report.python_version}",
        f"  Platform         : {report.platform}",
        f"  Installation     : {report.installation_path}", "", "ENGINE",
        f"  Selected         : {report.engine.name.split(':', 1)[-1]}",
        f"  Executable       : {report.engine.executable or '-'}",
        f"  Version          : {report.engine.version or 'UNKNOWN'}",
        f"  Status           : {report.engine.status.value}", "", "SCHEDULER",
        f"  Selected         : {report.scheduler.name.split(':', 1)[-1]}",
        f"  Executable       : {report.scheduler.executable or '-'}",
        f"  Version          : {report.scheduler.version or 'UNKNOWN'}",
        f"  Status           : {report.scheduler.status.value}", "", "LAUNCHER",
        f"  Selected         : {selected_launcher.name.rsplit(':', 1)[-1]}",
        f"  Executable       : {selected_launcher.executable or '-'}",
        f"  Status           : {selected_launcher.status.value}", "", "COMPATIBILITY",
        f"  Runtime          : {report.compatibility.status.value}",
        f"  Detail           : {report.compatibility.detail or '-'}", "", "PROFILE",
        f"  Active           : {report.profile.detail or '-'}",
        f"  Status           : {report.profile.status.value}", "", "FILESYSTEM",
        f"  Workspace        : {report.workspace}",
        f"  Writable         : {'YES' if report.filesystem.status is ProbeStatus.AVAILABLE else 'NO'}",
        "", "RESULT",
        f"  Environment      : {value['result']}",
    ))
