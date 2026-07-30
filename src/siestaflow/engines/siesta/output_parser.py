"""Streaming, provisional parser for real or partial SIESTA-like output."""

from __future__ import annotations

import re
from typing import Iterable

from ...models import DecisionStatus, GateDecision
from .models import OutputClassification, SiestaOutputRecord


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"


class SiestaOutputParser:
    PROVISIONAL = "PROVISIONAL_UNTIL_REAL_OUTPUT_IMPORTED"
    _BENIGN_WARNING_MARKERS = (
        "basis_enthalpy and basis_harris_enthalpy files are deprecated",
    )

    @classmethod
    def _is_benign_warning(cls, line: str) -> bool:
        lowered = line.casefold()
        return any(marker in lowered for marker in cls._BENIGN_WARNING_MARKERS)

    def parse(self, lines: Iterable[str], *, synthetic: bool = False) -> SiestaOutputRecord:
        version = None
        started = normal = scf_started = scf_converged = False
        dm_restart_attempted = dm_restart_succeeded = False
        iterations = atoms = species = None
        energies: list[float] = []
        max_force = elapsed = None
        warnings: list[str] = []
        benign_warnings: list[str] = []
        actionable_warnings: list[str] = []
        errors: list[str] = []
        artifacts: set[str] = set()
        spin = None
        classification_hint: OutputClassification | None = None
        line_count = 0
        for raw in lines:
            line_count += 1
            line = raw.rstrip("\r\n")
            lowered = line.casefold()
            match = re.search(r"^\s*(?:siesta\s+)?version\s*[:=]\s*([\w.+-]+)\s*$", line, re.I)
            if match and version is None:
                version = match.group(1)
                started = True
            if any(marker in lowered for marker in ("siesta started", "initatom:", "reading input fdf")):
                started = True
            if "scf cycle" in lowered or re.search(r"\bscf\s+iteration\b", lowered) or re.match(r"^\s*scf:\s*\d+", line, re.I):
                scf_started = True
            match = re.search(r"(?:scf\s+(?:cycle|iteration)\s*[:#]?\s*|^\s*scf:\s*)(\d+)", line, re.I)
            if match:
                iterations = max(iterations or 0, int(match.group(1)))
            if "scf converged" in lowered or "scf convergence achieved" in lowered or "scf cycle converged" in lowered:
                scf_converged = True
            if "scf not converged" in lowered or "maximum number of scf" in lowered:
                classification_hint = OutputClassification.SCF_NOT_CONVERGED
            match = re.search(r"(?:final\s+energy|total\s*=|etot\s*=)\s*(" + _FLOAT + r")", line, re.I)
            if match:
                energies.append(float(match.group(1)))
            match = re.search(r"(?:max(?:imum)?\s+force)\s*[:=]\s*(" + _FLOAT + r")", line, re.I)
            if match:
                max_force = float(match.group(1))
            match = re.search(r"number\s*of\s*atoms\s*(?::|=)?\s*(\d+)", line, re.I)
            if match:
                atoms = int(match.group(1))
            match = re.search(r"number\s*of\s*species\s*(?::|=)?\s*(\d+)", line, re.I)
            if match:
                species = int(match.group(1))
            match = re.search(r"(?:elapsed|wall)\s+(?:time)?\s*[:=]\s*(" + _FLOAT + r")\s*s", line, re.I)
            if match:
                elapsed = float(match.group(1))
            if "spin polarized" in lowered or "magnetization" in lowered:
                spin = line.strip()
            for suffix in (".DM", ".XV", ".CG", ".HSX", ".WFSX", ".RHO", ".DRHO", ".STRUCT_OUT", ".bands", ".DOS", ".PDOS"):
                if suffix.casefold() in lowered:
                    artifacts.add(suffix)
            if "warning" in lowered:
                warning = line.strip()
                warnings.append(warning)
                if self._is_benign_warning(warning):
                    benign_warnings.append(warning)
                else:
                    actionable_warnings.append(warning)
            if "attempting to read dm from file" in lowered:
                dm_restart_attempted = True
                if "succeeded" in lowered:
                    dm_restart_succeeded = True
            if any(marker in lowered for marker in ("job completed", "normal termination", "end of run")):
                normal = True
            if "pseudopotential" in lowered and any(marker in lowered for marker in ("missing", "not found", "cannot open", "error")):
                classification_hint = OutputClassification.PSEUDOPOTENTIAL_ERROR
                errors.append(line.strip())
            elif any(marker in lowered for marker in ("input error", "fdf error", "bad input")):
                classification_hint = OutputClassification.INPUT_ERROR
                errors.append(line.strip())
            elif any(marker in lowered for marker in ("command not found", "shared library", "mpi_abort", "environment error")):
                classification_hint = OutputClassification.ENVIRONMENT_ERROR
                errors.append(line.strip())
            elif any(marker in lowered for marker in ("out of memory", "oom-kill", "oom killed")):
                classification_hint = OutputClassification.OUT_OF_MEMORY
                errors.append(line.strip())
            elif any(marker in lowered for marker in ("due to time limit", "timeout", "time limit")):
                classification_hint = OutputClassification.TIMEOUT
                errors.append(line.strip())
            elif "node_fail" in lowered or "node failure" in lowered:
                classification_hint = OutputClassification.NODE_FAILURE
                errors.append(line.strip())
            elif "cancelled" in lowered or "canceled" in lowered:
                classification_hint = OutputClassification.CANCELLED
                errors.append(line.strip())
            elif any(marker in lowered for marker in ("floating point exception", "nan detected", "numerical failure")):
                classification_hint = OutputClassification.NUMERICAL_FAILURE
                errors.append(line.strip())
            elif "error" in lowered:
                errors.append(line.strip())

        if classification_hint is not None:
            classification = classification_hint
        elif normal and started and (scf_converged or not scf_started):
            classification = (
                OutputClassification.UNKNOWN_WARNING
                if actionable_warnings
                else OutputClassification.COMPLETED
            )
        elif started or scf_started or energies:
            classification = OutputClassification.TRUNCATED_OUTPUT
        else:
            classification = OutputClassification.UNKNOWN_FAILURE
        return SiestaOutputRecord(
            classification=classification,
            provisional_status=self.PROVISIONAL,
            version=version,
            started=started,
            normal_termination=normal,
            scf_started=scf_started,
            scf_converged=scf_converged,
            scf_iterations=iterations,
            energies=tuple(energies),
            max_force=max_force,
            warnings=tuple(warnings),
            errors=tuple(errors),
            atoms=atoms,
            species=species,
            spin_evidence=spin,
            elapsed_seconds=elapsed,
            mentioned_artifacts=tuple(sorted(artifacts)),
            line_count=line_count,
            synthetic=synthetic,
            benign_warnings=tuple(benign_warnings),
            dm_restart_attempted=dm_restart_attempted,
            dm_restart_succeeded=dm_restart_succeeded,
        )

    def gate(self, record: SiestaOutputRecord) -> GateDecision:
        if record.classification is OutputClassification.COMPLETED:
            return GateDecision(DecisionStatus.PASS, "normal technical completion evidence", (record.provisional_status,))
        if record.classification in {OutputClassification.UNKNOWN_WARNING, OutputClassification.TRUNCATED_OUTPUT, OutputClassification.UNKNOWN_FAILURE}:
            return GateDecision(DecisionStatus.REVIEW, record.classification.value, (record.provisional_status,))
        if record.classification in {OutputClassification.PSEUDOPOTENTIAL_ERROR, OutputClassification.ENVIRONMENT_ERROR}:
            return GateDecision(DecisionStatus.BLOCKED, record.classification.value, (record.provisional_status,))
        return GateDecision(DecisionStatus.FAIL, record.classification.value, (record.provisional_status,))
