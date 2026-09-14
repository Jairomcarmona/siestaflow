"""Collection policy for tests that require immutable external evidence."""

from __future__ import annotations

import os
from pathlib import Path


def pytest_ignore_collect(collection_path: Path, config: object) -> bool:
    """Keep the default suite self-contained; external evidence is opt-in."""

    normalized = collection_path.as_posix()
    if "/tests/characterization" in normalized:
        return not bool(os.environ.get("QRAFT_QEF_DONOR_ROOT"))
    if normalized.endswith("/tests/m3b1/test_real_smoke_package.py"):
        return not (
            os.environ.get("QRAFT_HISTORICAL_CONTEXT_ROOT")
            and os.environ.get("QRAFT_M3B1_C_PSEUDOPOTENTIAL")
        )
    return False
