#!/usr/bin/env python3
"""Create a deterministic ZIP of the verified immutable package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT.parent / f"{ROOT.name}.zip"


def main() -> int:
    if DESTINATION.exists():
        raise SystemExit(f"REFUSING_TO_OVERWRITE:{DESTINATION}")
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    files = sorted(
        {*manifest["immutable_files"], "manifest.json", "checksums.sha256"}
    )
    with ZipFile(
        DESTINATION, "x", compression=ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in files:
            path = ROOT / name
            relative = f"{ROOT.name}/{name}"
            info = ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (
                0o755 if path.suffix in {".py", ".sh", ".slurm"} else 0o644
            ) << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=ZIP_DEFLATED,
                compresslevel=9,
            )
    digest = hashlib.sha256(DESTINATION.read_bytes()).hexdigest()
    print(f"ARCHIVE:{DESTINATION}")
    print(f"SHA256:{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
