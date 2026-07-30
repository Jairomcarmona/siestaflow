#!/usr/bin/env python3
"""Local packaging helper; rebuilding remotely does not preserve the ZIP hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    manifest_path = ROOT / "manifest.json"
    checksums_path = ROOT / "checksums.sha256"
    if manifest_path.exists() or checksums_path.exists():
        raise SystemExit("REFUSING_TO_OVERWRITE_EXISTING_MANIFEST")
    files = {
        path.relative_to(ROOT).as_posix(): sha256(path)
        for path in sorted(ROOT.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and not mutable(PurePosixPath(path.relative_to(ROOT).as_posix()))
        and path.name not in {"manifest.json", "checksums.sha256"}
        and not path.name.startswith("slurm-")
    }
    manifest = {
        "schema_version": "1.0",
        "package_id": "YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V1",
        "purpose": "STAGED_M1_MNO2_SCIENTIFIC_CAMPAIGN",
        "automatic_submission": False,
        "login_node_persistent_process_required": False,
        "external_pseudopotentials_packaged": False,
        "remote_rebuild_preserves_distribution_hash": False,
        "immutable_files": files,
    }
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    checksum_files = dict(files)
    checksum_files["manifest.json"] = sha256(manifest_path)
    checksums_path.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksum_files.items())),
        encoding="utf-8",
        newline="\n",
    )
    print(f"MANIFEST_CREATED:{len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

