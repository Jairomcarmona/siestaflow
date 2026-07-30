"""SIESTA artifact discovery with deny-by-default restart compatibility."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .models import ArtifactDescriptor


SUFFIXES = (".DM", ".XV", ".CG", ".HSX", ".WFSX", ".RHO", ".DRHO", ".STRUCT_OUT", ".bands", ".DOS", ".PDOS")


def discover_siesta_artifacts(workspace: Path, *, task_id: str, attempt_id: str) -> tuple[ArtifactDescriptor, ...]:
    found = []
    if not workspace.exists():
        return ()
    for path in sorted(item for item in workspace.rglob("*") if item.is_file()):
        suffix = next((candidate for candidate in SUFFIXES if path.name.endswith(candidate)), None)
        if suffix:
            found.append(ArtifactDescriptor(
                str(path), suffix.lstrip("."), path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(), task_id, attempt_id,
            ))
    return tuple(found)
