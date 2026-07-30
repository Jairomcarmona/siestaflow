"""Shared import setup for read-only characterization of the QEF donor."""

from __future__ import annotations

import sys
from pathlib import Path


DONOR_ROOT = (
    Path(__file__).resolve().parents[3]
    / "context"
    / "donor"
    / "qe-postprocess-framework"
)

# Never leave bytecode artifacts in the read-only donor tree.
sys.dont_write_bytecode = True
sys.path.insert(0, str(DONOR_ROOT / "tests"))
sys.path.insert(0, str(DONOR_ROOT / "src"))
sys.path.insert(0, str(DONOR_ROOT))

