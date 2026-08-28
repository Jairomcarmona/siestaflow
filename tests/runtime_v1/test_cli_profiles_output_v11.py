from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from qraft.application import ApplicationConfiguration, QraftApplication
from qraft.cli import main
from qraft.execution.adapters import (
    LauncherRegistry, RegisteredLauncher, launcher_registry, scheduler_registry,
)
from qraft.execution.direct_launcher import DirectLauncher
from qraft.execution.openmpi_launcher import OpenMpiLauncher
from qraft.execution.srun_launcher import StepLaunchSpec
from qraft.execution_profiles import ExecutionProfile, ProfileStore
from qraft.output import ExecutionSession, OutputModel, QraftOutputWriter
from qraft.repl import QraftShell


FDF = """SystemName QRAFT CLI profile test
SystemLabel qraft_cli_profile
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


def inputs(root: Path) -> Path:
    fdf = root / "calc with spaces.fdf"
    fdf.write_text(FDF, encoding="utf-8")
    (root / "C.psf").write_text("pseudo\n", encoding="utf-8")
    return fdf


def profile_value(*, command: list[str] | None = None, executable: str = "siesta") -> dict:
    return {
        "schema_version": "1.0",
        "name": "local-mpi",
        "scheduler": "local",
        "launcher": {
            "name": "openmpi",
            "command": command or ["mpirun"],
            "arguments": [],
        },
        "partition": "local",
        "nodes": 1,
        "cpus_per_node": 4,
        "mpi_ranks": 4,
        "cpus_per_rank": 1,
        "walltime": "00:10:00",
        "engine": {"executable": executable, "arguments": []},
        "environment_setup": {
            "module_commands": [],
            "variables": {"OMP_NUM_THREADS": "1"},
        },
    }


def write_profile(root: Path, value: dict, name: str = "local-mpi.json") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def test_external_profile_store_missing_incomplete_and_capacity(tmp_path: Path) -> None:
    project_profiles = tmp_path / ".qraft" / "profiles"
    profile = write_profile(project_profiles, profile_value(), "cluster.json")
    store = ProfileStore(project_root=tmp_path, user_config_root=tmp_path / "user")
    loaded = store.load("cluster")
    assert loaded.source == profile.resolve()
    assert loaded.walltime_seconds == 600
    assert loaded.execution_layer()["launcher"] == "openmpi"

    incomplete = ExecutionProfile.from_mapping({"name": "minimal"})
    assert incomplete.execution_layer() == {}
    with pytest.raises(FileNotFoundError, match="not found"):
        store.load("absent")
    with pytest.raises(ValueError, match="unknown launcher"):
        ExecutionProfile.from_mapping({"name": "bad", "launcher": "missing"})

    fdf = inputs(tmp_path)
    constrained = profile_value()
    constrained["cpus_per_node"] = 2
    constrained["mpi_ranks"] = 1
    constrained_path = write_profile(tmp_path, constrained, "constrained.json")
    app = QraftApplication(ApplicationConfiguration(
        fdf=fdf, profile=constrained_path,
        overrides={"mpi_ranks": 4},
    ))
    with pytest.raises(ValueError, match="exceed profile capacity"):
        app.plan()


def test_profile_and_command_overrides_change_execution_not_science_or_dag(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    profile = write_profile(tmp_path, profile_value())
    app = QraftApplication(ApplicationConfiguration(fdf=fdf, profile=profile))
    first = app.plan()
    second = app.plan(command_overrides={"mpi_ranks": 2, "partition": "override"})
    assert first["scientific_identity"] == second["scientific_identity"]
    assert first["dag"] == second["dag"]
    assert first["execution_spec"]["fingerprint"] != second["execution_spec"]["fingerprint"]
    assert second["execution_spec"]["partition"] == "override"
    assert second["submitted"] is False


def test_launcher_registry_is_extensible_and_openmpi_builds_coordinated_command(tmp_path: Path) -> None:
    registry = LauncherRegistry()
    registry.register(RegisteredLauncher(
        "custom", ("custom-mpi",),
        lambda command, arguments: DirectLauncher(),
    ))
    assert registry.require("custom").default_command == ("custom-mpi",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(registry.require("custom"))

    launcher = OpenMpiLauncher(command=("mpirun",), arguments=("--bind-to", "none"))
    spec = StepLaunchSpec(
        "run", "attempt", tmp_path, tmp_path / "input.fdf",
        tmp_path / "stdout", tmp_path / "stderr", 4, 1, "siesta",
    )
    assert launcher.build_command(spec) == (
        "mpirun", "--bind-to", "none", "-np", "4", "siesta"
    )
    assert "openmpi" in launcher_registry.names()
    assert scheduler_registry.require("slurm").describe().startswith("SLURM")


def test_zero_argument_cli_enters_repl(monkeypatch: pytest.MonkeyPatch) -> None:
    entered: list[bool] = []
    monkeypatch.setattr("qraft.repl.run_repl", lambda: entered.append(True) or 0)
    assert main([]) == 0
    assert entered == [True]


def test_cli_and_repl_use_the_same_resolved_backend_and_plan_never_submits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fdf = inputs(tmp_path)
    profile = write_profile(tmp_path, profile_value())
    assert main([
        "plan", str(fdf), "--profile", str(profile), "--np", "2",
        "--partition", "debug", "--json",
    ]) == 0
    cli_plan = json.loads(capsys.readouterr().out)

    output = io.StringIO()
    app = QraftApplication()
    shell = QraftShell(app, stdout=output)
    assert shell.onecmd(f"fdf {shlex_quote(fdf)}") is False
    assert shell.onecmd(f"profile {shlex_quote(profile)}") is False
    assert shell.onecmd("np 2") is False
    assert shell.onecmd("partition debug") is False
    assert shell.onecmd("plan") is False
    repl_plan = app.plan()
    assert cli_plan["execution_spec"] == json.loads(json.dumps(repl_plan["execution_spec"]))
    assert cli_plan["scientific_identity"] == repl_plan["scientific_identity"]
    assert "No jobs submitted." in output.getvalue()
    assert not (tmp_path / ".qraft-runs").exists()


def shlex_quote(path: Path) -> str:
    import shlex

    return shlex.quote(str(path))


def test_repl_help_show_invalid_command_and_clean_exit(tmp_path: Path) -> None:
    output = io.StringIO()
    shell = QraftShell(stdout=output, stdin=io.StringIO("help run\ninvalid\nexit\n"))
    shell.use_rawinput = False
    shell.cmdloop()
    text = output.getvalue()
    assert "run [FDF]" in text
    assert "Unknown syntax: invalid" in text
    assert shell.onecmd("show") is False
    assert "UNCONFIGURED" in output.getvalue()


def test_repl_openmpi_functional_run_output_sessions_recovery_and_diagnostic(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    fake_mpirun = tmp_path / "fake mpirun.py"
    fake_siesta = tmp_path / "fake siesta.py"
    fake_mpirun.write_text(
        "import subprocess,sys\n"
        "data=sys.stdin.buffer.read()\n"
        "i=sys.argv.index('-np')\n"
        "p=subprocess.run(sys.argv[i+2:],input=data,capture_output=True)\n"
        "sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr)\n"
        "raise SystemExit(p.returncode)\n",
        encoding="utf-8",
    )
    fake_siesta.write_text(
        "import sys\nsys.stdin.read()\nprint('Siesta started')\n"
        "print('SCF cycle 1')\nprint('SCF converged')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    value = profile_value(command=[sys.executable, str(fake_mpirun)], executable=sys.executable)
    value["engine"]["arguments"] = [str(fake_siesta)]
    profile = write_profile(tmp_path, value)
    runs = tmp_path / "runs with spaces"
    app = QraftApplication(ApplicationConfiguration(runs_root=runs))
    output = io.StringIO()
    shell = QraftShell(app, stdout=output)
    for command in (
        f"fdf {shlex_quote(fdf)}",
        f"profile {shlex_quote(profile)}",
        "np 4",
        "launcher openmpi",
        "show resolved",
        "plan",
        "run",
        "resume",
        "attempts",
    ):
        assert shell.onecmd(command) is False
    manifests = tuple(runs.rglob("attempt.json"))
    assert len(manifests) == 1
    text = (runs / "qraft.out").read_text(encoding="utf-8")
    assert text.count("QRAFT EXECUTION SESSION") == 2
    assert "Mode             : NEW" in text and "Mode             : RECOVERY" in text
    assert "SESSION RESULT : COMPLETED" in text
    assert "[EXECUTION]" in text and "[IDENTITY]" in text
    assert "fake mpirun.py" in text and "-np 4" in text
    assert "runs with spaces" not in next(
        line for line in text.splitlines() if line.startswith("Workdir")
    )
    assert "REUSED_VALIDATED_ATTEMPT" in text

    fake_siesta.write_text(
        "import sys\nsys.stdin.read()\nprint('Siesta started')\n"
        "print('SCF did not converge')\nprint('FATAL termination')\n",
        encoding="utf-8",
    )
    failed = app.run(force_new_attempt=True, invocation="qraft> run --force-new-attempt")
    assert failed["attempt"]["result"]["technical_validation"]["status"] == "FAIL"
    failed_text = (runs / "qraft.out").read_text(encoding="utf-8")
    assert "[DIAGNOSTIC]" in failed_text
    assert "Relevant output:" in failed_text and "FATAL termination" in failed_text
    assert "SESSION RESULT : FAILED" in failed_text


def test_writer_appends_unambiguous_sessions(tmp_path: Path) -> None:
    writer = QraftOutputWriter(tmp_path / "qraft.out", campaign_root=tmp_path)
    writer.initialize(OutputModel(header={"Campaign root": str(tmp_path)}))
    for epoch, mode in ((1, "NEW"), (2, "RECOVERY")):
        writer.start_session(ExecutionSession(
            f"session-{epoch}", epoch, mode, f"2026-08-19T00:00:0{epoch}Z",
            "qraft run calc.fdf", "FAILED" if epoch > 1 else None, str(tmp_path),
        ))
        writer.finish_session(
            result="COMPLETED", finished=f"2026-08-19T00:01:0{epoch}Z",
            elapsed_seconds=60.0,
        )
    text = writer.path.read_text(encoding="utf-8")
    assert text.count("QRAFT EXECUTION SESSION") == 2
    assert "Session ID       : session-1" in text
    assert "Controller epoch : 2" in text
    assert text.count("SESSION RESULT : COMPLETED") == 2
