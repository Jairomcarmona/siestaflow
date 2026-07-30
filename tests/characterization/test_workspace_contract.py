"""Observed workspace, collision, staging, and overwrite behavior."""

from pathlib import Path

from qef.legacy.core.workspace import WorkspaceManager
from setup_workspace import _copy_dir
from utils import get_semantic_run_dir


QE_INPUT = """&CONTROL
  calculation = 'scf'
  pseudo_dir = '/absolute/old/path'
/
K_POINTS automatic
2 2 1 0 0 0
"""


def test_mass_import_is_semantic_versioned_and_preserves_source(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    input_file = source / "M1.in"
    input_file.write_text(QE_INPUT, encoding="utf-8")
    project = tmp_path / "project"

    first = WorkspaceManager.import_mass_inputs(source, project)
    second = WorkspaceManager.import_mass_inputs(source, project)

    assert first == {"in_processed": 1, "cif_moved": 0, "errors": 0}
    assert second == {"in_processed": 1, "cif_moved": 0, "errors": 0}
    runs = project / "03_runs"
    assert (runs / "m1_scf" / "M1.in").is_file()
    assert (runs / "m1_scf_v02" / "M1.in").is_file()
    assert "../../02_pseudos/" in (runs / "m1_scf" / "M1.in").read_text()
    assert input_file.read_text(encoding="utf-8") == QE_INPUT
    mapping = (runs / "job_index.map").read_text(encoding="utf-8")
    assert "m1_scf" in mapping and "m1_scf_v02" in mapping


def test_semantic_directory_api_does_not_confine_untrusted_labels(tmp_path: Path):
    runs = tmp_path / "project" / "03_runs"

    created = Path(get_semantic_run_dir(str(runs), "../escaped", "scf"))

    assert created == (runs.parent / "escaped_scf").resolve()
    assert runs.resolve() not in created.parents


def test_deploy_copy_helper_overwrites_same_named_files(tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "settings.txt").write_text("new", encoding="utf-8")
    target = destination / "settings.txt"
    target.write_text("user-value", encoding="utf-8")

    copied = _copy_dir(source, destination)

    assert copied == 1
    assert target.read_text(encoding="utf-8") == "new"

