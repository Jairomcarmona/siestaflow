"""Configured SIESTA command construction; no cluster assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EngineProfile:
    executable: str | None = None
    launcher_type: str | None = None
    command_template: str | None = None


class SiestaCommandBuilder:
    def build(self, input_path: Path, profile: EngineProfile) -> tuple[str, ...]:
        if not profile.executable:
            raise RuntimeError("SIESTA executable is not configured")
        if profile.command_template:
            return tuple(profile.command_template.format(executable=profile.executable, input=str(input_path)).split())
        return (profile.executable, str(input_path))
