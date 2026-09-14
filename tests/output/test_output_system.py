from __future__ import annotations

import csv
import sys
import threading
from pathlib import Path

import pytest

from qraft.execution.allocation_controller import AllocationController, ExecutionStatus
from qraft.output import (
    DagEntry,
    NodeEntry,
    OutputContributor,
    OutputMatrix,
    OutputMessage,
    OutputModel,
    OutputTable,
    QraftOutputWriter,
    collect_output,
)
from qraft.protocols.single_fdf import execute_fdf_plan
from tests.m4.test_allocation_controller import controller, environment, make_package


FDF = """SystemName output functional test
SystemLabel output_test
NumberOfAtoms 1
NumberOfSpecies 1
MeshCutoff 100 Ry
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
%block LatticeVectors
8.0 0.0 0.0
0.0 8.0 0.0
0.0 0.0 8.0
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0.0 0.0 0.0 1
%endblock AtomicCoordinatesAndAtomicSpecies
"""


class FakeContributor:
    def __init__(self, model: OutputModel) -> None:
        self.model = model

    def build_output(self, context: object) -> OutputModel:
        return self.model


class FailingContributor:
    def build_output(self, context: object) -> OutputModel:
        raise RuntimeError("optional failure")


def test_writer_renders_header_paths_nodes_messages_and_failure_summary(tmp_path: Path) -> None:
    writer = QraftOutputWriter(tmp_path / "qraft.out")
    writer.initialize(OutputModel(
        header={"Version": "0.2.0", "Campaign": "test", "Root": str(tmp_path)},
        configuration={"launcher": "direct", "MPI ranks": 1},
        dag=(DagEntry("validate", "gate", "READY"), DagEntry("run", "siesta", "WAITING", ("validate",))),
    ))
    writer.append("node result", OutputModel(
        nodes=(NodeEntry(
            "run", "siesta", "FAILED", "attempt-0001", str(tmp_path / "work"),
            str(tmp_path / "input.fdf"), str(tmp_path / "stdout.txt"),
            str(tmp_path / "stderr.txt"), str(tmp_path / "result_manifest.json"),
            {"MPI ranks": 4}, ("validate",),
        ),),
        messages=(OutputMessage(
            "ERROR", "fatal output with exit_code=0", "TECHNICAL_FAILURE", "run", "attempt-0001",
            {"stderr": str(tmp_path / "stderr.txt")},
            {"Technical state": "FAIL", "DAG action": "DEPENDENTS WILL BE BLOCKED"},
        ),),
    ))
    writer.finish({"Campaign status": "FAILED", "Failed": 1})
    text = writer.path.read_text(encoding="utf-8")
    for expected in (
        "Q R A F T", "qraft-output-schema : 1.1", "[RESOLVED CONFIGURATION]",
        "[DAG]", "[NODE STATE — run]", "attempt-0001", "stdout.txt", "stderr.txt",
        "[ERROR TECHNICAL_FAILURE]", "Technical state", "DAG action",
        "QRAFT CAMPAIGN SUMMARY", "FAILED",
    ):
        assert expected in text


def test_contributors_are_protocol_neutral_and_combine_without_writer_changes(tmp_path: Path) -> None:
    contributors = (
        FakeContributor(OutputModel(metrics={"Energy": -1.25}, notes=("single calculation",))),
        FakeContributor(OutputModel(tables=(OutputTable("convergence", ("mesh", "energy"), ((100, -1.0),)),))),
        FakeContributor(OutputModel(matrices=(OutputMatrix("chi", ("Mn01",), ("Mn01",), ((-0.2,),)),))),
        FakeContributor(OutputModel(metrics={"custom.future.metric": 7}, notes=("unknown/custom protocol",))),
    )
    assert all(isinstance(item, OutputContributor) for item in contributors)
    model = OutputModel.combine([item.build_output(None) for item in contributors])
    writer = QraftOutputWriter(tmp_path / "qraft.out")
    writer.initialize(OutputModel(header={"Campaign": "universal"}))
    writer.append("protocol contributions", model)
    text = writer.path.read_text(encoding="utf-8")
    assert "Energy" in text and "[TABLE convergence]" in text
    assert "[MATRIX chi]" in text and "custom.future.metric" in text
    optional = collect_output((*contributors, FailingContributor()), None)
    assert optional.messages[0].code == "OUTPUT_CONTRIBUTOR_FAILURE"


def test_small_matrix_is_inline_large_matrix_is_summarized_and_csv_is_valid(tmp_path: Path) -> None:
    small = OutputMatrix("chi0", ("A", "B"), ("A", "B"), ((1.0, 0.1), (0.1, 2.0)), unit="e/eV")
    large = OutputMatrix(
        "response large", ("A", "B", "C"), ("A", "B"),
        ((1, 2), (3, 4), (5, 6)), summary={"Condition number": 12.47},
    )
    table = OutputTable("energies", ("case", "energy"), (("full", -10.0),))
    large_table = OutputTable("many points", ("x",), tuple((index,) for index in range(6)))
    writer = QraftOutputWriter(tmp_path / "qraft.out", matrix_cell_limit=4, table_row_limit=4)
    writer.initialize(OutputModel(header={"Campaign": "matrix"}))
    writer.append("results", OutputModel(matrices=(small, large), tables=(table, large_table)))
    text = writer.path.read_text(encoding="utf-8")
    assert "[MATRIX chi0] [e/eV]" in text and "Dimensions  : 3 x 2" in text
    assert "Condition number" in text and "CSV artifact emitted by writer" in text
    assert "[TABLE many points]" in text and "Rows       : 6" in text
    for name in ("chi0.csv", "response_large.csv", "energies.csv", "many_points.csv"):
        assert (tmp_path / "results" / name).is_file()
    with (tmp_path / "results" / "energies.csv").open(newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == [["case", "energy"], ["full", "-10.0"]]


def test_no_tabular_data_creates_no_csv_and_optional_csv_failure_is_nonfatal(
    tmp_path: Path, monkeypatch
) -> None:
    writer = QraftOutputWriter(tmp_path / "qraft.out")
    writer.initialize(OutputModel(header={"Campaign": "plain"}, metrics={"SCF steps": 4}))
    assert not (tmp_path / "results").exists()
    monkeypatch.setattr(writer.csv_exporter, "export", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk")))
    warnings = writer.append("optional", OutputModel(tables=(OutputTable("x", ("a",), ((1,),)),)))
    assert warnings and "CSV_EXPORT_WARNING" in warnings[0]
    assert "CSV_EXPORT_WARNING" in writer.path.read_text(encoding="utf-8")


def test_concurrent_appends_keep_node_blocks_intact(tmp_path: Path) -> None:
    writer = QraftOutputWriter(tmp_path / "qraft.out")
    writer.initialize(OutputModel(header={"Campaign": "concurrent"}))
    barrier = threading.Barrier(3)

    def emit(node_id: str) -> None:
        barrier.wait()
        writer.append(node_id, OutputModel(nodes=(NodeEntry(node_id, "custom", "COMPLETED"),), notes=(node_id * 50,)))

    threads = [threading.Thread(target=emit, args=(name,)) for name in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    text = writer.path.read_text(encoding="utf-8")
    assert text.count("[NODE STATE — alpha]") == text.count("[NODE STATE — beta]") == 1
    assert "alpha" * 50 in text and "beta" * 50 in text


def test_single_fdf_functional_output_and_recovery_do_not_mutate_attempt(tmp_path: Path) -> None:
    fdf = tmp_path / "calc.fdf"
    fdf.write_text(FDF, encoding="utf-8")
    (tmp_path / "C.psf").write_text("pseudo", encoding="utf-8")
    fake = tmp_path / "fake_siesta.py"
    fake.write_text(
        "import sys\nsys.stdin.read()\nprint('SIESTA started')\n"
        "print('SCF iteration 1')\nprint('SCF converged')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs with spaces"
    overrides = {
        "launcher": "direct", "partition": "local", "executable": sys.executable,
        "executable_arguments": [str(fake)],
    }
    first = execute_fdf_plan(fdf, overrides=overrides, runs_root=runs)
    manifest = next(runs.rglob("attempt.json"))
    original = manifest.read_bytes()
    reused = execute_fdf_plan(fdf, overrides=overrides, runs_root=runs)
    assert first["attempt"]["result"]["technical_validation"]["status"] == "PASS"
    assert reused["status"] == "REUSED_VALIDATED_ATTEMPT"
    assert manifest.read_bytes() == original
    text = (runs / "qraft.out").read_text(encoding="utf-8")
    for expected in (
        "single_fdf:calc", "QRAFT EXECUTION SESSION", "[EXECUTION]", "[IDENTITY]",
        "[RESOLVED CONFIGURATION]", "[DAG]", "[NODE START — run_siesta]",
        "[NODE RESULT — run_siesta]",
        first["attempt"]["attempt_id"], "stdout.txt", "stderr.txt", "technical status", "PASS",
        "[RECOVERY]", "REUSED_VALIDATED_ATTEMPT", "no SIESTA relaunch required",
        "QRAFT CAMPAIGN SUMMARY",
    ):
        assert expected in text
    fake.write_text(
        "import sys\nsys.stdin.read()\nprint('SIESTA started')\nprint('SCF iteration 1')\n",
        encoding="utf-8",
    )
    failed = execute_fdf_plan(
        fdf, overrides=overrides, runs_root=runs, force_new_attempt=True
    )
    assert failed["attempt"]["result"]["technical_validation"]["status"] == "FAIL"
    failed_text = (runs / "qraft.out").read_text(encoding="utf-8")
    assert "NORMAL_TERMINATION_MISSING" in failed_text


def test_single_fdf_planning_failure_still_writes_authoritative_output(tmp_path: Path) -> None:
    runs = tmp_path / "failed planning"
    missing = tmp_path / "missing.fdf"
    with pytest.raises((FileNotFoundError, ValueError)):
        execute_fdf_plan(missing, runs_root=runs)
    text = (runs / "qraft.out").read_text(encoding="utf-8")
    assert "[PLANNING FAILURE]" in text
    assert "PLAN_BUILD_FAILED" in text
    assert "Technical state" in text and "DAG action" in text
    assert "Campaign status" in text and "BLOCKED" in text
    assert "PLAN_BUILD_FAILED" in (runs / "events.jsonl").read_text(encoding="utf-8")


def test_allocation_controller_writes_success_failure_and_resume_output(tmp_path: Path) -> None:
    campaign, _ = make_package(tmp_path, ["FAIL", "SUCCESS"], max_parallel=1)
    controller(campaign, "job-1").run(install_signal_handlers=False)
    text = (tmp_path / "qraft.out").read_text(encoding="utf-8")
    assert "[NODE RESULT — task-1]" in text and "[ERROR FAILED]" in text
    assert "[NODE RESULT — task-2]" in text and "Technical validation : PASS" in text
    assert "Campaign status" in text and "FAILED" in text
    controller(campaign, "job-2").run(install_signal_handlers=False)
    resumed = (tmp_path / "qraft.out").read_text(encoding="utf-8")
    assert "[RECOVERY]" in resumed and "CAMPAIGN RESUMED" in resumed
    assert "task-2:attempt-0001" in resumed


def test_controller_records_core_output_failure_without_invalidating_science(
    tmp_path: Path, monkeypatch
) -> None:
    campaign, _ = make_package(tmp_path, ["SUCCESS"])
    current = controller(campaign, "output-failure")
    monkeypatch.setattr(
        current.output_writer, "append", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("output disk"))
    )
    assert current.run(install_signal_handlers=False) is ExecutionStatus.COMPLETED
    events = (tmp_path / "evidence" / "events.jsonl").read_text(encoding="utf-8")
    assert "OUTPUT_CORE_FAILURE" in events and "output disk" in events


def test_allocation_validation_failure_writes_controlled_blocked_output(tmp_path: Path) -> None:
    campaign, config = make_package(tmp_path, ["SUCCESS"], total_cpus=2)
    current = AllocationController.from_file(
        campaign,
        environment=environment(tmp_path, "undersized", total_cpus=1),
        poll_interval_seconds=0.01,
    )
    with pytest.raises(ValueError, match="exceed allocation"):
        current.run(install_signal_handlers=False)
    text = (tmp_path / "qraft.out").read_text(encoding="utf-8")
    assert "[CONTROLLER BLOCKED]" in text
    assert "ALLOCATION_VALIDATION" in text and "Campaign status" in text
    assert "BLOCKED" in text
