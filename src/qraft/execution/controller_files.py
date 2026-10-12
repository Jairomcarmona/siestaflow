"""Durable private IPC and path checks for the ADR-017 controller launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
from typing import Any, Mapping

from .controller_contracts import parse_controller_json


def contained_path(root: Path, relative: str) -> Path:
    posix, windows = PurePosixPath(relative), PureWindowsPath(relative)
    if (not relative or "\x00" in relative or "\\" in relative or posix.is_absolute()
            or windows.drive or ".." in posix.parts):
        raise ValueError("unsafe controller relative path")
    target = root.joinpath(*posix.parts)
    # State and evidence are never redirected through symlinks outside the run.
    target.resolve().relative_to(root.resolve())
    return target


def atomic_controller_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode() + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".controller-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_controller_json(path: Path) -> dict[str, Any]:
    return parse_controller_json(path.read_bytes())
