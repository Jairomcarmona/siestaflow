"""Task-local attempt numbers must not collide in shared launcher instances."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

from qraft.execution.direct_launcher import DirectLauncher
from qraft.execution.hydra_launcher import HydraLauncher
from qraft.execution.openmpi_launcher import OpenMpiLauncher
from qraft.execution.srun_launcher import SrunLauncher, StepLaunchSpec


class ControlledProcess:
    """Expose barriers after registration without relying on timing or MPI."""

    def __init__(self) -> None:
        self.waiting = Event()
        self.finished = Event()
        self.returncode: int | None = None
        self.signals: list[str] = []

    def wait(self) -> int:
        self.waiting.set()
        assert self.finished.wait(10), "test process was not released"
        assert self.returncode is not None
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def complete(self, code: int = 0) -> None:
        self.returncode = code
        self.finished.set()

    def terminate(self) -> None:
        self.signals.append("terminate")
        self.complete(-15)

    def kill(self) -> None:
        self.signals.append("kill")
        self.complete(-9)


def _spec(tmp_path: Path, task_id: str) -> StepLaunchSpec:
    workdir = tmp_path / task_id
    workdir.mkdir()
    input_path = workdir / "input.fdf"
    input_path.write_text("", encoding="utf-8")
    return StepLaunchSpec(
        task_id=task_id,
        attempt_id="attempt-0001",
        workdir=workdir,
        input_path=input_path,
        stdout_path=workdir / "stdout.txt",
        stderr_path=workdir / "stderr.txt",
        mpi_processes=1,
        cpus_per_process=1,
        executable="unused-test-command",
        hosts=("localhost",),
        nodes=1,
        processes_per_node=1,
    )


@pytest.fixture(params=["direct", "openmpi", "srun", "hydra"])
def launcher_and_processes(request):
    processes = {name: ControlledProcess() for name in ("task-a", "task-b")}

    def factory(command, *, cwd, **kwargs):
        return processes[cwd.name]

    launchers = {
        "direct": lambda: DirectLauncher(popen_factory=factory),
        "openmpi": lambda: OpenMpiLauncher(popen_factory=factory),
        "srun": lambda: SrunLauncher(srun_command=("srun",), popen_factory=factory),
        "hydra": lambda: HydraLauncher(
            arguments=("-bootstrap", "ssh"), popen_factory=factory
        ),
    }
    return launchers[request.param](), processes


@pytest.mark.parametrize("kill", [False, True])
def test_cancel_all_tasks_with_same_attempt_number(
    tmp_path: Path, launcher_and_processes, kill: bool
) -> None:
    launcher, processes = launcher_and_processes
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        try:
            for task_id, process in processes.items():
                futures.append(executor.submit(launcher.launch, _spec(tmp_path, task_id)))
                assert process.waiting.wait(5)
            # Keep the public return contract: one task-local attempt ID per process.
            assert launcher.terminate_all(kill=kill) == ("attempt-0001", "attempt-0001")
            for task_id, future in zip(processes, futures):
                outcome = future.result(timeout=5)
                assert (outcome.task_id, outcome.attempt_id) == (task_id, "attempt-0001")
                assert outcome.terminated_by_controller
                assert outcome.exit_code == (-9 if kill else -15)
                assert processes[task_id].signals == ["kill" if kill else "terminate"]
            assert launcher.terminate_all() == ()
        finally:
            for process in processes.values():
                if process.poll() is None:
                    process.complete()


def test_completing_one_task_keeps_other_task_cancellable(
    tmp_path: Path, launcher_and_processes
) -> None:
    launcher, processes = launcher_and_processes
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}
        try:
            for task_id, process in processes.items():
                futures[task_id] = executor.submit(launcher.launch, _spec(tmp_path, task_id))
                assert process.waiting.wait(5)
            processes["task-a"].complete()
            completed = futures["task-a"].result(timeout=5)
            assert completed.exit_code == 0
            assert not completed.terminated_by_controller
            assert launcher.terminate_all() == ("attempt-0001",)
            cancelled = futures["task-b"].result(timeout=5)
            assert cancelled.exit_code == -15
            assert cancelled.terminated_by_controller
            assert processes["task-a"].signals == []
            assert processes["task-b"].signals == ["terminate"]
        finally:
            for process in processes.values():
                if process.poll() is None:
                    process.complete()


@pytest.mark.parametrize("launcher_class", [SrunLauncher, HydraLauncher])
def test_active_attempts_retains_task_local_string_contract(tmp_path: Path, launcher_class):
    processes = {name: ControlledProcess() for name in ("task-a", "task-b")}

    def factory(command, *, cwd, **kwargs):
        return processes[cwd.name]

    if launcher_class is SrunLauncher:
        launcher = launcher_class(srun_command=("srun",), popen_factory=factory)
    else:
        launcher = launcher_class(arguments=("-bootstrap", "ssh"), popen_factory=factory)
    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            for task_id, process in processes.items():
                executor.submit(launcher.launch, _spec(tmp_path, task_id))
                assert process.waiting.wait(5)
            assert launcher.active_attempts == ("attempt-0001", "attempt-0001")
        finally:
            for process in processes.values():
                process.complete()
    assert launcher.active_attempts == ()


@pytest.mark.parametrize("kill", [False, True])
def test_direct_launcher_cancels_two_real_local_processes(tmp_path: Path, kill: bool):
    waiting = {name: Event() for name in ("task-a", "task-b")}
    processes = []

    def factory(command, *, cwd, **kwargs):
        process = subprocess.Popen(command, cwd=cwd, **kwargs)
        processes.append(process)
        original_wait = process.wait

        def wait(*args, **wait_kwargs):
            waiting[cwd.name].set()
            return original_wait(*args, **wait_kwargs)

        process.wait = wait
        return process

    launcher = DirectLauncher(popen_factory=factory)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        try:
            for task_id, ready in waiting.items():
                spec = replace(
                    _spec(tmp_path, task_id), executable=sys.executable,
                    executable_arguments=("-c", "import time; time.sleep(15)"),
                )
                futures.append(executor.submit(launcher.launch, spec))
                assert ready.wait(5)
            assert all(process.poll() is None for process in processes)
            assert launcher.terminate_all(kill=kill) == ("attempt-0001", "attempt-0001")
            for future in futures:
                outcome = future.result(timeout=5)
                assert outcome.exit_code != 0
                assert outcome.terminated_by_controller
            assert all(process.poll() is not None for process in processes)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
