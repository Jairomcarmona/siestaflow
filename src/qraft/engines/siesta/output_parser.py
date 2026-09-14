"""Streaming, provisional parser for real or partial SIESTA-like output."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ...contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from ...models import DecisionStatus, GateDecision
from .models import OutputClassification, SiestaOutputRecord


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"


@dataclass(frozen=True)
class FinalScfEnergyEvidence:
    """Verified final total energy from a completed native SIESTA SCF output.

    This deliberately does not reuse the provisional ``energies`` list: that
    list contains iterative E_KS/Etot values and is not selection evidence.
    """

    value_ev: float
    stdout_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "quantity": "siesta.final_total_energy",
            "value_ev": self.value_ev,
            "unit": "eV",
            "parser": "qraft.siesta.final-total-energy.v1",
            "source_stdout_sha256": self.stdout_sha256,
            "scf_converged": True,
        }


def final_scf_energy_artifact_envelope(
    *,
    evidence: FinalScfEnergyEvidence,
    final_fdf_sha256: str,
    electronic_state_file_sha256: str,
    electronic_state_content_sha256: str,
    magnetic_state_file_sha256: str,
    magnetic_state_content_sha256: str,
    scientific_identity_sha256: str,
) -> dict[str, object]:
    """Wrap re-parsed historic energy evidence in the existing artifact contract.

    M8-D can therefore consume old M6 states without treating a caller-supplied
    numeric value as evidence.  The selector verifies this envelope and every
    parent hash, but never reads or parses SIESTA stdout itself.
    """

    energy = evidence.to_dict()
    energy["source_final_fdf_sha256"] = final_fdf_sha256
    payload = {
        "schema_version": "1.0",
        "artifact_id": "final-scf-energy",
        "artifact_type": "qraft.final-scf-energy",
        "authority": "PROVISIONAL",
        "energy": energy,
        "parent_electronic_state": {
            "file_sha256": electronic_state_file_sha256,
            "content_sha256": electronic_state_content_sha256,
            "scientific_identity_sha256": scientific_identity_sha256,
            "magnetic_state_file_sha256": magnetic_state_file_sha256,
            "magnetic_state_content_sha256": magnetic_state_content_sha256,
        },
    }
    return ContractEnvelope.create(
        SCIENTIFIC_ARTIFACT,
        producer="qraft.siesta-final-scf-energy",
        payload=payload,
    ).to_dict()


def parse_final_scf_energy_evidence(stdout: Path) -> FinalScfEnergyEvidence:
    """Return only the post-convergence ``Final energy`` total from SIESTA.

    The native 5.4 output contains many intermediate energies.  A result is
    accepted only when normal termination and SCF convergence are independently
    visible and exactly one final-energy section follows the DM_out final pass.
    """

    data = stdout.read_bytes()
    lines = data.decode("utf-8", errors="replace").splitlines()
    record = SiestaOutputParser().parse((line + "\n" for line in lines))
    if not record.normal_termination or not record.scf_converged:
        raise ValueError("final SIESTA energy requires normal converged SCF output")
    dm_markers = [index for index, line in enumerate(lines) if "using dm_out to compute the final energy" in line.casefold()]
    if len(dm_markers) != 1:
        raise ValueError("final SIESTA energy requires one DM_out final-energy pass")
    final_headers = [
        index for index, line in enumerate(lines)
        if index > dm_markers[0] and re.search(r"^\s*siesta:\s*final\s+energy\s*\(\s*ev\s*\)\s*:\s*$", line, re.I)
    ]
    if len(final_headers) != 1:
        raise ValueError("final SIESTA energy section is missing or ambiguous")
    totals: list[float] = []
    for line in lines[final_headers[0] + 1:]:
        if re.search(r"^\s*siesta:\s*final\s+energy\s*\(", line, re.I):
            break
        match = re.search(r"^\s*siesta:\s*total\s*=\s*(" + _FLOAT + r")\s*$", line, re.I)
        if match:
            totals.append(float(match.group(1)))
    if len(totals) != 1 or not math.isfinite(totals[0]):
        raise ValueError("final SIESTA total energy is missing, ambiguous, or non-finite")
    return FinalScfEnergyEvidence(totals[0], hashlib.sha256(data).hexdigest())


class SiestaOutputParser:
    PROVISIONAL = "PROVISIONAL_UNTIL_REAL_OUTPUT_IMPORTED"
    _BENIGN_WARNING_MARKERS = (
        "basis_enthalpy and basis_harris_enthalpy files are deprecated",
        "warning: this information might be incomplete",
        "begin: ts checks and warnings",
        "end: ts checks and warnings",
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
            for suffix in (".DM", ".XV", ".CG", ".HSX", ".WFSX", ".RHO", ".DRHO", ".STRUCT_OUT", ".bands", ".DOS", ".PDOS", ".EPSIMG"):
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
