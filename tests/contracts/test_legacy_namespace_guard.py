"""The naming gate must reject replacements even when ordinary tests change."""

import importlib.util
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "legacy_namespace_guard", ROOT / "tools/check_legacy_namespace.py"
)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def test_repository_preserves_legacy_namespace():
    assert guard.main() == 0


@pytest.mark.parametrize("replacement", ["qraft.workflow-lock", "siestaflow.run-lock", ""])
def test_replacement_is_detected(tmp_path, replacement):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "src/qraft/catalog.py"
    source.parent.mkdir(parents=True)
    source.write_text('NAME = "siestaflow.workflow-lock"\n', encoding="utf-8")
    subprocess.run(["git", "add", "src"], cwd=tmp_path, check=True)
    original = guard.inventory(tmp_path)
    source.write_text(f'NAME = "{replacement}"\n', encoding="utf-8")
    assert guard.differences(original, guard.inventory(tmp_path))
    source.unlink()
    assert guard.differences(original, guard.inventory(tmp_path))


def test_unrelated_edit_and_untracked_build_do_not_change_namespace(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "src/qraft/catalog.py"
    source.parent.mkdir(parents=True)
    source.write_text('NAME = "siestaflow.workflow-lock"\n', encoding="utf-8")
    subprocess.run(["git", "add", "src"], cwd=tmp_path, check=True)
    original = guard.inventory(tmp_path)
    source.write_text(source.read_text(encoding="utf-8") + "# unrelated edit\n", encoding="utf-8")
    (source.parent / "generated.py").write_text('NAME = "siestaflow.generated"', encoding="utf-8")
    assert not guard.differences(original, guard.inventory(tmp_path))
