import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import qraft.dos_pdos_results as results
from qraft.dos_pdos_results import DOSPDOSResultExporter, _dos_pdos_task, parse_total_dos


def test_parse_total_dos_accepts_non_spin_data_and_fortran_exponents(tmp_path: Path) -> None:
    source = tmp_path / "sample.DOS"
    source.write_text("# SIESTA DOS\n-1.0D+00 0.25\n0.0 1.5\n", encoding="utf-8")

    parsed = parse_total_dos(source)

    assert parsed.columns == ("energy_eV", "total_dos_states_per_eV")
    assert parsed.rows == ((-1.0, 0.25), (0.0, 1.5))


def test_parse_total_dos_accepts_spin_channels(tmp_path: Path) -> None:
    source = tmp_path / "spin.DOS"
    source.write_text("-1.0 0.25 0.5\n0.0 1.5 2.0\n", encoding="utf-8")

    parsed = parse_total_dos(source)

    assert parsed.columns == ("energy_eV", "dos_spin_up_states_per_eV", "dos_spin_down_states_per_eV")


@pytest.mark.parametrize("text", ["-1 0.1\n-1 0.2\n", "-1 0.1 0.2\n0 0.3\n", "not numeric\n"])
def test_parse_total_dos_rejects_malformed_or_nonmonotonic_data(tmp_path: Path, text: str) -> None:
    source = tmp_path / "bad.DOS"
    source.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError):
        parse_total_dos(source)


def test_dos_pdos_task_selection_requires_exactly_one_pair() -> None:
    class Task:
        def __init__(self, artifacts: tuple[str, ...]) -> None:
            self.required_artifacts = artifacts

    selected = _dos_pdos_task((Task(("x.DOS", "x.PDOS")), Task(("parent.DM",))))
    assert selected.required_artifacts == ("x.DOS", "x.PDOS")
    with pytest.raises(ValueError):
        _dos_pdos_task((Task(("a.DOS", "a.PDOS")), Task(("b.DOS", "b.PDOS"))))


def test_export_writes_hash_bound_table_without_interpretation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "package"
    attempt = package / "work" / "dos_pdos" / "attempt-0001"
    attempt.mkdir(parents=True)
    dos = attempt / "sample.DOS"
    pdos = attempt / "sample.PDOS"
    dos.write_text("-1.0 0.0\n0.0 2.0\n", encoding="utf-8")
    pdos.write_text("raw pdos\n", encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    (attempt / "result_manifest.json").write_text(json.dumps({
        "task_id": "dos_pdos", "exit_code": 0, "normal_termination": True,
        "scf_converged": True,
        "artifacts": {"sample.DOS": digest(dos), "sample.PDOS": digest(pdos)},
        "transferred_inputs": [],
    }), encoding="utf-8")
    task = SimpleNamespace(task_id="dos_pdos", required_artifacts=("sample.DOS", "sample.PDOS"), transfers=())
    inspection = SimpleNamespace(package_path=str(package), campaign_status="COMPLETED", run_id="run", workflow_id="workflow")
    monkeypatch.setattr(results, "load_controller_config", lambda _: SimpleNamespace(tasks=(task,)))
    monkeypatch.setattr(results, "read_campaign_progress", lambda _: {"tasks": [{"task_id": "dos_pdos", "status": "COMPLETED", "last_attempt": "attempt-0001"}]})
    monkeypatch.setattr(results, "load_workflow_lock", lambda _: (SimpleNamespace(content_sha256="w" * 64), None))
    monkeypatch.setattr(results, "load_run_lock", lambda _: (SimpleNamespace(content_sha256="r" * 64), SimpleNamespace(metadata={"source_identity": {"source_commit": "abc"}})))

    exported = DOSPDOSResultExporter(inspector=SimpleNamespace(inspect=lambda _: inspection)).export(package, tmp_path / "export")

    assert exported["status"] == "DOS_PDOS_RESULT_EXPORTED"
    assert (tmp_path / "export" / "total_dos.csv").read_text(encoding="utf-8").splitlines()[0] == "energy_eV,total_dos_states_per_eV"
    manifest = json.loads((tmp_path / "export" / "dos_pdos_export.json").read_text(encoding="utf-8"))
    assert manifest["scientific_interpretation"] == "NOT_PERFORMED"
    assert manifest["pdos"]["parsed"] is False
