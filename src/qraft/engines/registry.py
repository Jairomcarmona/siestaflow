"""Installed engine inspection metadata, separate from environment probes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


VersionParser = Callable[[str], str | None]


@dataclass(frozen=True)
class RegisteredEngine:
    """External executable metadata declared by an engine integration."""

    name: str
    default_executable: str
    version_arguments: tuple[str, ...]
    version_parser: VersionParser


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, RegisteredEngine] = {}

    def register(self, engine: RegisteredEngine, *, replace: bool = False) -> None:
        name = engine.name.strip().casefold()
        if not name:
            raise ValueError("engine name must be non-empty")
        if name in self._engines and not replace:
            raise ValueError(f"engine already registered: {name}")
        self._engines[name] = engine

    def require(self, name: str) -> RegisteredEngine:
        normalized = name.strip().casefold()
        try:
            return self._engines[normalized]
        except KeyError as exc:
            raise ValueError(
                f"unknown engine: {name}; available: {', '.join(self.names())}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._engines))


def _siesta_version(output: str) -> str | None:
    match = re.search(r"^\s*(?:Siesta\s+)?Version\s*:?\s*(\S+)", output, re.I | re.M)
    return match.group(1) if match else None


engine_registry = EngineRegistry()
engine_registry.register(RegisteredEngine(
    name="siesta",
    default_executable="siesta",
    version_arguments=("--version",),
    version_parser=_siesta_version,
))
