import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def historical_context_root() -> Path:
    configured = os.environ.get("QRAFT_HISTORICAL_CONTEXT_ROOT")
    if not configured:
        pytest.skip(
            "historical M2 evidence requires QRAFT_HISTORICAL_CONTEXT_ROOT",
        )
    root = Path(configured)
    if not root.is_dir():
        pytest.skip(
            "QRAFT_HISTORICAL_CONTEXT_ROOT does not name an available evidence root",
        )
    return root


@pytest.fixture(scope="session")
def snapshot(historical_context_root: Path) -> Path:
    snapshot_root = historical_context_root / "scientific_project_snapshot"
    if not snapshot_root.is_dir():
        pytest.skip(
            "QRAFT_HISTORICAL_CONTEXT_ROOT lacks scientific_project_snapshot",
        )
    return snapshot_root


@pytest.fixture(scope="session")
def sanity_fdf(snapshot: Path) -> Path:
    matches = list(snapshot.rglob("M1_U0_FM.pilot.NO_PRODUCTION.fdf"))
    assert len(matches) == 1
    return matches[0]


@pytest.fixture(scope="session")
def synthetic_fixtures() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "siesta" / "synthetic"


@pytest.fixture(scope="session")
def reference_package() -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / "reference_projects" / "birnessite_mn_o"
