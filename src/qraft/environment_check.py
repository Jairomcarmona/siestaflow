"""Read-only local runtime inspection for the researcher CLI."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .contracts import (
    ContractVersion,
    DecisionStatus,
    EvidenceClass,
    FindingScope,
    RuleDescriptor,
    ValidationFinding,
    ValidationReport,
    ValidationSubject,
    contract_sha256,
)


_RULES = (
    RuleDescriptor(
        "siestaflow.environment.python",
        ContractVersion(1, 0),
        "Check the Python runtime required by QRAFT.",
        EvidenceClass.RUNTIME_EVIDENCE,
        (FindingScope.EXECUTION,),
        ("local.environment",),
        False,
    ),
    RuleDescriptor(
        "siestaflow.environment.siesta",
        ContractVersion(1, 0),
        "Resolve and probe the requested SIESTA executable.",
        EvidenceClass.RUNTIME_EVIDENCE,
        (FindingScope.EXECUTION,),
        ("local.environment",),
        False,
    ),
    RuleDescriptor(
        "siestaflow.environment.launcher",
        ContractVersion(1, 0),
        "Resolve the requested local or allocation launcher.",
        EvidenceClass.RUNTIME_EVIDENCE,
        (FindingScope.EXECUTION,),
        ("local.environment",),
        False,
    ),
    RuleDescriptor(
        "siestaflow.environment.slurm",
        ContractVersion(1, 0),
        "Inspect Slurm client availability without submitting a job.",
        EvidenceClass.RUNTIME_EVIDENCE,
        (FindingScope.EXECUTION,),
        ("local.environment",),
        False,
    ),
    RuleDescriptor(
        "siestaflow.environment.workspace",
        ContractVersion(1, 0),
        "Check read/write accessibility of the selected workspace.",
        EvidenceClass.RUNTIME_EVIDENCE,
        (FindingScope.EXECUTION,),
        ("local.environment",),
        False,
    ),
)
_RULESET_SHA256 = contract_sha256(_RULES)
_SLURM_COMMANDS = ("sbatch", "srun", "squeue", "scontrol", "sinfo")
_LAUNCHERS = {"auto", "direct", "srun", "mpiexec", "mpirun"}


@dataclass(frozen=True)
class EnvironmentCheckRequest:
    siesta_executable: str = "siesta"
    launcher: str = "auto"
    require_slurm: bool = False
    working_directory: Path = Path(".")

    def __post_init__(self) -> None:
        if not self.siesta_executable.strip():
            raise ValueError("siesta executable must be non-empty")
        if self.launcher not in _LAUNCHERS:
            raise ValueError(f"unsupported launcher: {self.launcher}")


Runner = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]


class EnvironmentChecker:
    """Inspect local capabilities and return a Core Contracts report."""

    def __init__(
        self,
        *,
        which: Which = shutil.which,
        runner: Runner = subprocess.run,
        environ: Mapping[str, str] | None = None,
        python_version: tuple[int, int, int] | None = None,
    ) -> None:
        self._which = which
        self._runner = runner
        self._environ = dict(os.environ if environ is None else environ)
        self._python_version = python_version or (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )

    def check(self, request: EnvironmentCheckRequest) -> ValidationReport:
        working_directory = request.working_directory.resolve()
        findings: list[ValidationFinding] = []

        findings.append(self._check_python())
        siesta_path, siesta_output, siesta_mpi = self._check_siesta(
            request.siesta_executable,
            findings,
        )
        launcher = self._select_launcher(request.launcher, siesta_mpi)
        launcher_path = self._check_launcher(launcher, siesta_mpi, findings)
        slurm_paths = self._check_slurm(request.require_slurm, findings)
        findings.append(self._check_workspace(working_directory))

        subject = ValidationSubject(
            subject_id="local-environment",
            subject_type="local.environment",
            source=str(working_directory),
            attributes={
                "host": platform.node() or "local",
                "platform": platform.system(),
                "platform_release": platform.release(),
                "python_version": ".".join(map(str, self._python_version)),
                "siesta_requested": request.siesta_executable,
                "siesta_resolved": siesta_path,
                "siesta_version": _siesta_version(siesta_output),
                "siesta_mpi": siesta_mpi,
                "launcher_requested": request.launcher,
                "launcher_selected": launcher,
                "launcher_resolved": launcher_path,
                "require_slurm": request.require_slurm,
                "inside_slurm_allocation": bool(
                    self._environ.get("SLURM_JOB_ID")
                ),
                "slurm_commands": slurm_paths,
            },
        )
        return ValidationReport.build(
            report_id="local-environment:check",
            subject=subject,
            findings=tuple(findings),
            ruleset_sha256=_RULESET_SHA256,
            produced_by="siestaflow.environment-check",
            metadata={
                "read_only": True,
                "job_submitted": False,
                "scientific_validation": False,
            },
        )

    def _check_python(self) -> ValidationFinding:
        supported = self._python_version >= (3, 11, 0)
        return _finding(
            rule_id="siestaflow.environment.python",
            code=(
                "PYTHON_VERSION_SUPPORTED"
                if supported
                else "PYTHON_VERSION_UNSUPPORTED"
            ),
            status=DecisionStatus.PASS if supported else DecisionStatus.FAIL,
            message=(
                f"Python {'.'.join(map(str, self._python_version))} "
                + ("satisfies >=3.11." if supported else "does not satisfy >=3.11.")
            ),
            hint=(
                None
                if supported
                else "Activate Python 3.11 or newer before running QRAFT."
            ),
        )

    def _check_siesta(
        self,
        requested: str,
        findings: list[ValidationFinding],
    ) -> tuple[str | None, str, bool | None]:
        resolved = _resolve_executable(requested, self._which)
        if resolved is None:
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.siesta",
                    code="SIESTA_EXECUTABLE_MISSING",
                    status=DecisionStatus.BLOCKED,
                    message=f"SIESTA executable could not be resolved: {requested}",
                    hint=(
                        "Load the SIESTA module, add it to PATH, or pass "
                        "--siesta /absolute/path/to/siesta."
                    ),
                )
            )
            return None, "", None
        try:
            result = self._run((resolved, "--version"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.siesta",
                    code="SIESTA_VERSION_PROBE_FAILED",
                    status=DecisionStatus.FAIL,
                    message=f"SIESTA version probe failed: {exc}",
                    hint="Run the same executable with --version and inspect its runtime dependencies.",
                    evidence=(resolved,),
                )
            )
            return resolved, "", None
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.siesta",
                    code="SIESTA_VERSION_PROBE_NONZERO",
                    status=DecisionStatus.FAIL,
                    message=f"SIESTA --version exited with code {result.returncode}.",
                    hint="Resolve missing shared libraries or MPI runtime conflicts.",
                    evidence=(resolved,),
                )
            )
            return resolved, output, None
        version = _siesta_version(output)
        identity_confirmed = bool(
            version
            and re.search(r"^\s*Parallelisations\s*:", output, re.I | re.M)
        )
        if not identity_confirmed:
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.siesta",
                    code="SIESTA_IDENTITY_UNCONFIRMED",
                    status=DecisionStatus.FAIL,
                    message=(
                        "The requested executable returned success but did not "
                        "emit the expected SIESTA version/capability fields."
                    ),
                    hint="Pass the actual SIESTA executable, not a wrapper or another program.",
                    evidence=(resolved,),
                )
            )
            return resolved, output, None
        mpi = bool(re.search(r"Parallelisations\s*:\s*.*\bMPI\b", output, re.I))
        findings.append(
            _finding(
                rule_id="siestaflow.environment.siesta",
                code="SIESTA_EXECUTABLE_READY",
                status=DecisionStatus.PASS,
                message=(
                    f"SIESTA {version} "
                    f"responded normally; MPI support={'yes' if mpi else 'no'}."
                ),
                evidence=(resolved,),
                data={"mpi": mpi, "version": version},
            )
        )
        return resolved, output, mpi

    def _select_launcher(self, requested: str, siesta_mpi: bool | None) -> str:
        if requested != "auto":
            return requested
        if self._environ.get("SLURM_JOB_ID") and self._which("srun"):
            return "srun"
        if siesta_mpi and self._which("mpiexec"):
            return "mpiexec"
        if siesta_mpi and self._which("mpirun"):
            return "mpirun"
        return "direct"

    def _check_launcher(
        self,
        launcher: str,
        siesta_mpi: bool | None,
        findings: list[ValidationFinding],
    ) -> str | None:
        if launcher == "direct":
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.launcher",
                    code="DIRECT_LAUNCHER_SELECTED",
                    status=DecisionStatus.PASS,
                    message="Direct single-process execution is available.",
                )
            )
            return None
        resolved = self._which(launcher)
        if resolved is None:
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.launcher",
                    code="LAUNCHER_MISSING",
                    status=DecisionStatus.BLOCKED,
                    message=f"Requested launcher is unavailable: {launcher}",
                    hint=f"Load or install {launcher}, or select --launcher direct.",
                )
            )
            return None
        if siesta_mpi is False:
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.launcher",
                    code="SIESTA_MPI_REQUIRED",
                    status=DecisionStatus.FAIL,
                    message=(
                        f"Launcher {launcher} requires an MPI-enabled SIESTA, "
                        "but the probed executable reports no MPI support."
                    ),
                    hint="Select an MPI-enabled SIESTA build or use --launcher direct.",
                    evidence=(resolved,),
                )
            )
            return resolved
        findings.append(
            _finding(
                rule_id="siestaflow.environment.launcher",
                code="LAUNCHER_READY",
                status=DecisionStatus.PASS,
                message=f"Launcher {launcher} is available.",
                evidence=(resolved,),
            )
        )
        return resolved

    def _check_slurm(
        self,
        required: bool,
        findings: list[ValidationFinding],
    ) -> dict[str, str | None]:
        paths = {name: self._which(name) for name in _SLURM_COMMANDS}
        missing = [name for name, path in paths.items() if path is None]
        if missing:
            status = DecisionStatus.BLOCKED if required else DecisionStatus.PASS
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.slurm",
                    code=(
                        "SLURM_CLIENT_INCOMPLETE"
                        if required
                        else "SLURM_NOT_REQUIRED"
                    ),
                    status=status,
                    message=(
                        f"Slurm client commands missing: {', '.join(missing)}."
                        if required
                        else "Slurm was not required for this local preparation check."
                    ),
                    hint=(
                        "Install/load Slurm client commands or remove --require-slurm."
                        if required
                        else None
                    ),
                    data={"missing": missing},
                )
            )
            return paths
        try:
            result = self._run((paths["sinfo"] or "sinfo", "--version"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            findings.append(
                _finding(
                    rule_id="siestaflow.environment.slurm",
                    code="SLURM_VERSION_PROBE_FAILED",
                    status=(
                        DecisionStatus.BLOCKED
                        if required
                        else DecisionStatus.REVIEW
                    ),
                    message=f"Slurm commands exist but sinfo could not be probed: {exc}",
                    hint="Check the loaded Slurm client and cluster configuration.",
                )
            )
            return paths
        ready = result.returncode == 0
        findings.append(
            _finding(
                rule_id="siestaflow.environment.slurm",
                code=(
                    "SLURM_CLIENT_READY"
                    if ready
                    else "SLURM_VERSION_PROBE_NONZERO"
                ),
                status=(
                    DecisionStatus.PASS
                    if ready
                    else (
                        DecisionStatus.BLOCKED
                        if required
                        else DecisionStatus.REVIEW
                    )
                ),
                message=(
                    (result.stdout or result.stderr or "Slurm client ready").strip()
                    if ready
                    else f"sinfo --version exited with code {result.returncode}."
                ),
                hint=None if ready else "Inspect the active Slurm installation.",
            )
        )
        return paths

    @staticmethod
    def _check_workspace(path: Path) -> ValidationFinding:
        ready = (
            path.is_dir()
            and os.access(path, os.R_OK)
            and os.access(path, os.W_OK)
            and os.access(path, os.X_OK)
        )
        return _finding(
            rule_id="siestaflow.environment.workspace",
            code="WORKSPACE_ACCESSIBLE" if ready else "WORKSPACE_INACCESSIBLE",
            status=DecisionStatus.PASS if ready else DecisionStatus.FAIL,
            message=(
                f"Workspace is readable and writable: {path}"
                if ready
                else f"Workspace is missing or not writable: {path}"
            ),
            hint=(
                None
                if ready
                else "Create the directory or correct its ownership and permissions."
            ),
            evidence=(str(path),),
        )

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self._runner(
            list(command),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )


def _resolve_executable(requested: str, which: Which) -> str | None:
    if any(separator in requested for separator in ("/", "\\")):
        path = Path(requested).expanduser()
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    return which(requested)


def _siesta_version(output: str) -> str | None:
    match = re.search(r"^\s*Version\s*:?\s*(\S+)", output, re.I | re.M)
    return match.group(1) if match else None


def _finding(
    *,
    rule_id: str,
    code: str,
    status: DecisionStatus,
    message: str,
    hint: str | None = None,
    evidence: tuple[str, ...] = (),
    data: Mapping[str, object] | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        rule_id=rule_id,
        code=code,
        status=status,
        message=message,
        evidence_class=EvidenceClass.RUNTIME_EVIDENCE,
        scope=FindingScope.EXECUTION,
        subject_id="local-environment",
        hint=hint,
        evidence=evidence,
        data=dict(data or {}),
    )
