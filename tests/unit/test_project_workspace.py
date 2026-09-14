from pathlib import Path

import pytest

from qraft.errors import AlreadyExistsError
from qraft.filesystem import RealFileSystem
from qraft.models import ProjectManifest
from qraft.project import ProjectManager


def test_project_manifest_and_attempts_never_overwrite(tmp_path: Path):
    manager = ProjectManager(RealFileSystem())
    manifest = ProjectManifest("PROJECT_001", "Test project")
    root = manager.create(tmp_path, manifest)

    assert manager.load(root) == manifest
    with pytest.raises(AlreadyExistsError):
        manager.create(tmp_path, manifest)

