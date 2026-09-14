from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from qraft.engines.siesta.output_parser import SiestaOutputParser
from qraft.local_execution import (
    InputBinding,
    LocalExecutionError,
    LocalExecutionProfile,
    LocalExecutor,
    LocalRunSpec,
    classify_output,
    compare_run_summaries,
    validate_bindings,
    validate_profile,
)


REPO = Path(__file__).resolve().parents[2]
PROFILES = REPO / "examples/reference_projects/graphene_surf_gr5x5/local_execution_profiles.yaml"
SMOKE_SPEC = REPO / "examples/reference_projects/graphene_surf_gr5x5/local_smoke_spec.json"


def executable(path: Path, version: str = "Parallelisations: MPI") -> Path:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n")
    path.chmod(0o755)
    return path


def binding(path: Path, destination: str = "input.fdf") -> InputBinding:
    return InputBinding(path, destination, hashlib.sha256(path.read_bytes()).hexdigest())


def record(output: str):
    return SiestaOutputParser().parse(output.splitlines(True))


def test_external_profiles_are_generic_and_loadable():
    serial = LocalExecutionProfile.from_file(PROFILES, "local_serial")
    mpi2 = LocalExecutionProfile.from_file(PROFILES, "local_openmpi_2")
    mpi4 = LocalExecutionProfile.from_file(PROFILES, "local_openmpi_4")
    assert (serial.launcher, serial.tasks) == ("direct", 1)
    assert (mpi2.launcher, mpi2.tasks) == ("mpirun", 2)
    assert (mpi4.launcher, mpi4.tasks) == ("mpirun", 4)
    core = (REPO / "src/qraft/local_execution.py").read_text()
    assert "/home/jmc" not in core and "SURF_Gr5x5" not in core and "C.psml" not in core


def test_real_inputs_and_hashes_remain_external_to_core():
    data = __import__("json").loads(SMOKE_SPEC.read_text())
    assert data["expected"] == {"number_of_atoms": 50, "species": ["C"]}
    assert {data["input"]["source"], *(item["source"] for item in data["resources"])} == {
        "input/smoke.fdf", "pseudos/C.psml", "geometry/SURF_Gr5x5_clean_v01.xyz",
    }


def test_serial_binary_marked_as_mpi_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    binary = executable(tmp_path / "engine", "Parallelisations: none")
    monkeypatch.setattr("qraft.local_execution.shutil.which", lambda _: "/usr/bin/launcher")
    monkeypatch.setattr(
        "qraft.local_execution.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "Parallelisations: none\n", ""),
    )
    with pytest.raises(LocalExecutionError, match="EXECUTABLE_NOT_MPI"):
        validate_profile(LocalExecutionProfile("bad", "launcher", str(binary), 2))


def test_missing_mpi_binary_is_rejected(tmp_path: Path):
    with pytest.raises(LocalExecutionError, match="EXECUTABLE_MISSING"):
        validate_profile(LocalExecutionProfile("missing", "launcher", str(tmp_path / "missing"), 2))


def test_missing_launcher_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    binary = executable(tmp_path / "engine")
    monkeypatch.setattr("qraft.local_execution.shutil.which", lambda _: None)
    with pytest.raises(LocalExecutionError, match="LAUNCHER_MISSING"):
        validate_profile(LocalExecutionProfile("missing", "launcher", str(binary), 2))


@pytest.mark.parametrize("tasks", [0, -1, 1.5, True])
def test_invalid_task_count_is_rejected(tmp_path: Path, tasks):
    binary = executable(tmp_path / "engine")
    with pytest.raises(LocalExecutionError, match="INVALID_TASK_COUNT"):
        validate_profile(LocalExecutionProfile("bad", "direct", str(binary), tasks))


def test_missing_input_and_resource_are_classified(tmp_path: Path):
    missing = tmp_path / "missing"
    with pytest.raises(LocalExecutionError, match="INPUT_MISSING"):
        validate_bindings((InputBinding(missing, "input.fdf", "0" * 64),))
    source = tmp_path / "input"; source.write_text("input")
    with pytest.raises(LocalExecutionError, match="RESOURCE_MISSING"):
        validate_bindings((binding(source), InputBinding(missing, "resource.dat", "0" * 64)))


def test_altered_hash_is_rejected(tmp_path: Path):
    source = tmp_path / "input"; source.write_text("input")
    item = binding(source); source.write_text("altered")
    with pytest.raises(LocalExecutionError, match="INPUT_HASH_MISMATCH"):
        validate_bindings((item,))


def test_input_resource_destination_collision_is_blocked_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    input_source = tmp_path / "source.fdf"; input_source.write_text("original FDF")
    resource_source = tmp_path / "resource.dat"; resource_source.write_text("resource payload")
    destination = tmp_path / "run"
    launched = False

    monkeypatch.setattr(
        "qraft.local_execution.validate_profile",
        lambda _: (tmp_path / "engine", None, "Version: test", None),
    )

    def unexpected_run(*args, **kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("SIESTA_EXECUTED_AFTER_BINDING_COLLISION")

    monkeypatch.setattr("qraft.local_execution.subprocess.run", unexpected_run)
    time_command = tmp_path / "time"; time_command.write_text("")
    spec = LocalRunSpec(
        "input-resource-collision", destination,
        LocalExecutionProfile("serial", "direct", str(tmp_path / "engine"), 1),
        binding(input_source, "input.fdf"),
        (binding(resource_source, "input.fdf"),),
    )

    with pytest.raises(LocalExecutionError, match="BINDING_DESTINATION_COLLISION"):
        LocalExecutor(time_command=str(time_command)).run(spec)
    assert launched is False
    assert destination.exists() is False


def test_two_resources_with_same_destination_are_blocked_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    input_source = tmp_path / "source.fdf"; input_source.write_text("original FDF")
    resource_a = tmp_path / "resource-a.dat"; resource_a.write_text("resource A")
    resource_b = tmp_path / "resource-b.dat"; resource_b.write_text("resource B")
    destination = tmp_path / "run"
    launched = False

    monkeypatch.setattr(
        "qraft.local_execution.validate_profile",
        lambda _: (tmp_path / "engine", None, "Version: test", None),
    )

    def unexpected_run(*args, **kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("SIESTA_EXECUTED_AFTER_BINDING_COLLISION")

    monkeypatch.setattr("qraft.local_execution.subprocess.run", unexpected_run)
    time_command = tmp_path / "time"; time_command.write_text("")
    spec = LocalRunSpec(
        "resource-resource-collision", destination,
        LocalExecutionProfile("serial", "direct", str(tmp_path / "engine"), 1),
        binding(input_source, "input.fdf"),
        (binding(resource_a, "shared.dat"), binding(resource_b, "shared.dat")),
    )

    with pytest.raises(LocalExecutionError, match="BINDING_DESTINATION_COLLISION"):
        LocalExecutor(time_command=str(time_command)).run(spec)
    assert launched is False
    assert destination.exists() is False


@pytest.mark.parametrize(
    "output,code,expected",
    [
        ("Version : 5.4.2\nSCF cycle 1\n", 1, "TRUNCATED_OUTPUT"),
        ("Version : 5.4.2\nSCF cycle 1\nSCF converged\n", 0, "TRUNCATED_OUTPUT"),
        ("MPI_ABORT invoked\n", 1, "MPI_FAILURE"),
        ("Version : 5.4.2\nNaN detected\n", 1, "NUMERICAL_FAILURE"),
    ],
)
def test_runtime_failures_have_clear_classification(output: str, code: int, expected: str):
    assert classify_output(record(output), output, code) == expected


def test_nonzero_exit_takes_precedence_over_normal_converged_markers():
    output = "Version : 5.4.2\nSCF cycle 1\nSCF converged\nJob completed\n"
    parsed = record(output)
    assert parsed.normal_termination is True
    assert parsed.scf_converged is True
    assert classify_output(parsed, output, 1) == "PROCESS_EXIT_FAILURE"


def test_zero_exit_normal_nonconverged_behavior_is_preserved():
    output = "Version : 5.4.2\nSCF cycle 1\nJob completed\n"
    parsed = record(output)
    assert parsed.normal_termination is True
    assert parsed.scf_converged is False
    assert classify_output(parsed, output, 0) == "NORMAL_NONCONVERGED_TERMINATION"


def test_duplicate_run_id_and_overwrite_are_refused(tmp_path: Path):
    destination = tmp_path / "run"; destination.mkdir()
    source = tmp_path / "input"; source.write_text("input")
    spec = LocalRunSpec(
        "same-id", destination,
        LocalExecutionProfile("serial", "direct", str(tmp_path / "engine"), 1), binding(source),
    )
    with pytest.raises(LocalExecutionError, match="RUN_DESTINATION_EXISTS"):
        LocalExecutor().run(spec)


def test_same_run_id_in_a_different_destination_is_refused(tmp_path: Path):
    existing = tmp_path / "first/evidence"; existing.mkdir(parents=True)
    (existing / "summary.json").write_text('{"run_id":"same-id"}\n')
    source = tmp_path / "input"; source.write_text("input")
    spec = LocalRunSpec(
        "same-id", tmp_path / "second",
        LocalExecutionProfile("serial", "direct", str(tmp_path / "engine"), 1), binding(source),
    )
    with pytest.raises(LocalExecutionError, match="DUPLICATE_RUN_ID"):
        LocalExecutor().run(spec)


def summary(energy: float, elapsed: float, tasks: int) -> dict:
    return {
        "exit_code": 0, "normal_termination": True, "scf_started": True,
        "scf_converged": True, "scf_iterations": 10, "number_of_atoms": 50,
        "number_of_species": 1, "final_energy": energy, "NaN_detected": False,
        "MPI_failure_detected": False, "filesystem_failure_detected": False,
        "elapsed_time_seconds": elapsed, "max_rss_kbytes": 100, "tasks": tasks,
    }


def test_comparison_accepts_exact_reported_equality_and_computes_performance():
    result = compare_run_summaries(
        {"serial": summary(-1.0, 10.0, 1), "np2": summary(-1.0, 6.0, 2)}, reference="serial",
    )
    assert result["technical_acceptance"] == "PASS"
    assert result["numeric_consistency"] == "NUMERICALLY_CONSISTENT"
    assert result["numeric_consistency_basis"] == "EXACT_EQUALITY_AT_REPORTED_PRECISION"
    assert result["performance"]["np2"]["speedup_vs_reference"] == pytest.approx(10 / 6)


def test_comparison_requires_review_for_nonzero_delta_without_tolerance():
    result = compare_run_summaries(
        {"serial": summary(-1.0, 10.0, 1), "np2": summary(-1.000001, 6.0, 2)}, reference="serial",
    )
    assert result["numeric_consistency"] == "NUMERIC_DIFFERENCE_REVIEW_REQUIRED"
    assert result["configured_energy_tolerance"] is None
