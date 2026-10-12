"""Explicit ADR-017 entrypoint resolution; never load or discover plugins."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sysconfig
from typing import Mapping, Sequence

from ..contracts import CapabilityDescriptor, CapabilityKind


@dataclass(frozen=True)
class ControllerExtension:
    distribution: str
    entrypoint: str
    inner_launchers: tuple[str, ...]
    resume: str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("unsupported qraft.controller metadata version")
        if not isinstance(self.distribution, str) or re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", self.distribution,
        ) is None:
            raise ValueError("controller distribution must be an explicit distribution name")
        if not isinstance(self.entrypoint, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", self.entrypoint,
        ) is None:
            raise ValueError("controller entrypoint must be a console_scripts name")
        if not isinstance(self.inner_launchers, tuple) or not self.inner_launchers:
            raise ValueError("controller must declare supported inner launchers")
        if any(item not in ("hydra", "openmpi") for item in self.inner_launchers):
            raise ValueError("unsupported controller inner launcher")
        if len(set(self.inner_launchers)) != len(self.inner_launchers):
            raise ValueError("duplicate controller inner launcher")
        if self.resume not in ("NATIVE_VERIFIED", "NONE"):
            raise ValueError("controller resume must be NATIVE_VERIFIED or NONE")

    @classmethod
    def from_descriptor(cls, descriptor: CapabilityDescriptor) -> ControllerExtension:
        if descriptor.kind not in (CapabilityKind.ENGINE, CapabilityKind.EXECUTABLE):
            raise ValueError("controller capability must be ENGINE or EXECUTABLE")
        value = descriptor.metadata.get("qraft.controller")
        names = {"schema_version", "distribution", "entrypoint", "inner_launchers", "resume"}
        if not isinstance(value, Mapping) or set(value) != names:
            raise ValueError("qraft.controller metadata fields are missing or unknown")
        if not isinstance(value["inner_launchers"], list):
            raise ValueError("controller inner_launchers must be a JSON array")
        return cls(value["distribution"], value["entrypoint"],
                   tuple(value["inner_launchers"]), value["resume"], value["schema_version"])


def resolve_controller_entrypoint(extension: ControllerExtension) -> Path:
    """Find only a declared console script owned by the installed distribution.

    Resolving entrypoint metadata must not import the entrypoint callable. The
    executable must be present in that distribution's installed RECORD at the
    running environment's scripts location; PATH never participates.
    """
    if os.name != "posix":
        raise ValueError("CONTROLLER_REQUIRES_POSIX")
    try:
        distribution = metadata.distribution(extension.distribution)
    except metadata.PackageNotFoundError as exc:
        raise ValueError("CONTROLLER_ENTRYPOINT_MISSING: distribution not installed") from exc
    points = [point for point in distribution.entry_points
              if point.group == "console_scripts" and point.name == extension.entrypoint]
    if len(points) != 1:
        raise ValueError("CONTROLLER_ENTRYPOINT_MISSING: declared console script not unique")
    executable = Path(sysconfig.get_path("scripts")) / extension.entrypoint
    executable = executable.resolve()
    recorded = any(
        Path(distribution.locate_file(item)).resolve() == executable
        for item in (distribution.files or ())
    )
    if not recorded or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("CONTROLLER_ENTRYPOINT_MISSING: installed executable missing")
    return executable


def validate_controller_command(
    command: Sequence[str], entrypoint: Path, reservation_path: str,
) -> tuple[str, ...]:
    """Bind the command to the resolved script and declared relative descriptor."""
    if isinstance(command, (str, bytes)) or any(not isinstance(arg, str) for arg in command):
        raise ValueError("controller command must be a sequence of strings")
    values = tuple(command)
    if len(values) < 3 or values[:3] != (
        str(entrypoint), "--qraft-reservation", reservation_path,
    ):
        raise ValueError("controller command disagrees with resolved entrypoint or descriptor")
    for arg in (reservation_path, *values[3:]):
        path_value = arg.split("=", 1)[-1]
        posix = PurePosixPath(path_value)
        windows = PureWindowsPath(path_value)
        if (not arg or "\x00" in arg or posix.is_absolute() or windows.drive
                or ".." in posix.parts or ".." in windows.parts):
            raise ValueError("controller arguments must not escape relative paths")
        if arg.startswith("--qraft-reservation"):
            raise ValueError("controller descriptor override is forbidden")
    return values
