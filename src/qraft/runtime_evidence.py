"""Conservative technology-specific producers of runtime compatibility facts."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]
RuntimeEvidenceProbe = Callable[
    [str | None, str | None, Mapping[str, str]],
    tuple[Mapping[str, Mapping[str, str]], Mapping[str, Sequence[str]]],
]


def _resolved_executable(value: str | None, which: Which) -> str | None:
    if not value:
        return None
    if any(separator in value for separator in ("/", "\\")):
        path = Path(value).expanduser()
        return str(path.resolve()) if path.is_file() else None
    return which(value)


def _elf_mpi_instance(
    executable: str | None, *, which: Which, runner: Runner,
) -> tuple[dict[str, str], list[str]]:
    resolved = _resolved_executable(executable, which)
    ldd = which("ldd")
    if resolved is None or ldd is None:
        return {}, []
    try:
        result = runner(
            [ldd, resolved], capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}, []
    if result.returncode != 0:
        return {}, []
    roots: set[str] = set()
    for line in ((result.stdout or "") + "\n" + (result.stderr or "")).splitlines():
        match = re.match(
            r"^\s*libmpi(?:fort|cxx)?\.so(?:\.\d+)*\s+=>\s+(\S+)", line
        )
        if match is None:
            continue
        library = Path(match.group(1))
        try:
            canonical = library.resolve(strict=True)
        except OSError:
            continue
        root = next(
            (parent.parent for parent in canonical.parents if parent.name in {"lib", "lib64"}),
            None,
        )
        if root is not None:
            roots.add(str(root.resolve()))
    if len(roots) == 1:
        return {"mpi_runtime_instance": roots.pop()}, []
    if len(roots) > 1:
        return {}, ["multiple canonical MPI runtime instances observed"]
    return {}, []


def observe_runtime_evidence(
    engine_executable: str | None,
    launcher_executable: str | None,
    environment: Mapping[str, str],
    *,
    which: Which = shutil.which,
    runner: Runner = subprocess.run,
) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """Observe strict runtime-instance facts; absent evidence remains absent."""

    engine, engine_conflicts = _elf_mpi_instance(
        engine_executable, which=which, runner=runner
    )
    launcher, launcher_conflicts = _elf_mpi_instance(
        launcher_executable, which=which, runner=runner
    )
    environment_facts: dict[str, str] = {}
    root = environment.get("I_MPI_ROOT")
    if root:
        try:
            path = Path(root).expanduser().resolve(strict=True)
        except OSError:
            pass
        else:
            if path.is_dir():
                environment_facts["mpi_runtime_instance"] = str(path)
    conflicts = {
        name: values
        for name, values in (
            ("engine", engine_conflicts), ("launcher", launcher_conflicts)
        )
        if values
    }
    return {
        "engine": engine,
        "launcher": launcher,
        "environment": environment_facts,
    }, conflicts
