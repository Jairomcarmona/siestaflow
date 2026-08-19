"""Explicit filesystem boundary with a zero-write dry-run implementation."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AlreadyExistsError, PathSafetyError


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def validate_identifier(value: str, *, field_name: str = "identifier") -> str:
    if not isinstance(value, str) or not value:
        raise PathSafetyError(f"{field_name} must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PathSafetyError(f"{field_name} contains control characters")
    if value in {".", ".."} or "..\\" in value or "../" in value:
        raise PathSafetyError(f"{field_name} contains traversal")
    if "/" in value or "\\" in value:
        raise PathSafetyError(f"{field_name} contains a path separator")
    if re.match(r"^[A-Za-z]:", value) or Path(value).is_absolute():
        raise PathSafetyError(f"{field_name} is absolute or drive-qualified")
    if value.endswith(".") or value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise PathSafetyError(f"{field_name} is unsafe on Windows")
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise PathSafetyError(f"{field_name} contains unsupported characters")
    return value


def safe_join(root: Path, *identifiers: str) -> Path:
    root_resolved = root.resolve()
    clean = [validate_identifier(item) for item in identifiers]
    candidate = root_resolved.joinpath(*clean).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PathSafetyError(f"resolved path escaped authorized root: {candidate}")
    return candidate


@dataclass(frozen=True)
class FileOperation:
    operation: str
    path: str
    detail: str = ""


class FileSystem(ABC):
    @abstractmethod
    def mkdir(self, path: Path, *, parents: bool = False, exist_ok: bool = False) -> None: ...

    @abstractmethod
    def write_text(self, path: Path, content: str, *, overwrite: bool = False) -> None: ...

    @abstractmethod
    def read_text(self, path: Path) -> str: ...

    @abstractmethod
    def copy(self, source: Path, destination: Path) -> None: ...

    @abstractmethod
    def remove(self, path: Path) -> None: ...

    @abstractmethod
    def exists(self, path: Path) -> bool: ...

    @abstractmethod
    def list_dir(self, path: Path) -> list[Path]: ...

    @abstractmethod
    def atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None: ...

    @abstractmethod
    def append_text(self, path: Path, content: str) -> None: ...


class RealFileSystem(FileSystem):
    """Real IO with no-overwrite defaults and durable atomic JSON replacement."""

    def mkdir(self, path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
        path.mkdir(parents=parents, exist_ok=exist_ok)

    def write_text(self, path: Path, content: str, *, overwrite: bool = False) -> None:
        mode = "w" if overwrite else "x"
        with path.open(mode, encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def copy(self, source: Path, destination: Path) -> None:
        if destination.exists():
            raise AlreadyExistsError(f"refusing to overwrite {destination}")
        shutil.copy2(source, destination)

    def remove(self, path: Path) -> None:
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()

    def exists(self, path: Path) -> bool:
        return path.exists()

    def list_dir(self, path: Path) -> list[Path]:
        return sorted(path.iterdir()) if path.is_dir() else []

    def atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
            except OSError:
                directory_fd = None  # Directory fsync is not available on all platforms.
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def append_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())


class DryRunFileSystem(FileSystem):
    """Read-through filesystem that records every mutation without performing it."""

    def __init__(self) -> None:
        self.operations: list[FileOperation] = []

    def _record(self, operation: str, path: Path, detail: str = "") -> None:
        self.operations.append(FileOperation(operation, str(path), detail))

    def mkdir(self, path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
        self._record("mkdir", path, f"parents={parents},exist_ok={exist_ok}")

    def write_text(self, path: Path, content: str, *, overwrite: bool = False) -> None:
        self._record("write_text", path, f"bytes={len(content.encode('utf-8'))},overwrite={overwrite}")

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def copy(self, source: Path, destination: Path) -> None:
        self._record("copy", destination, f"source={source}")

    def remove(self, path: Path) -> None:
        self._record("remove", path)

    def exists(self, path: Path) -> bool:
        return path.exists()

    def list_dir(self, path: Path) -> list[Path]:
        return sorted(path.iterdir()) if path.is_dir() else []

    def atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self._record("atomic_write_json", path, f"bytes={len(encoded.encode('utf-8'))}")

    def append_text(self, path: Path, content: str) -> None:
        self._record("append_text", path, f"bytes={len(content.encode('utf-8'))}")
