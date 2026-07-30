from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from siestaflow.errors import AlreadyExistsError, PathSafetyError
from siestaflow.filesystem import DryRunFileSystem, RealFileSystem, safe_join, validate_identifier


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape", "..\\escape", "/absolute", "C:\\escape", "a/b", "a\\b",
        "", "..", "bad\x00id", "CON", "aux.txt", "trailing."
    ],
)
def test_rejects_posix_and_windows_path_traversal(unsafe: str):
    with pytest.raises(PathSafetyError):
        validate_identifier(unsafe)


def test_safe_join_remains_inside_authorized_root(tmp_path: Path):
    result = safe_join(tmp_path, "CAMPAIGN_001", "TASK_001")
    assert tmp_path.resolve() in result.parents


def _inventory(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_dry_run_records_plan_with_zero_filesystem_side_effects(tmp_path: Path):
    existing = tmp_path / "existing.txt"
    existing.write_text("preserve", encoding="utf-8")
    before = _inventory(tmp_path)
    fs = DryRunFileSystem()

    fs.mkdir(tmp_path / "new", parents=True)
    fs.write_text(tmp_path / "new" / "file.txt", "payload")
    fs.atomic_write_json(tmp_path / "state.json", {"state": "RUNNING"})
    fs.copy(existing, tmp_path / "copy.txt")
    fs.remove(existing)

    assert _inventory(tmp_path) == before
    assert [item.operation for item in fs.operations] == [
        "mkdir", "write_text", "atomic_write_json", "copy", "remove"
    ]


def test_real_filesystem_refuses_text_overwrite(tmp_path: Path):
    fs = RealFileSystem()
    path = tmp_path / "immutable.txt"
    fs.write_text(path, "first")
    with pytest.raises(FileExistsError):
        fs.write_text(path, "second")
