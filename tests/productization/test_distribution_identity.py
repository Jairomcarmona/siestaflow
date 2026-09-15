"""The installed version must belong to QRAFT HPC, not the unrelated qraft."""

from importlib import metadata
from pathlib import Path
import runpy

import pytest


@pytest.mark.parametrize("installed", [True, False])
def test_version_never_uses_unrelated_qraft_metadata(monkeypatch, installed):
    queries = []

    def lookup(name):
        queries.append(name)
        if name == "qraft":
            return "99.0.0"
        if name == "qraft-hpc" and installed:
            return "1.2.3"
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", lookup)
    source = Path(__file__).resolve().parents[2] / "src/qraft/version.py"
    namespace = runpy.run_path(str(source))
    assert namespace["__version__"] == ("1.2.3" if installed else "0+unknown")
    assert queries == ["qraft-hpc"]
