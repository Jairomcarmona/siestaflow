from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

import qraft
from qraft.application import ApplicationConfiguration, QraftApplication
from qraft.cli import main
from qraft.errors import PreflightError
from qraft.repl import QraftShell


FDF = """SystemName installed product test
SystemLabel installed_product
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
    root.mkdir(parents=True, exist_ok=True)
    fdf = root / "calc with spaces.fdf"
    fdf.write_text(FDF, encoding="utf-8")
    (root / "C.psf").write_text("pseudo\n", encoding="utf-8")
    return fdf


def profile(root: Path, python: str, script: Path) -> Path:
    path = root / ".qraft" / "profiles" / "local.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "name": "local",
        "scheduler": "local",
        "launcher": {"name": "direct", "command": [], "arguments": []},
        "partition": "local",
        "nodes": 1,
        "cpus_per_node": 1,
        "mpi_ranks": 1,
        "cpus_per_rank": 1,
        "engine": {"executable": python, "arguments": [str(script)]},
    }, indent=2), encoding="utf-8")
    return path


def test_public_api_is_intentional() -> None:
    expected = {
        "ApplicationConfiguration", "BandPathMode", "BandPathPlanner",
        "BandPathProposal", "BandPathRequest", "BandPathSegment",
        "CollinearMomentToken", "CollinearSpinMoment", "CollinearSpinSpec",
        "NonCollinearSpinMoment", "NonCollinearSpinSpec",
        "SpinOrbitSpec",
        "CrystalStructure", "EngineAdapter", "ExecutionProfile",
        "ExecutionSpec", "LauncherAdapter", "OutputModel", "ProfileStore",
        "ProviderPath", "QraftApplication", "SchedulerAdapter",
        "ScientificIdentity", "SymmetryAnalysis", "SymmetryPathProvider",
        "__version__",
    }
    assert set(qraft.__all__) == expected
    assert qraft.__version__ == "0.2.0"
    assert qraft.ExecutionSpec.__name__ == "ExecutionSpec"
    assert qraft.QraftApplication.__name__ == "QraftApplication"


def test_public_cli_environment_config_validate_and_profiles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fdf = inputs(tmp_path)
    script = tmp_path / "fake.py"
    script.write_text(
        "import sys\nsys.stdin.read()\nprint('Siesta started')\n"
        "print('SCF converged')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    selected = profile(tmp_path, sys.executable, script)

    assert main(["profile", "show", str(selected), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["config", "--profile", str(selected), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["execution"]["launcher"] == "direct"
    assert main(["env", "--profile", str(selected), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "READY"
    assert main(["validate", str(fdf), "--profile", str(selected), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    assert main(["env", "--profile", "missing-profile", "--json"]) == 0
    missing = json.loads(capsys.readouterr().out)
    assert missing["profile"]["status"] == "INVALID"
    with pytest.raises(SystemExit) as help_exit:
        main(["run", "--help"])
    assert help_exit.value.code == 0
    assert "qraft run" in capsys.readouterr().out


def test_run_preflight_blocks_before_attempt_or_session(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    runs = tmp_path / "runs"
    app = QraftApplication(ApplicationConfiguration(
        fdf=fdf, runs_root=runs,
        overrides={"launcher": "direct", "executable": "definitely-missing-qraft-engine"},
    ))
    report = app.validate()
    assert report["status"] == "BLOCKED"
    assert any(item["name"] == "Engine" and item["status"] == "BLOCKED" for item in report["checks"])
    with pytest.raises(PreflightError, match="Engine"):
        app.run()
    assert not runs.exists()


def test_repl_uses_shared_env_config_validate_backend(tmp_path: Path) -> None:
    fdf = inputs(tmp_path)
    fake = tmp_path / "fake.py"
    fake.write_text("print('not executed by validate')\n", encoding="utf-8")
    selected = profile(tmp_path, sys.executable, fake)
    app = QraftApplication(ApplicationConfiguration(fdf=fdf, profile=selected))
    output = io.StringIO()
    shell = QraftShell(app, stdout=output)
    for command in ("env", "config", "profile validate", "validate"):
        assert shell.onecmd(command) is False
    text = output.getvalue()
    assert "QRAFT ENVIRONMENT" in text
    assert "QRAFT CONFIGURATION" in text
    assert "PRE-FLIGHT" in text and "Execution profile" in text


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_qraft(root: Path) -> Path:
    return root / ("Scripts/qraft.exe" if os.name == "nt" else "bin/qraft")


def test_wheel_clean_room_installed_cli_run_and_recovery(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    build_python = os.environ.get("QRAFT_BUILD_PYTHON")
    if not build_python:
        pytest.skip("release build tooling is not installed; set QRAFT_BUILD_PYTHON")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    build = subprocess.run(
        [build_python, "-m", "pip", "wheel", ".", "--no-deps",
         "--no-build-isolation", "--wheel-dir", str(wheelhouse)],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = tuple(wheelhouse.glob("qraft-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
    assert "qraft/engines/siesta/data/validation_rules_5.4.2.json" in names
    assert not any(
        token in name.casefold()
        for name in names
        for token in ("tests/", "remote_validation", "scratch", ".zip")
    )

    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = _venv_python(environment)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", "--no-cache-dir",
         "--force-reinstall", str(wheels[0])],
        capture_output=True, text=True, check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    user = tmp_path / "user project"
    fdf = inputs(user)
    fake = user / "fake siesta.py"
    fake.write_text(
        "import sys\nsys.stdin.read()\nprint('Siesta started')\n"
        "print('SCF cycle 1')\nprint('SCF converged')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    selected = profile(user, str(python), fake)
    runs = user / "runs"
    command = _venv_qraft(environment)
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)

    def invoke(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(command), *arguments], cwd=user, env=clean_env,
            input=input_text, capture_output=True, text=True, check=False,
        )

    imported = subprocess.run(
        [str(python), "-c", "import qraft; print(qraft.__version__)"],
        cwd=user, env=clean_env, capture_output=True, text=True, check=False,
    )
    assert imported.returncode == 0 and imported.stdout.strip() == "0.2.0"
    assert str(repo) not in imported.stdout + imported.stderr
    assert invoke("--version").returncode == 0
    assert invoke("--help").returncode == 0
    assert invoke(input_text="exit\n").returncode == 0
    assert invoke("env", "--profile", str(selected), "--json").returncode == 0
    assert invoke("config", "--profile", str(selected), "--json").returncode == 0
    assert invoke("validate", str(fdf), "--profile", str(selected), "--json").returncode == 0
    planned = invoke("plan", str(fdf), "--profile", str(selected), "--json")
    assert planned.returncode == 0 and json.loads(planned.stdout)["submitted"] is False
    first = invoke(
        "run", str(fdf), "--profile", str(selected),
        "--runs-root", str(runs), "--json",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout)["attempt"]["result"]["technical_validation"]["status"] == "PASS"
    assert invoke("status", "--runs-root", str(runs), "--json").returncode == 0
    resumed = invoke("resume", "--runs-root", str(runs), "--json")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert json.loads(resumed.stdout)["status"] == "REUSED_VALIDATED_ATTEMPT"
    assert len(tuple(runs.glob("*/*/attempt.json"))) == 1
