"""Configurable SLURM preview renderer; it never submits jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class SlurmRenderStatus(str, Enum):
    PREVIEW_WITH_UNVERIFIED_PROFILE = "PREVIEW_WITH_UNVERIFIED_PROFILE"
    EXECUTABLE_AFTER_PROFILE_VERIFICATION = "EXECUTABLE_AFTER_PROFILE_VERIFICATION"


@dataclass(frozen=True)
class SlurmProfile:
    name: str = "YOLTLA_UNVERIFIED_FOR_SIESTA"
    verified_for_siesta: bool = False
    partition: str | None = None
    account: str | None = None
    qos: str | None = None
    nodes: int | None = None
    ntasks: int | None = None
    cpus_per_task: int | None = None
    memory: str | None = None
    walltime: str | None = None
    signal: str | None = None
    module_commands: tuple[str, ...] = ()
    launcher_command: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SlurmRenderResult:
    status: SlurmRenderStatus
    script: str
    missing_fields: tuple[str, ...]


class SlurmRenderer:
    REQUIRED = ("partition", "account", "nodes", "ntasks", "cpus_per_task", "walltime", "launcher_command")

    def render(
        self,
        profile: SlurmProfile,
        *,
        job_name: str,
        worker_command: str,
        stdout: str = "slurm-%j.out",
        stderr: str = "slurm-%j.err",
        controller_in_batch: bool = False,
    ) -> SlurmRenderResult:
        required = tuple(field for field in self.REQUIRED if not (controller_in_batch and field == "launcher_command"))
        missing = tuple(field for field in required if getattr(profile, field) is None)
        executable = profile.verified_for_siesta and not missing
        status = SlurmRenderStatus.EXECUTABLE_AFTER_PROFILE_VERIFICATION if executable else SlurmRenderStatus.PREVIEW_WITH_UNVERIFIED_PROFILE
        lines = ["#!/usr/bin/env bash", "# QRAFT M2 SLURM RENDER", f"# render_status: {status.value}", f"# profile: {profile.name}", f"#SBATCH --job-name={job_name}"]
        directives = {
            "partition": profile.partition, "account": profile.account, "qos": profile.qos,
            "nodes": profile.nodes, "ntasks": profile.ntasks, "cpus-per-task": profile.cpus_per_task,
            "mem": profile.memory, "time": profile.walltime, "signal": profile.signal,
            "output": stdout, "error": stderr,
        }
        for key, value in directives.items():
            if value is None:
                marker = "REQUIRED_CONFIGURATION" if key.replace("-", "_") in self.REQUIRED else "OPTIONAL_CONFIGURATION"
                lines.append(f"# {marker}: {key}=null")
            else:
                lines.append(f"#SBATCH --{key}={value}")
        lines.extend(("", "set -euo pipefail", ""))
        if executable:
            lines.extend((
                '[[ -n "${SLURM_SUBMIT_DIR:-}" ]] || {',
                '  echo "SLURM_SUBMIT_DIR_NOT_SET" >&2',
                "  exit 2",
                "}",
                '[[ -d "$SLURM_SUBMIT_DIR" ]] || {',
                '  echo "INVALID_SLURM_SUBMIT_DIR:$SLURM_SUBMIT_DIR" >&2',
                "  exit 2",
                "}",
                'ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)',
                "export ROOT",
                '[[ -f "$ROOT/package_manifest.json" ]] || {',
                '  echo "INVALID_SLURM_SUBMIT_DIR:$ROOT" >&2',
                "  exit 2",
                "}",
                'mkdir -p "$ROOT/evidence" "$ROOT/results" "$ROOT/work"',
                'cd "$ROOT"',
                "# QRAFT_PACKAGE_ROOT_END",
                "",
            ))
        lines.extend(profile.module_commands or (("# module_commands: none declared",) if executable else ("# REQUIRED_CONFIGURATION: module_commands=[]",)))
        if executable:
            if controller_in_batch:
                lines.extend((
                    "# The controller already runs inside the batch allocation.",
                    "# Scientific calculations are the only commands launched with srun.",
                    worker_command,
                ))
            else:
                lines.append(f"{profile.launcher_command} {worker_command}")
        else:
            lines.extend((f"# launcher_command: {profile.launcher_command or 'null'}", f"# worker_command: {worker_command}", "echo REMOTE_PREFLIGHT_REQUIRES_CONFIGURATION >&2", "exit 2"))
        return SlurmRenderResult(status, "\n".join(lines) + "\n", missing)
