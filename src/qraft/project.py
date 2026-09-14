"""Project identity and deterministic root creation."""

from __future__ import annotations

from pathlib import Path

from .errors import AlreadyExistsError, IntegrityError
from .filesystem import FileSystem, safe_join, validate_identifier
from .models import ProjectManifest, primitive


class ProjectManager:
    """Create/load a project without accepting raw path components."""

    MANIFEST = "project.json"

    def __init__(self, filesystem: FileSystem) -> None:
        self.fs = filesystem

    def create(self, parent: Path, manifest: ProjectManifest) -> Path:
        validate_identifier(manifest.project_id, field_name="project_id")
        root = safe_join(parent, manifest.project_id)
        if self.fs.exists(root):
            raise AlreadyExistsError(f"project already exists: {root}")
        self.fs.mkdir(root, parents=True, exist_ok=False)
        self.fs.atomic_write_json(root / self.MANIFEST, primitive(manifest))
        return root

    def load(self, root: Path) -> ProjectManifest:
        import json

        path = root.resolve() / self.MANIFEST
        try:
            data = json.loads(self.fs.read_text(path))
            return ProjectManifest(**data)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise IntegrityError(f"invalid project manifest: {path}") from exc

