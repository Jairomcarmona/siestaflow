"""Shared import setup for read-only characterization of the QEF donor."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_donor_root = os.environ.get("QRAFT_QEF_DONOR_ROOT")
if not _donor_root:
    raise RuntimeError(
        "QRAFT_QEF_DONOR_ROOT is required when collecting historical QEF "
        "characterization",
    )

DONOR_ROOT = Path(_donor_root)
if not DONOR_ROOT.is_dir():
    raise RuntimeError(
        "QRAFT_QEF_DONOR_ROOT does not name an available QEF donor checkout",
    )

# Never leave bytecode artifacts in the read-only donor tree.
sys.dont_write_bytecode = True
sys.path.insert(0, str(DONOR_ROOT / "tests"))
sys.path.insert(0, str(DONOR_ROOT / "src"))
sys.path.insert(0, str(DONOR_ROOT))

