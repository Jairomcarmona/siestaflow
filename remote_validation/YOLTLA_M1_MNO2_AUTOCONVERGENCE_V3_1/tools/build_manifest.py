#!/usr/bin/env python3
"""Create the immutable manifest for the V3 deployment package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3_1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def immutable(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path.is_file()
        and not path.is_symlink()
        and relative.parts[0] != "runs"
        and path.name not in {"manifest.json", "checksums.sha256"}
        and not path.name.startswith(("OUT.", "ERROR.", "slurm-"))
        and "__pycache__" not in relative.parts
        and path.suffix != ".pyc"
    )


def main() -> int:
    manifest_path = ROOT / "manifest.json"
    checksums_path = ROOT / "checksums.sha256"
    if manifest_path.exists() or checksums_path.exists():
        raise SystemExit("REFUSING_TO_OVERWRITE_EXISTING_MANIFEST")
    files = {
        path.relative_to(ROOT).as_posix(): sha256(path)
        for path in sorted(ROOT.rglob("*"))
        if immutable(path)
    }
    manifest = {
        "schema_version": "1.0",
        "package_id": PACKAGE_ID,
        "purpose": "M1_MNO2_AUTOMATED_NUMERICAL_BASIS_U_SPIN_TESTS",
        "automatic_submission": False,
        "runs_inside_single_slurm_allocation": True,
        "login_node_daemon_required": False,
        "production_relaxation_enabled": False,
        "pseudopotentials_packaged": True,
        "pseudopotential_sha256": {
            "Mn.psml": "0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6",
            "O.psml": "224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e"
        },
        "immutable_files": files,
    }
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    checksum_files = {**files, "manifest.json": sha256(manifest_path)}
    checksums_path.write_text(
        "".join(
            f"{digest}  {name}\n"
            for name, digest in sorted(checksum_files.items())
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(f"MANIFEST_CREATED:{len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
