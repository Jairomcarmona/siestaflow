#!/usr/bin/env python3
"""Create a deterministic ZIP without mutable state or external PSML files."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT.parent / f"{ROOT.name}.zip"


def mutable(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if parts[0] in {"generated", "state", "work", "results", "evidence", "site"}:
        return True
    if len(parts) >= 2 and parts[:2] == ("gates", "decisions"):
        return True
    if len(parts) >= 2 and parts[:2] == ("external", "pseudopotentials"):
        return relative.name != "README.md"
    if len(parts) >= 2 and parts[:2] == ("geometry", "systems"):
        return relative.name != "README.md"
    return False


def main() -> int:
    if DESTINATION.exists():
        raise SystemExit(f"REFUSING_TO_OVERWRITE:{DESTINATION}")
    files = [
        path
        for path in sorted(ROOT.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and not mutable(PurePosixPath(path.relative_to(ROOT).as_posix()))
        and not path.name.startswith("slurm-")
    ]
    with ZipFile(
        DESTINATION, "x", compression=ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = PurePosixPath(ROOT.name) / PurePosixPath(
                path.relative_to(ROOT).as_posix()
            )
            info = ZipInfo(relative.as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            mode = 0o755 if path.suffix in {".py", ".sh", ".slurm"} else 0o644
            info.external_attr = mode << 16
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

