"""Generic, no-overwrite execution of a local stdin-driven engine.

Scientific inputs and machine-specific commands live in external profiles.  The
executor owns only runtime validation, isolated directories, evidence capture,
and delegation of output interpretation to an injected parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .engines.siesta.models import SiestaOutputRecord
from .engines.siesta.output_parser import SiestaOutputParser
from .project_packages import load_structured


class LocalExecutionError(RuntimeError):
    """A classified failure at a local execution trust boundary."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}:{detail}" if detail else code)


class OutputParser(Protocol):
    def parse(self, lines: Sequence[str]) -> SiestaOutputRecord: ...


@dataclass(frozen=True)
class LocalExecutionProfile:
    name: str
    launcher: str
    executable: str
    tasks: int
    environment: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path, name: str) -> "LocalExecutionProfile":
        profiles = load_structured(path).get("profiles")
        if not isinstance(profiles, dict) or not isinstance(profiles.get(name), dict):
            raise LocalExecutionError("PROFILE_NOT_FOUND", name)
        raw = profiles[name]
        environment = raw.get("environment", {})
        if not isinstance(environment, dict):
            raise LocalExecutionError("INVALID_ENVIRONMENT", name)
        return cls(
            name=name,
            launcher=str(raw.get("launcher", "")),
            executable=str(raw.get("executable", "")),
            tasks=raw.get("tasks"),
            environment={str(key): str(value) for key, value in environment.items()},
        )


@dataclass(frozen=True)
class InputBinding:
    source: Path
    destination: str
    sha256: str


@dataclass(frozen=True)
class LocalRunSpec:
    run_id: str
    destination: Path
    profile: LocalExecutionProfile
    input_binding: InputBinding
    resources: tuple[InputBinding, ...] = ()


@dataclass(frozen=True)
class LocalRunResult:
    run_id: str
    exit_code: int
    termination_class: str
    summary_path: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def validate_profile(profile: LocalExecutionProfile) -> tuple[Path, str | None, str, str | None]:
    if not isinstance(profile.tasks, int) or isinstance(profile.tasks, bool) or profile.tasks < 1:
        raise LocalExecutionError("INVALID_TASK_COUNT", str(profile.tasks))
    executable = _expand_path(profile.executable)
    if not executable.is_file():
        raise LocalExecutionError("EXECUTABLE_MISSING", str(executable))
    if not os.access(executable, os.X_OK):
        raise LocalExecutionError("EXECUTABLE_NOT_RUNNABLE", str(executable))
    launcher: str | None
    if profile.launcher == "direct":
        launcher = None
        if profile.tasks != 1:
            raise LocalExecutionError("DIRECT_LAUNCH_REQUIRES_ONE_TASK")
    else:
        launcher = shutil.which(profile.launcher)
        if launcher is None:
            raise LocalExecutionError("LAUNCHER_MISSING", profile.launcher)
    probe = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, timeout=30, check=False,
    )
    version = probe.stdout + probe.stderr
    if probe.returncode != 0:
        raise LocalExecutionError("EXECUTABLE_VERSION_PROBE_FAILED", str(probe.returncode))
    if launcher is not None and not re.search(r"Parallelisations\s*:\s*.*\bMPI\b", version, re.I):
        raise LocalExecutionError("EXECUTABLE_NOT_MPI")
    launcher_version = None
    if launcher is not None:
        launcher_probe = subprocess.run(
            [launcher, "--version"], capture_output=True, text=True, timeout=30, check=False,
        )
        launcher_version = launcher_probe.stdout + launcher_probe.stderr
        if launcher_probe.returncode != 0:
            raise LocalExecutionError("LAUNCHER_VERSION_PROBE_FAILED", str(launcher_probe.returncode))
    return executable, launcher, version, launcher_version


def _validate_binding_destinations(bindings: Sequence[InputBinding]) -> None:
    seen: set[str] = set()
    for binding in bindings:
        destination = Path(binding.destination)
        if destination.is_absolute() or ".." in destination.parts or not binding.destination:
            raise LocalExecutionError("UNSAFE_INPUT_DESTINATION", binding.destination)
        if binding.destination in seen:
            raise LocalExecutionError("BINDING_DESTINATION_COLLISION", binding.destination)
        seen.add(binding.destination)


def validate_bindings(bindings: Sequence[InputBinding], *, missing_code: str | None = None) -> None:
    _validate_binding_destinations(bindings)
    for binding in bindings:
        if not binding.source.is_file():
            code = missing_code or ("INPUT_MISSING" if len(bindings) == 1 else "RESOURCE_MISSING")
            raise LocalExecutionError(code, str(binding.source))
        actual = sha256_file(binding.source)
        if actual != binding.sha256:
            raise LocalExecutionError("INPUT_HASH_MISMATCH", binding.destination)


def classify_output(record: SiestaOutputRecord, raw: str, exit_code: int) -> str:
    if re.search(r"\bnan\b", raw, re.I):
        return "NUMERICAL_FAILURE"
    if re.search(r"\b(?:MPI_ABORT|MPI failure|PMI error|mpirun.*error)\b", raw, re.I):
        return "MPI_FAILURE"
    if re.search(r"(?:no space left|read-only file system|permission denied|I/O error)", raw, re.I):
        return "FILESYSTEM_FAILURE"
    if record.normal_termination and exit_code != 0:
        return "PROCESS_EXIT_FAILURE"
    if record.normal_termination and record.scf_converged and exit_code == 0:
        return "NORMAL_CONVERGED_TERMINATION"
    if record.normal_termination:
        return "NORMAL_NONCONVERGED_TERMINATION"
    if record.started or record.scf_started:
        return "TRUNCATED_OUTPUT"
    return "UNKNOWN_FAILURE"


def _time_fields(text: str) -> tuple[float | None, int | None]:
    elapsed = None
    match = re.search(r"Elapsed \(wall clock\) time .*?:\s*((?:(\d+):)?(\d+):(\d+(?:\.\d+)?))", text)
    if match:
        hours = int(match.group(2) or 0)
        elapsed = hours * 3600 + int(match.group(3)) * 60 + float(match.group(4))
    match = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", text)
    return elapsed, int(match.group(1)) if match else None


class LocalExecutor:
    """Run once into a new isolated destination and emit machine-readable evidence."""

    def __init__(self, parser: OutputParser | None = None, *, time_command: str = "/usr/bin/time") -> None:
        self.parser = parser or SiestaOutputParser()
        self.time_command = time_command

    def run(self, spec: LocalRunSpec) -> LocalRunResult:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec.run_id):
            raise LocalExecutionError("INVALID_RUN_ID", spec.run_id)
        if spec.destination.exists():
            raise LocalExecutionError("RUN_DESTINATION_EXISTS", str(spec.destination))
        for summary_path in spec.destination.parent.glob("*/evidence/summary.json"):
            try:
                observed_id = json.loads(summary_path.read_text(encoding="utf-8")).get("run_id")
            except (OSError, json.JSONDecodeError):
                continue
            if observed_id == spec.run_id:
                raise LocalExecutionError("DUPLICATE_RUN_ID", spec.run_id)
        bindings = (spec.input_binding, *spec.resources)
        _validate_binding_destinations(bindings)
        executable, launcher, version, launcher_version = validate_profile(spec.profile)
        validate_bindings((spec.input_binding,), missing_code="INPUT_MISSING")
        validate_bindings(spec.resources, missing_code="RESOURCE_MISSING")
        if not Path(self.time_command).is_file():
            raise LocalExecutionError("TIME_COMMAND_MISSING", self.time_command)

        registry = spec.destination.parent / ".run_ids"
        registry.mkdir(parents=True, exist_ok=True)
        try:
            (registry / spec.run_id).mkdir()
        except FileExistsError as exc:
            raise LocalExecutionError("DUPLICATE_RUN_ID", spec.run_id) from exc

        for name in ("input", "work", "results", "evidence"):
            (spec.destination / name).mkdir(parents=True, exist_ok=False)
        copied: dict[str, str] = {}
        for binding in bindings:
            archive = spec.destination / "input" / binding.destination
            work = spec.destination / "work" / binding.destination
            archive.parent.mkdir(parents=True, exist_ok=True)
            work.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(binding.source, archive)
            shutil.copyfile(binding.source, work)
            copied[binding.destination] = sha256_file(work)

        command = [str(executable)] if launcher is None else [launcher, "-np", str(spec.profile.tasks), str(executable)]
        stdout_path = spec.destination / "results/siesta.out"
        stderr_path = spec.destination / "results/siesta.err"
        time_path = spec.destination / "results/siesta.time"
        input_path = spec.destination / "work" / spec.input_binding.destination
        environment = os.environ.copy()
        environment.update(spec.profile.environment)
        timed = [self.time_command, "-v", "-o", str(time_path), *command]
        with input_path.open("rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(
                timed, cwd=spec.destination / "work", env=environment,
                stdin=stdin, stdout=stdout, stderr=stderr, check=False,
            )
        raw = stdout_path.read_text(errors="replace") + "\n" + stderr_path.read_text(errors="replace")
        record = self.parser.parse(raw.splitlines(True))
        elapsed, max_rss = _time_fields(time_path.read_text(errors="replace"))
        termination = classify_output(record, raw, completed.returncode)
        summary = {
            "run_id": spec.run_id,
            "profile": spec.profile.name,
            "launcher": profile_launcher(spec.profile, launcher),
            "tasks": spec.profile.tasks,
            "executable": str(executable),
            "command": timed,
            "hostname": socket.gethostname(),
            "exit_code": completed.returncode,
            "normal_termination": record.normal_termination,
            "termination_class": termination,
            "scf_started": record.scf_started,
            "scf_iterations": record.scf_iterations,
            "scf_converged": record.scf_converged,
            "number_of_atoms": record.atoms,
            "number_of_species": record.species,
            "final_energy": record.energies[-1] if record.energies else None,
            "NaN_detected": bool(re.search(r"\bnan\b", raw, re.I)),
            "MPI_failure_detected": termination == "MPI_FAILURE",
            "filesystem_failure_detected": termination == "FILESYSTEM_FAILURE",
            "elapsed_time_seconds": elapsed,
            "max_rss_kbytes": max_rss,
            "input_hashes": copied,
            "siesta_version_output": version,
            "launcher_version_output": launcher_version,
        }
        summary_path = spec.destination / "evidence/summary.json"
        summary_path.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (spec.destination / "evidence/command.json").write_text(
            json.dumps({"argv": timed, "environment": dict(spec.profile.environment)}, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return LocalRunResult(spec.run_id, completed.returncode, termination, summary_path)


def profile_launcher(profile: LocalExecutionProfile, resolved: str | None) -> str:
    return "direct" if profile.launcher == "direct" else str(resolved)


def compare_run_summaries(
    summaries: Mapping[str, Mapping[str, object]], *,
    reference: str, energy_tolerance: float | None = None,
) -> dict[str, object]:
    """Compare observed results without silently inventing scientific tolerance."""
    if reference not in summaries or len(summaries) < 2:
        raise LocalExecutionError("INVALID_COMPARISON_SET")
    required = {
        "exit_code", "normal_termination", "scf_started", "scf_converged",
        "scf_iterations", "number_of_atoms", "number_of_species", "final_energy",
        "NaN_detected", "MPI_failure_detected", "filesystem_failure_detected",
        "elapsed_time_seconds", "max_rss_kbytes", "tasks",
    }
    for name, summary in summaries.items():
        missing = required - set(summary)
        if missing:
            raise LocalExecutionError("INCOMPLETE_RUN_SUMMARY", f"{name}:{sorted(missing)}")
    labels = list(summaries)
    deltas: dict[str, float] = {}
    for index, left in enumerate(labels):
        for right in labels[index + 1:]:
            deltas[f"{left}__{right}"] = float(summaries[left]["final_energy"]) - float(
                summaries[right]["final_energy"]
            )
    if all(delta == 0.0 for delta in deltas.values()):
        consistency = "NUMERICALLY_CONSISTENT"
        basis = "EXACT_EQUALITY_AT_REPORTED_PRECISION"
    elif energy_tolerance is not None and energy_tolerance >= 0 and all(
        abs(delta) <= energy_tolerance for delta in deltas.values()
    ):
        consistency = "NUMERICALLY_CONSISTENT"
        basis = "CONFIGURED_TOLERANCE"
    else:
        consistency = "NUMERIC_DIFFERENCE_REVIEW_REQUIRED"
        basis = "NO_CONFIGURED_TOLERANCE" if energy_tolerance is None else "OUTSIDE_CONFIGURED_TOLERANCE"
    reference_time = float(summaries[reference]["elapsed_time_seconds"])
    performance = {}
    for name, summary in summaries.items():
        elapsed = float(summary["elapsed_time_seconds"])
        tasks = int(summary["tasks"])
        speedup = reference_time / elapsed
        performance[name] = {
            "elapsed_time_seconds": elapsed,
            "max_rss_kbytes": int(summary["max_rss_kbytes"]),
            "tasks": tasks,
            "speedup_vs_reference": speedup,
            "parallel_efficiency": speedup / tasks,
        }
    technical_pass = all(
        int(item["exit_code"]) == 0
        and item["normal_termination"] is True
        and item["scf_started"] is True
        and item["scf_converged"] is True
        and item["NaN_detected"] is False
        and item["MPI_failure_detected"] is False
        and item["filesystem_failure_detected"] is False
        for item in summaries.values()
    )
    technical_pass = technical_pass and len({item["number_of_atoms"] for item in summaries.values()}) == 1
    technical_pass = technical_pass and len({item["number_of_species"] for item in summaries.values()}) == 1
    return {
        "reference": reference,
        "technical_acceptance": "PASS" if technical_pass else "FAIL",
        "numeric_consistency": consistency,
        "numeric_consistency_basis": basis,
        "configured_energy_tolerance": energy_tolerance,
        "energy_deltas_ev": deltas,
        "scf_iterations": {name: item["scf_iterations"] for name, item in summaries.items()},
        "final_energies_ev": {name: item["final_energy"] for name, item in summaries.items()},
        "performance": performance,
    }
