#!/usr/bin/env python3
"""Verify the immutable package and its internal scientific contracts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent
PACKAGE_ID = "YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V1"


def fail(code: str, detail: str = "") -> None:
    raise SystemExit(code + (f":{detail}" if detail else ""))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(name: str) -> Path:
    posix = PurePosixPath(name)
    if posix.is_absolute() or ".." in posix.parts or "\\" in name or not posix.parts:
        fail("UNSAFE_MANIFEST_PATH", name)
    return ROOT.joinpath(*posix.parts)


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
    if not manifest_path.is_file() or not checksums_path.is_file():
        fail("PACKAGE_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("package_id") != PACKAGE_ID
    ):
        fail("PACKAGE_IDENTITY_MISMATCH")
    immutable = manifest.get("immutable_files")
    if not isinstance(immutable, dict) or not immutable:
        fail("IMMUTABLE_MANIFEST_EMPTY")
    for name, expected in immutable.items():
        target = safe_path(str(name))
        if not target.is_file() or target.is_symlink():
            fail("IMMUTABLE_FILE_MISSING", str(name))
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            fail("INVALID_IMMUTABLE_SHA256", str(name))
        if sha256(target) != expected:
            fail("IMMUTABLE_HASH_MISMATCH", str(name))

    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not mutable(PurePosixPath(path.relative_to(ROOT).as_posix()))
        and path.name not in {"manifest.json", "checksums.sha256"}
        and not path.name.startswith("slurm-")
    }
    if actual != set(immutable):
        fail("IMMUTABLE_COVERAGE_MISMATCH", str(sorted(actual ^ set(immutable))))
    if any(path.is_symlink() for path in ROOT.rglob("*")):
        fail("PACKAGE_SYMLINK_FORBIDDEN")

    seen: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(.+)", line)
        if not match:
            fail("INVALID_CHECKSUM_LINE", line)
        digest, name = match.groups()
        if name in seen:
            fail("DUPLICATE_CHECKSUM", name)
        target = safe_path(name)
        if not target.is_file() or sha256(target) != digest:
            fail("CHECKSUM_MISMATCH", name)
        seen[name] = digest
    if set(seen) != set(immutable) | {"manifest.json"}:
        fail("CHECKSUM_COVERAGE_MISMATCH")

    for path in sorted((ROOT / "scripts").glob("*.py")):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            fail("PYTHON_SYNTAX_FAILURE", f"{path.name}:{exc}")
    compile(
        (ROOT / "verify_package.py").read_text(encoding="utf-8"),
        str(ROOT / "verify_package.py"),
        "exec",
    )
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", path.relative_to(ROOT).as_posix()],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            fail("BASH_SYNTAX_FAILURE", f"{path.name}:{result.stderr.strip()}")

    controller = (
        ROOT / "runtime/siestaflow/execution/allocation_controller.py"
    ).read_text(encoding="utf-8")
    if "srun" not in controller or "campaign_state.json" not in controller:
        fail("VENDORED_CONTROLLER_CONTRACT_MISSING")
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"subprocess\.(?:run|Popen)\s*\(\s*\[[^\]]*['\"]sbatch", text):
            fail("AUTOMATIC_SBATCH_FORBIDDEN", path.relative_to(ROOT).as_posix())

    result = subprocess.run(
        [sys.executable, "scripts/campaignctl.py", "verify"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail("SCIENTIFIC_STRUCTURE_FAILURE", result.stderr.strip())
    print("YOLTLA_M1_PACKAGE_VERIFIED")
    print("REMOTE_SUBMISSION_NOT_PERFORMED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

