from __future__ import annotations

import subprocess
from pathlib import Path

from qraft.environment_check import (
    EnvironmentChecker,
    EnvironmentCheckRequest,
)
from qraft.validation_render import render_validation_report


def completed(
    command,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_environment_check_reports_resolved_mpi_siesta_and_slurm(tmp_path: Path):
    commands = {
        name: f"/usr/bin/{name}"
        for name in ("siesta", "srun", "sbatch", "squeue", "scontrol", "sinfo")
    }

    def run(command, **_kwargs):
        if command[-1] == "--version" and "siesta" in command[0]:
            return completed(
                command,
                stdout="Version : 5.4.2\nParallelisations: MPI\n",
            )
        return completed(command, stdout="slurm-wlm 23.11.4\n")

    report = EnvironmentChecker(
        which=commands.get,
        runner=run,
        environ={"SLURM_JOB_ID": "42"},
        python_version=(3, 12, 3),
    ).check(
        EnvironmentCheckRequest(
            launcher="auto",
            require_slurm=True,
            working_directory=tmp_path,
        )
    )

    assert report.status.value == "PASS"
    assert report.subject.attributes["launcher_selected"] == "srun"
    assert report.subject.attributes["siesta_version"] == "5.4.2"
    assert report.metadata["job_submitted"] is False


def test_missing_siesta_is_blocked_with_remediation(tmp_path: Path):
    report = EnvironmentChecker(
        which=lambda _name: None,
        environ={},
        python_version=(3, 12, 0),
    ).check(EnvironmentCheckRequest(working_directory=tmp_path))

    assert report.status.value == "BLOCKED"
    finding = next(
        item for item in report.findings
        if item.code == "SIESTA_EXECUTABLE_MISSING"
    )
    assert "--siesta" in (finding.hint or "")
    assert "Suggested action:" in render_validation_report(
        report,
        title="ENVIRONMENT CHECK",
    )


def test_mpi_launcher_rejects_serial_siesta(tmp_path: Path):
    commands = {
        "siesta": "/usr/bin/siesta",
        "mpiexec": "/usr/bin/mpiexec",
    }

    def run(command, **_kwargs):
        return completed(
            command,
            stdout="Version : 5.4.2\nParallelisations: none\n",
        )

    report = EnvironmentChecker(
        which=commands.get,
        runner=run,
        environ={},
        python_version=(3, 12, 0),
    ).check(
        EnvironmentCheckRequest(
            launcher="mpiexec",
            working_directory=tmp_path,
        )
    )

    assert report.status.value == "FAIL"
    assert "SIESTA_MPI_REQUIRED" in {
        finding.code for finding in report.findings
    }


def test_successful_non_siesta_executable_is_rejected(tmp_path: Path):
    report = EnvironmentChecker(
        which=lambda name: f"/usr/bin/{name}",
        runner=lambda command, **_kwargs: completed(
            command,
            stdout="Python 3.12.3\n",
        ),
        environ={},
        python_version=(3, 12, 0),
    ).check(
        EnvironmentCheckRequest(
            launcher="direct",
            working_directory=tmp_path,
        )
    )

    assert report.status.value == "FAIL"
    assert "SIESTA_IDENTITY_UNCONFIRMED" in {
        finding.code for finding in report.findings
    }


def test_environment_check_is_read_only(tmp_path: Path):
    before = tuple(tmp_path.iterdir())
    EnvironmentChecker(
        which=lambda _name: None,
        environ={},
        python_version=(3, 12, 0),
    ).check(EnvironmentCheckRequest(working_directory=tmp_path))
    assert tuple(tmp_path.iterdir()) == before
