from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def snapshot() -> Path:
    return Path(__file__).resolve().parents[3] / "context" / "scientific_project_snapshot"


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
