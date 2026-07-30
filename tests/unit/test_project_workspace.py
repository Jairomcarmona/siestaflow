from pathlib import Path

import pytest

from siestaflow.errors import AlreadyExistsError
from siestaflow.filesystem import RealFileSystem
from siestaflow.models import ProjectManifest
from siestaflow.project import ProjectManager


def test_project_manifest_and_attempts_never_overwrite(tmp_path: Path):
    manager = ProjectManager(RealFileSystem())
    manifest = ProjectManifest("PROJECT_001", "Test project")
    root = manager.create(tmp_path, manifest)

    assert manager.load(root) == manifest
    with pytest.raises(AlreadyExistsError):
        manager.create(tmp_path, manifest)

