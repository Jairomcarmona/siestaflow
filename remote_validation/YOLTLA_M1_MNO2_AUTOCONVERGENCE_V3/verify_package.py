#!/usr/bin/env python3
"""Verify hashes, scientific scope and the exact Yoltla resource contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGE_ID = "YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3"


def fail(code: str, detail: str = "") -> None:
    raise SystemExit(code + (f":{detail}" if detail else ""))


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


def load_automatic_campaign():
    path = ROOT / "scripts/automatic_campaign.py"
    spec = importlib.util.spec_from_file_location("automatic_campaign_v3", path)
    if spec is None or spec.loader is None:
        fail("AUTOMATIC_CAMPAIGN_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    manifest_path = ROOT / "manifest.json"
    checksums_path = ROOT / "checksums.sha256"
    if not manifest_path.is_file() or not checksums_path.is_file():
        fail("PACKAGE_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package_id") != PACKAGE_ID:
        fail("PACKAGE_ID_MISMATCH")
    immutable_files = manifest.get("immutable_files")
    if not isinstance(immutable_files, dict) or not immutable_files:
        fail("IMMUTABLE_MANIFEST_EMPTY")
    for name, expected in immutable_files.items():
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            fail("IMMUTABLE_FILE_MISSING", name)
        if sha256(path) != expected:
            fail("IMMUTABLE_HASH_MISMATCH", name)
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if immutable(path)
    }
    if actual != set(immutable_files):
        fail("IMMUTABLE_COVERAGE_MISMATCH", str(sorted(actual ^ set(immutable_files))))
    if any(path.is_symlink() for path in ROOT.rglob("*")):
        fail("SYMLINK_FORBIDDEN")
    checksum_entries = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(.+)", line)
        if not match:
            fail("INVALID_CHECKSUM_LINE", line)
        digest, name = match.groups()
        if name in checksum_entries or sha256(ROOT / name) != digest:
            fail("CHECKSUM_MISMATCH", name)
        checksum_entries[name] = digest
    if set(checksum_entries) != set(immutable_files) | {"manifest.json"}:
        fail("CHECKSUM_COVERAGE_MISMATCH")
    pseudo_expected = manifest["pseudopotential_sha256"]
    for name, expected in pseudo_expected.items():
        if sha256(ROOT / "external/pseudopotentials" / name) != expected:
            fail("PSEUDOPOTENTIAL_HASH_MISMATCH", name)

    for path in ROOT.rglob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for path in ROOT.rglob("*.sh"):
        result = subprocess.run(
            ["bash", "-n", path.relative_to(ROOT).as_posix()],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            fail("BASH_SYNTAX_FAILURE", f"{path.name}:{result.stderr.strip()}")
    result = subprocess.run(
        ["bash", "-n", "submit.slurm"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail("SLURM_SCRIPT_SYNTAX_FAILURE", result.stderr.strip())

    submit = (ROOT / "submit.slurm").read_text(encoding="utf-8")
    directives = {
        "--partition": "qz2d-128p",
        "--nodes": "2",
        "--ntasks": "128",
        "--ntasks-per-node": "64",
        "--cpus-per-task": "1",
        "--time": "2-00:00:00",
    }
    for key, value in directives.items():
        if not re.search(
            rf"(?m)^#SBATCH\s+{re.escape(key)}={re.escape(value)}\s*$", submit
        ):
            fail("SBATCH_DIRECTIVE_MISMATCH", key)
    if re.search(r"(?m)^\s*sbatch\s+", submit):
        fail("AUTOMATIC_SBATCH_FORBIDDEN")

    module = load_automatic_campaign()
    config = module.load_config(ROOT / "campaign.json")
    module.validate_static_files(config)
    generated = module.render_fdf(
        (ROOT / config["system"]["base_fdf"]).read_text(encoding="utf-8"),
        config,
        module.Variant(
            "verification_u3p8_stripe",
            "verification",
            350,
            (4, 4, 1),
            "EXPLICIT_TZP",
            3.8,
            "STRIPE_AFM",
        ),
    )
    for required in (
        "DFTU.ProjectorGenerationMethod 2",
        "DFTU.CutoffNorm 0.900000",
        "%block DFTU.Proj",
        "%block PAO.Basis",
        "n=3 2 3 P 1",
        "3.800000 0.000000",
        "MD.Steps 0",
    ):
        if required not in generated:
            fail("MATERIALIZED_FDF_MISSING", required)
    for forbidden in (
        "PAO.BasisSize TZP",
        "LDAU.ProjectorGenerationMethod",
        "dual_40",
        "quad_20",
        "scaling_20_40_80",
    ):
        if forbidden in generated or forbidden in submit:
            fail("FORBIDDEN_LEGACY_POLICY", forbidden)
    print("YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3_VERIFIED")
    print("REMOTE_SUBMISSION_NOT_PERFORMED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
