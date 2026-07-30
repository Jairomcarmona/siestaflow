#!/usr/bin/env python3
"""Run the complete M1 numerical/basis/U-spin test chain in one SLURM allocation."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PACKAGE_ROOT / "campaign.json"
FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
STOP_REQUESTED = False
ACTIVE_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}
PROCESS_LOCK = threading.Lock()
EVENT_LOCK = threading.Lock()


class CampaignError(RuntimeError):
    pass


class InterruptedCampaign(CampaignError):
    pass


@dataclass(frozen=True)
class Variant:
    task_id: str
    stage: str
    mesh_ry: int
    kgrid: tuple[int, int, int]
    basis: str = "DZP"
    ueff_ev: float = 0.0
    magnetic_state: str = "FM"
    parent_task_id: str | None = None
    parent_decision: str | None = None
    step_ntasks: int | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_text(path, json_text(value))


def append_event(path: Path, event: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at_epoch": time.time(),
        "event": event,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        **fields,
    }
    with EVENT_LOCK:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"INVALID_CAMPAIGN_JSON:{exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != "3.0":
        raise CampaignError("UNSUPPORTED_CAMPAIGN_SCHEMA")
    validate_config(data)
    return data


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("package_id") != "YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3_2":
        raise CampaignError("PACKAGE_ID_MISMATCH")
    if sys.version_info < (3, 10):
        raise CampaignError("PYTHON_3_10_OR_NEWER_REQUIRED")
    slurm = config.get("slurm")
    if not isinstance(slurm, Mapping):
        raise CampaignError("SLURM_CONFIGURATION_REQUIRED")
    exact = {
        "partition": "qz2d-128p",
        "nodes": 2,
        "ntasks": 128,
        "ntasks_per_node": 64,
        "cpus_per_task": 1,
    }
    for key, expected in exact.items():
        if slurm.get(key) != expected:
            raise CampaignError(f"INVALID_FULL_ALLOCATION_POLICY:{key}")
    execution = config.get("execution")
    if not isinstance(execution, Mapping):
        raise CampaignError("EXECUTION_POLICY_REQUIRED")
    if execution.get("candidate_step_ntasks") != [64, 128]:
        raise CampaignError("EXECUTION_CANDIDATES_MUST_BE_64_128")
    if int(execution.get("parallel_steps_when_64", 0)) != 2:
        raise CampaignError("TWO_WAY_64_MPI_POLICY_REQUIRED")
    if float(execution.get("minimum_speedup_128_vs_64", 0.0)) <= 1.0:
        raise CampaignError("INVALID_128_MPI_SPEEDUP_THRESHOLD")
    numerical = config.get("numerical_policy")
    if not isinstance(numerical, Mapping):
        raise CampaignError("NUMERICAL_POLICY_REQUIRED")
    if numerical.get("mesh_ry") != [200, 250, 300, 350]:
        raise CampaignError("MESH_SERIES_MISMATCH")
    if numerical.get("kgrids") != [[2, 2, 1], [3, 3, 1], [4, 4, 1]]:
        raise CampaignError("KGRID_SERIES_MISMATCH")
    if numerical.get("optional_kgrid") != [5, 5, 1]:
        raise CampaignError("OPTIONAL_KGRID_MISMATCH")
    if float(numerical.get("energy_tolerance_mev_per_atom", 0)) <= 0:
        raise CampaignError("ENERGY_TOLERANCE_MUST_BE_POSITIVE")
    for key in (
        "max_force_delta_tolerance_ev_ang",
        "rms_force_delta_tolerance_ev_ang",
    ):
        if float(numerical.get(key, 0)) <= 0:
            raise CampaignError(f"FORCE_TOLERANCE_MUST_BE_POSITIVE:{key}")
    dftu = config.get("dftu")
    if not isinstance(dftu, Mapping):
        raise CampaignError("DFTU_POLICY_REQUIRED")
    if (
        dftu.get("formalism") != "Dudarev"
        or dftu.get("projector_generation_method") != 2
        or float(dftu.get("j_ev", -1)) != 0.0
        or dftu.get("ueff_ev") != [3.8, 4.0]
    ):
        raise CampaignError("DFTU_POLICY_MISMATCH")
    magnetism = config.get("magnetism")
    if not isinstance(magnetism, Mapping):
        raise CampaignError("MAGNETIC_POLICY_REQUIRED")
    plus = set(map(int, magnetism.get("stripe_plus_indices", [])))
    minus = set(map(int, magnetism.get("stripe_minus_indices", [])))
    fm = set(map(int, magnetism.get("fm_plus_indices", [])))
    if plus & minus or plus | minus != fm or len(fm) != 18:
        raise CampaignError("INVALID_STRIPE_AFM_PARTITION")
    if float(magnetism.get("minimum_abs_mn_moment_muB", 0.0)) <= 0:
        raise CampaignError("INVALID_MINIMUM_MN_MOMENT")
    basis = config.get("basis")
    if not isinstance(basis, Mapping):
        raise CampaignError("BASIS_POLICY_REQUIRED")
    lines = basis.get("stricter_definition", {}).get("pao_basis_lines")
    if not isinstance(lines, list) or not lines:
        raise CampaignError("EXPLICIT_STRICTER_BASIS_REQUIRED")
    joined = "\n".join(map(str, lines))
    for required in ("%block PAO.Basis", "Mn 4", "n=3 2 3 P 1", "O 2"):
        if required not in joined:
            raise CampaignError(f"STRICTER_BASIS_INCOMPLETE:{required}")
    if re.search(r"(?im)^\s*PAO\.BasisSize\s+TZP\b", joined):
        raise CampaignError("PAO_BASISSIZE_TZP_FORBIDDEN_BY_EXPLICIT_BASIS_POLICY")


def validate_static_files(config: Mapping[str, Any]) -> dict[str, str]:
    base = PACKAGE_ROOT / str(config["system"]["base_fdf"])
    pseudos = PACKAGE_ROOT / "external/pseudopotentials"
    required = [base, pseudos / "Mn.psml", pseudos / "O.psml"]
    for path in required:
        if not path.is_file() or path.is_symlink():
            raise CampaignError(f"REQUIRED_FILE_MISSING:{path.relative_to(PACKAGE_ROOT)}")
    text = base.read_text(encoding="utf-8")
    requirements = (
        r"(?im)^\s*NumberOfAtoms\s+54\s*$",
        r"(?im)^\s*NumberOfSpecies\s+2\s*$",
        r"(?im)^\s*NetCharge\s+0\s*$",
        r"(?im)^\s*MD\.Steps\s+0\s*$",
        r"(?im)^\s*PAO\.BasisSize\s+DZP\s*$",
        r"(?im)^\s*Spin\s+polarized\s*$",
    )
    for pattern in requirements:
        if not re.search(pattern, text):
            raise CampaignError(f"BASE_FDF_CONTRACT_FAILED:{pattern}")
    coordinate = re.search(
        r"(?is)%block\s+AtomicCoordinatesAndAtomicSpecies\s*(.*?)"
        r"%endblock\s+AtomicCoordinatesAndAtomicSpecies",
        text,
    )
    if not coordinate:
        raise CampaignError("BASE_COORDINATE_BLOCK_MISSING")
    rows = [
        line
        for line in coordinate.group(1).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(rows) != int(config["system"]["atoms"]):
        raise CampaignError("BASE_ATOM_COUNT_MISMATCH")
    mn_indices = {
        index
        for index, line in enumerate(rows, start=1)
        if line.split()[-1] == "1"
    }
    expected = set(map(int, config["magnetism"]["fm_plus_indices"]))
    if mn_indices != expected:
        raise CampaignError("MN_INDEX_MAP_MISMATCH")
    return {path.relative_to(PACKAGE_ROOT).as_posix(): sha256(path) for path in required}


def replace_unique(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise CampaignError(f"FDF_REPLACEMENT_FAILED:{label}:{count}")
    return updated


def spin_block(config: Mapping[str, Any], state: str) -> str:
    magnetic = config["magnetism"]
    if state == "FM":
        signed = [(int(index), "+") for index in magnetic["fm_plus_indices"]]
    elif state == "STRIPE_AFM":
        signed = [
            *((int(index), "+") for index in magnetic["stripe_plus_indices"]),
            *((int(index), "-") for index in magnetic["stripe_minus_indices"]),
        ]
        signed.sort()
    else:
        raise CampaignError(f"UNSUPPORTED_MAGNETIC_STATE:{state}")
    body = "\n".join(f"  {index:3d} {token}" for index, token in signed)
    return f"%block DM.InitSpin\n{body}\n%endblock DM.InitSpin"


def dftu_block(config: Mapping[str, Any], ueff_ev: float) -> str:
    if abs(ueff_ev) < 1.0e-12:
        return ""
    dftu = config["dftu"]
    if ueff_ev not in tuple(map(float, dftu["ueff_ev"])):
        raise CampaignError(f"UNAPPROVED_UEFF:{ueff_ev}")
    return (
        "DFTU.ProjectorGenerationMethod 2\n"
        f"DFTU.CutoffNorm {float(dftu['cutoff_norm']):.6f}\n"
        f"DFTU.ThresholdTol {float(dftu['threshold_tol']):.6f}\n"
        f"DFTU.PopTol {float(dftu['population_tol']):.6f}\n"
        "%block DFTU.Proj\n"
        "Mn 1\n"
        f"  n={int(dftu['principal_quantum_number'])} "
        f"{int(dftu['angular_momentum'])}\n"
        f"  {ueff_ev:.6f} {float(dftu['j_ev']):.6f}\n"
        f"  {float(dftu['projector_radius_bohr']):.6f} "
        f"{float(dftu['fermi_width_bohr']):.6f}\n"
        "%endblock DFTU.Proj\n"
    )


def render_fdf(base: str, config: Mapping[str, Any], variant: Variant) -> str:
    if variant.mesh_ry not in {200, 250, 300, 350}:
        raise CampaignError(f"UNAPPROVED_MESH:{variant.mesh_ry}")
    if variant.kgrid not in {
        (2, 2, 1),
        (3, 3, 1),
        (4, 4, 1),
        (5, 5, 1),
    }:
        raise CampaignError(f"UNAPPROVED_KGRID:{variant.kgrid}")
    if variant.kgrid[2] != 1:
        raise CampaignError("KZ_MUST_EQUAL_ONE")
    text = replace_unique(
        base,
        r"(?im)^\s*SystemName\s+.*$",
        f"SystemName {variant.task_id}",
        "SystemName",
    )
    text = replace_unique(
        text,
        r"(?im)^\s*SystemLabel\s+\S+\s*$",
        f"SystemLabel {variant.task_id}",
        "SystemLabel",
    )
    text = replace_unique(
        text,
        r"(?im)^\s*Mesh\.Cutoff\s+" + FLOAT + r"\s+Ry\s*$",
        f"Mesh.Cutoff {variant.mesh_ry} Ry",
        "Mesh.Cutoff",
    )
    kblock = (
        "%block kgrid.MonkhorstPack\n"
        f"  {variant.kgrid[0]} 0 0 0.0\n"
        f"  0 {variant.kgrid[1]} 0 0.0\n"
        "  0 0 1 0.0\n"
        "%endblock kgrid.MonkhorstPack"
    )
    text = replace_unique(
        text,
        r"(?is)%block\s+kgrid\.MonkhorstPack.*?"
        r"%endblock\s+kgrid\.MonkhorstPack",
        kblock,
        "kgrid.MonkhorstPack",
    )
    text = replace_unique(
        text,
        r"(?is)%block\s+DM\.InitSpin.*?%endblock\s+DM\.InitSpin",
        spin_block(config, variant.magnetic_state),
        "DM.InitSpin",
    )
    if variant.basis == "DZP":
        pass
    elif variant.basis == "EXPLICIT_TZP":
        basis_lines = config["basis"]["stricter_definition"]["pao_basis_lines"]
        text = replace_unique(
            text,
            r"(?im)^\s*PAO\.BasisSize\s+DZP\s*$",
            "\n".join(map(str, basis_lines)),
            "PAO.BasisSize_to_explicit_PAO.Basis",
        )
    else:
        raise CampaignError(f"UNAPPROVED_BASIS:{variant.basis}")
    block = dftu_block(config, variant.ueff_ev)
    if block:
        text = replace_unique(
            text,
            r"(?im)^\s*NetCharge\s+0\s*$",
            block + "\nNetCharge 0",
            "DFTU_insertion",
        )
    forbidden = (
        "NO_AUTO_RUN",
        "DO_NOT_SUBMIT",
        "DO_NOT_EXECUTE_AUTOMATICALLY",
        "HUMAN_REVIEW_REQUIRED",
    )
    if any(token in text for token in forbidden):
        raise CampaignError("BLOCKING_MARKER_SURVIVED_MATERIALIZATION")
    provenance = {
        "task_id": variant.task_id,
        "stage": variant.stage,
        "mesh_ry": variant.mesh_ry,
        "kgrid": list(variant.kgrid),
        "basis": variant.basis,
        "ueff_ev": variant.ueff_ev,
        "j_ev": float(config["dftu"]["j_ev"]),
        "magnetic_state": variant.magnetic_state,
        "parent_task_id": variant.parent_task_id,
        "parent_decision": variant.parent_decision,
        "step_ntasks": variant.step_ntasks,
    }
    header = (
        "# generated_by=YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3_2\n"
        f"# variant_sha256={hashlib.sha256(canonical(provenance).encode()).hexdigest()}\n"
        f"# variant={canonical(provenance)}\n"
    )
    result = header + text
    for pattern, label in (
        (r"(?im)^\s*MD\.Steps\s+0\s*$", "MD.Steps=0"),
        (r"(?im)^\s*NetCharge\s+0\s*$", "NetCharge=0"),
        (r"(?im)^\s*NumberOfAtoms\s+54\s*$", "NumberOfAtoms=54"),
    ):
        if not re.search(pattern, result):
            raise CampaignError(f"MATERIALIZED_FDF_CONTRACT_FAILED:{label}")
    return result


def _number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def parse_final_forces(text: str) -> list[list[float]]:
    markers = list(
        re.finditer(r"(?im)^\s*siesta:\s+Atomic forces\s+\(eV/Ang\):\s*$", text)
    )
    if not markers:
        return []
    tail = text[markers[-1].end() :]
    forces: list[list[float]] = []
    row = re.compile(
        r"^\s*(\d+)\s+(" + FLOAT + r")\s+(" + FLOAT + r")\s+(" + FLOAT + r")\s*$"
    )
    for line in tail.splitlines():
        match = row.match(line)
        if match:
            expected = len(forces) + 1
            if int(match.group(1)) != expected:
                break
            forces.append([_number(match.group(i)) for i in (2, 3, 4)])
        elif forces:
            break
    return forces


def parse_final_mulliken(text: str) -> list[dict[str, Any]]:
    header = re.compile(
        r"(?im)^\s*Mulliken Atomic Populations:\s*$\s*"
        r"^\s*Atom #\s+charge \[q\]\s+valence \[e\]\s+Sz \[e\]\s+Species\s*$"
    )
    markers = list(header.finditer(text))
    if not markers:
        return []
    tail = text[markers[-1].end() :]
    row = re.compile(
        r"^\s*(\d+)\s+(" + FLOAT + r")\s+(" + FLOAT + r")\s+(" + FLOAT + r")\s+(\S+)\s*$"
    )
    populations: list[dict[str, Any]] = []
    for line in tail.splitlines():
        match = row.match(line)
        if match:
            populations.append(
                {
                    "atom_index": int(match.group(1)),
                    "charge_e": _number(match.group(2)),
                    "valence_e": _number(match.group(3)),
                    "sz_muB": _number(match.group(4)),
                    "species": match.group(5),
                }
            )
        elif populations and (line.lstrip().startswith("-") or "Total" in line):
            break
    return populations


def force_metrics(forces: list[list[float]]) -> tuple[float | None, float | None]:
    if not forces:
        return None, None
    magnitudes = [math.sqrt(sum(component * component for component in vector)) for vector in forces]
    return max(magnitudes), math.sqrt(sum(value * value for value in magnitudes) / len(magnitudes))


def classify_warnings(
    warning_lines: list[str], policy: Mapping[str, Any]
) -> dict[str, list[str]]:
    groups = {"allowed": [], "review": [], "terminal": []}
    allowed = tuple(str(item).casefold() for item in policy.get("allowed_markers", []))
    terminal = tuple(str(item).casefold() for item in policy.get("terminal_markers", []))
    for line in warning_lines:
        lowered = line.casefold()
        if any(marker in lowered for marker in terminal):
            groups["terminal"].append(line)
        elif any(marker in lowered for marker in allowed):
            groups["allowed"].append(line)
        else:
            groups["review"].append(line)
    return groups


def parse_siesta_output(
    stdout: Path,
    stderr: Path,
    exit_code: int,
    warning_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out = stdout.read_text(encoding="utf-8", errors="replace") if stdout.is_file() else ""
    err = stderr.read_text(encoding="utf-8", errors="replace") if stderr.is_file() else ""
    combined = out + "\n" + err
    lowered = combined.casefold()
    normal = any(
        marker in lowered
        for marker in (">> end of run:", "normal termination", "job completed")
    )
    scf = any(
        marker in lowered
        for marker in (
            "scf cycle converged",
            "scf convergence achieved",
            "scf convergence by dm+h criterion",
        )
    )
    energy_patterns = (
        r"(?im)^\s*siesta:\s+Total\s*=\s*(" + FLOAT + r")\s*$",
        r"(?im)^\s*siesta:\s+Etot\s*=\s*(" + FLOAT + r")\s*$",
        r"(?im)^\s*siesta:\s+E_KS\(eV\)\s*=\s*(" + FLOAT + r")\s*$",
        r"(?im)^\s*siesta:\s+Final energy\s+(" + FLOAT + r")\s*$",
    )
    energies: list[float] = []
    for pattern in energy_patterns:
        matches = re.findall(pattern, combined)
        if matches:
            energies = [_number(item) for item in matches]
            break
    iterations = [
        int(value)
        for value in re.findall(
            r"(?i)SCF cycle converged after\s+(\d+)\s+iterations", combined
        )
    ]
    edftu = [
        _number(item)
        for item in re.findall(
            r"(?im)^\s*siesta:\s+Edftu\s*=\s*(" + FLOAT + r")\s*$", combined
        )
    ]
    warning_lines = [
        line.strip()
        for line in combined.splitlines()
        if "warning" in line.casefold()
    ][:100]
    forces = parse_final_forces(out)
    max_force, rms_force = force_metrics(forces)
    mulliken = parse_final_mulliken(out)
    hard_error_markers = (
        "fdf error",
        "input error",
        "pseudopotential not found",
        "cannot open pseudopotential",
        "mpi_abort",
        "floating point exception",
        "out of memory",
        "oom-kill",
        "segmentation fault",
    )
    errors = [
        marker for marker in hard_error_markers if marker in lowered
    ]
    warning_classes = classify_warnings(warning_lines, warning_policy or {})
    success = bool(
        exit_code == 0
        and normal
        and scf
        and energies
        and not errors
        and not warning_classes["terminal"]
    )
    return {
        "status": "PASS" if success else "FAIL",
        "exit_code": exit_code,
        "normal_termination": normal,
        "scf_converged": scf,
        "scf_iterations": iterations[-1] if iterations else None,
        "energy_ev": energies[-1] if energies else None,
        "edftu_ev": edftu[-1] if edftu else None,
        "warnings": warning_lines,
        "warning_classification": warning_classes,
        "forces_ev_ang": forces,
        "force_atom_count": len(forces),
        "max_force_ev_ang": max_force,
        "rms_force_ev_ang": rms_force,
        "mulliken_atomic_populations": mulliken,
        "hard_errors": errors,
        "stdout_sha256": sha256(stdout) if stdout.is_file() else None,
        "stderr_sha256": sha256(stderr) if stderr.is_file() else None,
    }


def adjacent_deltas_mev_per_unit(
    values: Iterable[tuple[Any, float]], denominator: int
) -> list[dict[str, Any]]:
    ordered = list(values)
    result = []
    for previous, current in zip(ordered, ordered[1:]):
        result.append(
            {
                "from": previous[0],
                "to": current[0],
                "delta_mev_per_unit": abs(current[1] - previous[1])
                * 1000.0
                / denominator,
            }
        )
    return result


def compare_results(
    lower: Mapping[str, Any],
    stricter: Mapping[str, Any],
    denominator: int,
) -> dict[str, float]:
    lower_forces = lower.get("forces_ev_ang") or []
    stricter_forces = stricter.get("forces_ev_ang") or []
    if len(lower_forces) != denominator or len(stricter_forces) != denominator:
        raise CampaignError("FORCE_VECTOR_COUNT_MISMATCH")
    deltas = [
        math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))
        for left, right in zip(lower_forces, stricter_forces)
    ]
    return {
        "energy_delta_mev_per_atom": abs(
            float(lower["energy_ev"]) - float(stricter["energy_ev"])
        )
        * 1000.0
        / denominator,
        "max_force_delta_ev_ang": max(deltas),
        "rms_force_delta_ev_ang": math.sqrt(
            sum(value * value for value in deltas) / denominator
        ),
    }


def convergence_passes(
    comparison: Mapping[str, float],
    energy_tolerance: float,
    max_force_tolerance: float,
    rms_force_tolerance: float,
) -> bool:
    return bool(
        comparison["energy_delta_mev_per_atom"] <= energy_tolerance
        and comparison["max_force_delta_ev_ang"] <= max_force_tolerance
        and comparison["rms_force_delta_ev_ang"] <= rms_force_tolerance
    )


def select_plateau(
    values: Iterable[tuple[Any, Mapping[str, Any]]],
    tolerance_mev_per_unit: float,
    denominator: int,
    max_force_tolerance_ev_ang: float,
    rms_force_tolerance_ev_ang: float,
) -> tuple[Any | None, list[dict[str, Any]]]:
    ordered = list(values)
    if len(ordered) < 2:
        raise CampaignError("AT_LEAST_TWO_POINTS_REQUIRED")
    comparisons: list[dict[str, Any]] = []
    for candidate_index in range(len(ordered) - 1):
        candidate_key, candidate_result = ordered[candidate_index]
        candidate_passes = True
        for stricter_key, stricter_result in ordered[candidate_index + 1 :]:
            metrics = compare_results(candidate_result, stricter_result, denominator)
            passed = convergence_passes(
                metrics,
                tolerance_mev_per_unit,
                max_force_tolerance_ev_ang,
                rms_force_tolerance_ev_ang,
            )
            comparisons.append(
                {
                    "candidate": candidate_key,
                    "stricter": stricter_key,
                    **metrics,
                    "pass": passed,
                }
            )
            candidate_passes = candidate_passes and passed
        if candidate_passes:
            return candidate_key, comparisons
    return None, comparisons


def task_directory(run_root: Path, variant: Variant) -> Path:
    return run_root / "calculations" / variant.stage / variant.task_id


def next_attempt(directory: Path) -> tuple[str, Path]:
    attempts = directory / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    numbers = []
    for child in attempts.glob("attempt-*"):
        match = re.fullmatch(r"attempt-(\d{4})", child.name)
        if match:
            numbers.append(int(match.group(1)))
    number = max(numbers, default=0) + 1
    name = f"attempt-{number:04d}"
    target = attempts / name
    target.mkdir(parents=False, exist_ok=False)
    return name, target


def completed_result(directory: Path, input_hash: str) -> dict[str, Any] | None:
    status_path = directory / "status.json"
    if not status_path.is_file():
        return None
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("status") != "PASS" or status.get("input_sha256") != input_hash:
        return None
    selected = directory / str(status.get("selected_attempt", "")) / "result.json"
    if not selected.is_file():
        return None
    result = json.loads(selected.read_text(encoding="utf-8"))
    return result if result.get("status") == "PASS" else None


def signal_handler(number: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    with PROCESS_LOCK:
        processes = list(ACTIVE_PROCESSES.values())
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (AttributeError, OSError, ProcessLookupError):
            process.terminate()


def slurm_end_epoch() -> int | None:
    raw = os.environ.get("SLURM_JOB_END_TIME", "").strip()
    if raw.isdigit():
        return int(raw)
    job_id = os.environ.get("SLURM_JOB_ID")
    if not job_id or shutil.which("scontrol") is None:
        return None
    query = subprocess.run(
        ["scontrol", "show", "job", "-o", job_id],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    match = re.search(r"\bEndTime=(\S+)", query.stdout)
    if not match or match.group(1) in {"Unknown", "N/A"}:
        return None
    try:
        return int(
            time.mktime(time.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S"))
        )
    except ValueError:
        return None


def estimate_task_seconds(
    config: Mapping[str, Any], run_root: Path, variant: Variant
) -> float:
    samples: list[float] = []
    for result_path in run_root.glob(
        f"calculations/{variant.stage}/*/attempts/attempt-*/result.json"
    ):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        elapsed = result.get("elapsed_seconds")
        if result.get("status") == "PASS" and isinstance(elapsed, (int, float)):
            samples.append(float(elapsed))
    policy = config["walltime_policy"]
    estimate = (
        statistics.median(samples)
        if samples
        else float(policy["default_task_estimate_seconds"])
    )
    return max(float(policy["minimum_task_estimate_seconds"]), estimate)


def enforce_walltime_guard(
    config: Mapping[str, Any],
    run_root: Path,
    events: Path,
    variant: Variant,
) -> None:
    end_epoch = slurm_end_epoch()
    if end_epoch is None:
        raise CampaignError("SLURM_END_TIME_UNAVAILABLE")
    remaining = end_epoch - int(time.time())
    estimate = estimate_task_seconds(config, run_root, variant)
    policy = config["walltime_policy"]
    required = (
        estimate * float(policy["safety_factor"])
        + float(policy["shutdown_margin_seconds"])
    )
    append_event(
        events,
        "WALLTIME_GUARD",
        task_id=variant.task_id,
        remaining_seconds=remaining,
        estimated_seconds=estimate,
        required_seconds=required,
    )
    if remaining < required:
        raise InterruptedCampaign(
            f"INSUFFICIENT_WALLTIME:{variant.task_id}:{remaining}<{required:.0f}"
        )


def classify_failure(
    result: Mapping[str, Any], config: Mapping[str, Any]
) -> str:
    combined = "\n".join(
        [
            *map(str, result.get("hard_errors", [])),
            *map(str, result.get("warnings", [])),
        ]
    ).casefold()
    resilience = config["resilience"]
    if any(
        str(marker).casefold() in combined
        for marker in resilience.get("terminal_markers", [])
    ):
        return "TERMINAL"
    if any(
        str(marker).casefold() in combined
        for marker in resilience.get("retryable_markers", [])
    ):
        return "RETRYABLE"
    if int(result.get("exit_code", 0)) != 0 and not result.get("normal_termination"):
        return "RETRYABLE"
    return "TERMINAL"


def classify_magnetic_state(
    populations: list[dict[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    mn_indices = list(map(int, config["magnetism"]["fm_plus_indices"]))
    by_index = {int(row["atom_index"]): row for row in populations}
    if any(index not in by_index for index in mn_indices):
        return {
            "classification": "INCOMPLETE_MN_MULLIKEN_TABLE",
            "mn_moments_muB": {},
        }
    moments = {index: float(by_index[index]["sz_muB"]) for index in mn_indices}
    minimum = float(config["magnetism"]["minimum_abs_mn_moment_muB"])
    if any(abs(value) < minimum for value in moments.values()):
        classification = "MOMENT_COLLAPSE_OR_MIXED"
    else:
        signs = {index: 1 if value > 0 else -1 for index, value in moments.items()}
        if len(set(signs.values())) == 1:
            classification = "FM"
        else:
            plus = set(map(int, config["magnetism"]["stripe_plus_indices"]))
            expected = {index: (1 if index in plus else -1) for index in mn_indices}
            exact = all(signs[index] == expected[index] for index in mn_indices)
            inverted = all(signs[index] == -expected[index] for index in mn_indices)
            classification = "STRIPE_AFM" if exact or inverted else "OTHER_MAGNETIC_PATTERN"
    return {
        "classification": classification,
        "mn_moments_muB": {str(key): value for key, value in moments.items()},
        "minimum_abs_mn_moment_muB": min(abs(value) for value in moments.values()),
        "total_mn_moment_muB": sum(moments.values()),
    }


def run_variant_once(
    config: Mapping[str, Any],
    run_root: Path,
    events: Path,
    base_text: str,
    variant: Variant,
) -> dict[str, Any]:
    if STOP_REQUESTED:
        raise InterruptedCampaign("STOP_REQUESTED_BEFORE_TASK")
    enforce_walltime_guard(config, run_root, events, variant)
    directory = task_directory(run_root, variant)
    directory.mkdir(parents=True, exist_ok=True)
    fdf = render_fdf(base_text, config, variant)
    input_hash = hashlib.sha256(fdf.encode()).hexdigest()
    cached = completed_result(directory, input_hash)
    if cached is not None:
        append_event(events, "TASK_REUSED", task_id=variant.task_id, input_sha256=input_hash)
        return cached

    attempt_id, attempt = next_attempt(directory)
    input_path = attempt / "input.fdf"
    atomic_text(input_path, fdf)
    pseudo_hashes = {}
    for name in ("Mn.psml", "O.psml"):
        source = PACKAGE_ROOT / "external/pseudopotentials" / name
        target = attempt / name
        shutil.copy2(source, target)
        pseudo_hashes[name] = sha256(target)
    lineage = {
        "schema_version": "1.0",
        "task_id": variant.task_id,
        "stage": variant.stage,
        "attempt_id": attempt_id,
        "input_sha256": input_hash,
        "base_fdf_sha256": hashlib.sha256(base_text.encode()).hexdigest(),
        "pseudopotential_sha256": pseudo_hashes,
        "parent_task_id": variant.parent_task_id,
        "parent_decision": variant.parent_decision,
        "parameters": {
            "mesh_ry": variant.mesh_ry,
            "kgrid": list(variant.kgrid),
            "basis": variant.basis,
            "ueff_ev": variant.ueff_ev,
            "j_ev": float(config["dftu"]["j_ev"]),
            "magnetic_state": variant.magnetic_state,
            "step_ntasks": int(
                variant.step_ntasks or config["slurm"]["ntasks"]
            ),
        },
        "slurm": {
            "job_id": os.environ.get("SLURM_JOB_ID"),
            "nodes": int(config["slurm"]["nodes"]),
            "ntasks": int(config["slurm"]["ntasks"]),
            "ntasks_per_node": int(config["slurm"]["ntasks_per_node"]),
            "step_ntasks": int(
                variant.step_ntasks or config["slurm"]["ntasks"]
            ),
        },
    }
    atomic_json(attempt / "lineage.json", lineage)
    step_ntasks = int(variant.step_ntasks or config["slurm"]["ntasks"])
    if step_ntasks not in tuple(map(int, config["execution"]["candidate_step_ntasks"])):
        raise CampaignError(f"UNAPPROVED_STEP_NTASKS:{step_ntasks}")
    step_nodes = 1 if step_ntasks == 64 else 2
    command = [
        str(config["runtime"]["launcher"]),
        "--exclusive",
        "--kill-on-bad-exit=1",
        f"--nodes={step_nodes}",
        f"--ntasks={step_ntasks}",
        f"--ntasks-per-node={int(config['execution']['ntasks_per_node'])}",
        f"--cpus-per-task={int(config['slurm']['cpus_per_task'])}",
        "--distribution=block:block",
        f"--cpu-bind={config['execution']['cpu_bind']}",
        str(config["runtime"]["siesta_executable"]),
    ]
    atomic_json(
        attempt / "command.json",
        {
            "argv": command,
            "cwd": str(attempt),
            "stdin": "input.fdf",
            "stdout": "siesta.out",
            "stderr": "siesta.err",
        },
    )
    atomic_json(
        attempt / "environment.json",
        {
            key: os.environ.get(key)
            for key in (
                "SLURM_JOB_ID",
                "SLURM_JOB_NODELIST",
                "SLURM_NNODES",
                "SLURM_NTASKS",
                "SLURM_TASKS_PER_NODE",
                "SLURM_CPUS_PER_TASK",
                "LOADEDMODULES",
            )
        },
    )
    stdout = attempt / "siesta.out"
    stderr = attempt / "siesta.err"
    append_event(
        events,
        "TASK_STARTED",
        task_id=variant.task_id,
        attempt_id=attempt_id,
        input_sha256=input_hash,
        command=command,
    )
    started = time.monotonic()
    with input_path.open("rb") as stdin_handle, stdout.open("xb") as stdout_handle, stderr.open(
        "xb"
    ) as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=attempt,
            stdin=stdin_handle,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env={
                **os.environ,
                **{
                    str(key): str(value)
                    for key, value in config["runtime"]["environment"].items()
                },
            },
            start_new_session=True,
        )
        with PROCESS_LOCK:
            ACTIVE_PROCESSES[variant.task_id] = process
        try:
            exit_code = int(process.wait())
        finally:
            with PROCESS_LOCK:
                ACTIVE_PROCESSES.pop(variant.task_id, None)
    elapsed = max(0.0, time.monotonic() - started)
    result = parse_siesta_output(
        stdout, stderr, exit_code, config.get("warning_policy")
    )
    post_run_failures: list[str] = []
    if variant.ueff_ev > 0.0 and result.get("edftu_ev") is None:
        post_run_failures.append("DFTU_ENERGY_EVIDENCE_MISSING")
    if int(result.get("force_atom_count", 0)) != int(config["system"]["atoms"]):
        post_run_failures.append("FINAL_FORCE_TABLE_MISSING_OR_INCOMPLETE")
    magnetic = classify_magnetic_state(
        list(result.get("mulliken_atomic_populations", [])), config
    )
    result["magnetic_analysis"] = magnetic
    if magnetic["classification"] == "INCOMPLETE_MN_MULLIKEN_TABLE":
        post_run_failures.append("FINAL_MN_MULLIKEN_TABLE_MISSING_OR_INCOMPLETE")
    if post_run_failures:
        result["status"] = "FAIL"
        result["hard_errors"] = [
            *list(result.get("hard_errors", [])),
            *post_run_failures,
        ]
    result.update(
        {
            "schema_version": "1.0",
            "task_id": variant.task_id,
            "attempt_id": attempt_id,
            "elapsed_seconds": elapsed,
            "input_sha256": input_hash,
            "lineage_sha256": sha256(attempt / "lineage.json"),
            "command_sha256": sha256(attempt / "command.json"),
        }
    )
    result["failure_class"] = (
        None if result["status"] == "PASS" else classify_failure(result, config)
    )
    moments_path = attempt / "mn_moments.csv"
    with moments_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("atom_index", "sz_muB"))
        writer.writeheader()
        for index, value in sorted(
            (int(key), float(value))
            for key, value in magnetic.get("mn_moments_muB", {}).items()
        ):
            writer.writerow({"atom_index": index, "sz_muB": value})
        handle.flush()
        os.fsync(handle.fileno())
    result["mn_moments_csv_sha256"] = sha256(moments_path)
    atomic_json(attempt / "result.json", result)
    artifact_files = [
        path
        for path in sorted(attempt.iterdir())
        if path.is_file() and path.name != "artifacts_manifest.json"
    ]
    atomic_json(
        attempt / "artifacts_manifest.json",
        {
            "schema_version": "1.0",
            "task_id": variant.task_id,
            "attempt_id": attempt_id,
            "files": {
                path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                for path in artifact_files
            },
        },
    )
    selected_relative = f"attempts/{attempt_id}"
    atomic_json(
        directory / "status.json",
        {
            "schema_version": "1.0",
            "task_id": variant.task_id,
            "status": result["status"],
            "selected_attempt": selected_relative,
            "input_sha256": input_hash,
            "result_sha256": sha256(attempt / "result.json"),
            "updated_at_epoch": time.time(),
        },
    )
    append_event(
        events,
        "TASK_FINISHED",
        task_id=variant.task_id,
        attempt_id=attempt_id,
        status=result["status"],
        energy_ev=result.get("energy_ev"),
        elapsed_seconds=elapsed,
    )
    if STOP_REQUESTED:
        raise InterruptedCampaign(f"INTERRUPTED_DURING:{variant.task_id}")
    return result


def run_variant(
    config: Mapping[str, Any],
    run_root: Path,
    events: Path,
    base_text: str,
    variant: Variant,
) -> dict[str, Any]:
    directory = task_directory(run_root, variant)
    fdf = render_fdf(base_text, config, variant)
    input_hash = hashlib.sha256(fdf.encode()).hexdigest()
    cached = completed_result(directory, input_hash)
    if cached is not None:
        append_event(events, "TASK_REUSED", task_id=variant.task_id, input_sha256=input_hash)
        return cached
    maximum = int(config["resilience"]["max_attempts"])
    last: dict[str, Any] | None = None
    for attempt_number in range(1, maximum + 1):
        last = run_variant_once(config, run_root, events, base_text, variant)
        if last["status"] == "PASS":
            return last
        failure_class = str(last["failure_class"])
        append_event(
            events,
            "TASK_ATTEMPT_FAILED",
            task_id=variant.task_id,
            attempt_number=attempt_number,
            failure_class=failure_class,
        )
        if failure_class != "RETRYABLE" or attempt_number == maximum:
            raise CampaignError(
                f"TASK_FAILED:{variant.task_id}:{failure_class}:{last['hard_errors']}"
            )
        time.sleep(float(config["resilience"]["retry_backoff_seconds"]))
    raise CampaignError(f"TASK_FAILED_WITHOUT_RESULT:{variant.task_id}")


def run_variants(
    config: Mapping[str, Any],
    run_root: Path,
    events: Path,
    base_text: str,
    variants: list[Variant],
    step_ntasks: int,
) -> list[tuple[Variant, dict[str, Any]]]:
    materialized = [
        Variant(
            item.task_id,
            item.stage,
            item.mesh_ry,
            item.kgrid,
            item.basis,
            item.ueff_ev,
            item.magnetic_state,
            item.parent_task_id,
            item.parent_decision,
            step_ntasks,
        )
        for item in variants
    ]
    workers = 2 if step_ntasks == 64 else 1
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                run_variant, config, run_root, events, base_text, variant
            ): variant
            for variant in materialized
        }
        for future in concurrent.futures.as_completed(futures):
            variant = futures[future]
            results[variant.task_id] = future.result()
    return [(variant, results[variant.task_id]) for variant in materialized]


def write_stage_summary(
    run_root: Path,
    stage: str,
    rows: Iterable[Mapping[str, Any]],
    decision: Mapping[str, Any],
) -> Path:
    directory = run_root / "stages" / stage
    directory.mkdir(parents=True, exist_ok=True)
    row_list = list(rows)
    fields = sorted({str(key) for row in row_list for key in row})
    output = directory / "summary.csv"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(row_list)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    enriched = {
        **decision,
        "summary_csv": output.relative_to(run_root).as_posix(),
        "summary_sha256": sha256(output),
    }
    decision_path = directory / "decision.json"
    atomic_json(decision_path, enriched)
    return decision_path


def register_reuse(
    run_root: Path,
    *,
    stage: str,
    task_id: str,
    source_variant: Variant,
    source_result: Mapping[str, Any],
    reason: str,
    parent_decision: Path,
) -> Variant:
    variant = Variant(
        task_id,
        stage,
        source_variant.mesh_ry,
        source_variant.kgrid,
        source_variant.basis,
        0.0,
        "FM",
        source_variant.task_id,
        parent_decision.as_posix(),
    )
    directory = task_directory(run_root, variant)
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "1.0",
        "task_id": task_id,
        "status": "PASS_REUSED",
        "source_task_id": source_variant.task_id,
        "source_result_sha256": hashlib.sha256(canonical(source_result).encode()).hexdigest(),
        "reason": reason,
        "parent_decision": parent_decision.relative_to(run_root).as_posix(),
        "parent_decision_sha256": sha256(parent_decision),
    }
    atomic_json(directory / "reuse.json", record)
    atomic_json(
        directory / "status.json",
        {
            "schema_version": "1.0",
            "task_id": task_id,
            "status": "PASS_REUSED",
            "source_task_id": source_variant.task_id,
            "reuse_sha256": sha256(directory / "reuse.json"),
        },
    )
    return variant


def result_row(variant: Variant, result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": variant.task_id,
        "mesh_ry": variant.mesh_ry,
        "kgrid": "x".join(map(str, variant.kgrid)),
        "basis": variant.basis,
        "ueff_ev": variant.ueff_ev,
        "magnetic_state": variant.magnetic_state,
        "status": result["status"],
        "energy_ev": result["energy_ev"],
        "max_force_ev_ang": result.get("max_force_ev_ang"),
        "rms_force_ev_ang": result.get("rms_force_ev_ang"),
        "final_magnetic_classification": result.get("magnetic_analysis", {}).get(
            "classification"
        ),
        "step_ntasks": variant.step_ntasks,
        "scf_iterations": result.get("scf_iterations"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "input_sha256": result.get("input_sha256"),
    }


def build_traceability(run_root: Path) -> None:
    rows: list[dict[str, Any]] = []
    calculations = run_root / "calculations"
    for status_path in sorted(calculations.glob("*/*/status.json")):
        status = json.loads(status_path.read_text(encoding="utf-8"))
        task_dir = status_path.parent
        reuse_path = task_dir / "reuse.json"
        if reuse_path.is_file():
            reuse = json.loads(reuse_path.read_text(encoding="utf-8"))
            rows.append(
                {
                    "stage": task_dir.parent.name,
                    "task_id": status["task_id"],
                    "status": status["status"],
                    "attempt": "",
                    "source_task_id": reuse["source_task_id"],
                    "input_sha256": "",
                    "result_sha256": reuse["source_result_sha256"],
                    "directory": task_dir.relative_to(run_root).as_posix(),
                }
            )
            continue
        rows.append(
            {
                "stage": task_dir.parent.name,
                "task_id": status["task_id"],
                "status": status["status"],
                "attempt": status.get("selected_attempt", ""),
                "source_task_id": "",
                "input_sha256": status.get("input_sha256", ""),
                "result_sha256": status.get("result_sha256", ""),
                "directory": task_dir.relative_to(run_root).as_posix(),
            }
        )
    output = run_root / "traceability.csv"
    fields = (
        "stage",
        "task_id",
        "status",
        "attempt",
        "source_task_id",
        "input_sha256",
        "result_sha256",
        "directory",
    )
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)


def remote_preflight(config: Mapping[str, Any], run_root: Path) -> None:
    if os.environ.get("SLURM_JOB_ID") is None:
        raise CampaignError("MUST_RUN_INSIDE_SLURM_ALLOCATION")
    checks = {
        "SLURM_NNODES": int(config["slurm"]["nodes"]),
        "SLURM_NTASKS": int(config["slurm"]["ntasks"]),
        "SLURM_CPUS_PER_TASK": int(config["slurm"]["cpus_per_task"]),
    }
    for key, expected in checks.items():
        try:
            actual = int(os.environ.get(key, ""))
        except ValueError as exc:
            raise CampaignError(f"INVALID_SLURM_ENVIRONMENT:{key}") from exc
        if actual != expected:
            raise CampaignError(f"SLURM_ALLOCATION_MISMATCH:{key}:{actual}!={expected}")
    tasks_per_node = os.environ.get("SLURM_TASKS_PER_NODE", "")
    if tasks_per_node and not re.match(r"^64(?:\(x2\))?$", tasks_per_node):
        raise CampaignError(f"SLURM_TASKS_PER_NODE_MISMATCH:{tasks_per_node}")
    for command in (
        str(config["runtime"]["launcher"]),
        str(config["runtime"]["siesta_executable"]),
    ):
        if shutil.which(command) is None:
            raise CampaignError(f"RUNTIME_COMMAND_NOT_FOUND:{command}")
    job_query = subprocess.run(
        ["scontrol", "show", "job", "-o", str(os.environ["SLURM_JOB_ID"])],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if job_query.returncode != 0:
        raise CampaignError("SCONTROL_JOB_QUERY_FAILED")
    fields = dict(re.findall(r"(\w+)=([^\s]+)", job_query.stdout))
    expected_fields = {
        "Partition": str(config["slurm"]["partition"]),
        "Account": str(config["slurm"]["account"]),
        "QOS": str(config["slurm"]["qos"]),
    }
    for key, expected in expected_fields.items():
        if fields.get(key) != expected:
            raise CampaignError(
                f"SLURM_JOB_FIELD_MISMATCH:{key}:{fields.get(key)}!={expected}"
            )
    nodelist = fields.get("NodeList") or os.environ.get("SLURM_JOB_NODELIST")
    if not nodelist or nodelist in {"(null)", "N/A"}:
        raise CampaignError("SLURM_NODELIST_MISSING")
    launcher = str(config["runtime"]["launcher"])
    host_probe = subprocess.run(
        [
            launcher,
            "--nodes=2",
            "--ntasks=2",
            "--ntasks-per-node=1",
            "--distribution=block:block",
            "--cpu-bind=cores",
            "bash",
            "-lc",
            'printf "%s %s\\n" "$(hostname)" "$(nproc --all)"',
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    host_rows = [line.split() for line in host_probe.stdout.splitlines() if line.strip()]
    unique_hosts = {row[0] for row in host_rows if len(row) == 2}
    cpu_counts = {
        int(row[1]) for row in host_rows if len(row) == 2 and row[1].isdigit()
    }
    if (
        host_probe.returncode != 0
        or len(unique_hosts) != 2
        or not cpu_counts
        or min(cpu_counts) < 64
    ):
        raise CampaignError(
            f"MULTINODE_HOST_PREFLIGHT_FAILED:{host_probe.returncode}:"
            f"{sorted(unique_hosts)}:{sorted(cpu_counts)}"
        )
    version = subprocess.run(
        [
            launcher,
            "--nodes=2",
            "--ntasks=2",
            "--ntasks-per-node=1",
            "--distribution=block:block",
            "--cpu-bind=cores",
            str(config["runtime"]["siesta_executable"]),
            "--version",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    version_text = version.stdout + "\n" + version.stderr
    required_version = str(config["runtime"]["required_siesta_version"])
    if version.returncode != 0 or version_text.count(required_version) < 2:
        raise CampaignError("MULTINODE_SIESTA_VERSION_PREFLIGHT_FAILED")
    evidence = run_root / "preflight"
    evidence.mkdir(parents=True, exist_ok=True)
    atomic_text(evidence / "siesta_version.txt", version_text)
    atomic_text(evidence / "multinode_hostname.txt", host_probe.stdout)
    atomic_text(evidence / "scontrol_job.txt", job_query.stdout)
    atomic_json(
        evidence / "slurm_environment.json",
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith("SLURM_") or key in {"LOADEDMODULES", "MODULEPATH"}
        },
    )
    atomic_json(
        evidence / "multinode_preflight.json",
        {
            "schema_version": "1.0",
            "status": "PASS",
            "unique_hosts": sorted(unique_hosts),
            "physical_cpus_reported": sorted(cpu_counts),
            "partition": fields["Partition"],
            "account": fields["Account"],
            "qos": fields["QOS"],
            "nodelist": nodelist,
            "cpu_bind": str(config["execution"]["cpu_bind"]),
            "siesta_version": required_version,
        },
    )


def evaluate_magnetic_matrix(
    config: Mapping[str, Any],
    u_results: Mapping[tuple[float, str], tuple[Variant, Mapping[str, Any]]],
) -> tuple[dict[str, Any], list[str], bool]:
    mn_atoms = int(config["system"]["mn_atoms"])
    degeneracy = float(config["numerical_policy"]["magnetic_degeneracy_mev_per_mn"])
    selections: dict[str, Any] = {}
    selected_orders: list[str] = []
    for ueff in map(float, config["dftu"]["ueff_ev"]):
        fm_variant, fm_result = u_results[(ueff, "FM")]
        afm_variant, afm_result = u_results[(ueff, "STRIPE_AFM")]
        fm_final = fm_result["magnetic_analysis"]["classification"]
        afm_final = afm_result["magnetic_analysis"]["classification"]
        comparable = fm_final == "FM" and afm_final == "STRIPE_AFM"
        delta: float | None = None
        if not comparable:
            order = "NOT_COMPARABLE_FINAL_STATE_COLLAPSE"
        else:
            delta = (
                abs(float(fm_result["energy_ev"]) - float(afm_result["energy_ev"]))
                * 1000.0
                / mn_atoms
            )
            if delta <= degeneracy:
                order = "NUMERICALLY_DEGENERATE"
            elif float(fm_result["energy_ev"]) < float(afm_result["energy_ev"]):
                order = "FM"
            else:
                order = "STRIPE_AFM"
        selections[str(ueff)] = {
            "selected_order_within_candidate_set": order,
            "energy_comparison_performed": comparable,
            "fm_task_id": fm_variant.task_id,
            "stripe_afm_task_id": afm_variant.task_id,
            "fm_final_classification": fm_final,
            "stripe_afm_final_classification": afm_final,
            "delta_mev_per_mn": delta,
            "criterion_mev_per_mn": degeneracy,
        }
        selected_orders.append(order)
    robust = (
        len(set(selected_orders)) == 1
        and selected_orders[0] in {"FM", "STRIPE_AFM"}
    )
    return selections, selected_orders, robust


def run_scaling_benchmark(
    config: Mapping[str, Any],
    run_root: Path,
    events: Path,
    base_text: str,
) -> tuple[int, Variant, dict[str, Any], Path]:
    fixed_k = tuple(map(int, config["numerical_policy"]["mesh_fixed_kgrid"]))
    mesh = int(config["numerical_policy"]["mesh_ry"][0])
    replicas = [
        Variant(f"scaling_64_replica_{index}", "00_scaling", mesh, fixed_k)
        for index in range(1, 3)
    ]
    results_64 = run_variants(
        config, run_root, events, base_text, replicas, step_ntasks=64
    )
    variant_128 = Variant("scaling_128", "00_scaling", mesh, fixed_k)
    result_128 = run_variants(
        config, run_root, events, base_text, [variant_128], step_ntasks=128
    )[0]
    atoms = int(config["system"]["atoms"])
    numerical = config["numerical_policy"]
    reference_64 = results_64[0]
    equivalence_rows: list[dict[str, Any]] = []
    for variant, result in [results_64[1], result_128]:
        metrics = compare_results(reference_64[1], result, atoms)
        passed = convergence_passes(
            metrics,
            float(numerical["energy_tolerance_mev_per_atom"]),
            float(numerical["max_force_delta_tolerance_ev_ang"]),
            float(numerical["rms_force_delta_tolerance_ev_ang"]),
        )
        equivalence_rows.append(
            {
                "reference_task_id": reference_64[0].task_id,
                "comparison_task_id": variant.task_id,
                **metrics,
                "pass": passed,
            }
        )
        if not passed:
            raise CampaignError(
                f"MPI_SCALING_NUMERICAL_EQUIVALENCE_FAILED:{variant.task_id}"
            )
    median_64 = statistics.median(
        float(result["elapsed_seconds"]) for _, result in results_64
    )
    elapsed_128 = float(result_128[1]["elapsed_seconds"])
    speedup = median_64 / elapsed_128 if elapsed_128 > 0 else 0.0
    threshold = float(config["execution"]["minimum_speedup_128_vs_64"])
    selected_ntasks = 128 if speedup >= threshold else 64
    selected_variant, selected_result = (
        result_128 if selected_ntasks == 128 else reference_64
    )
    decision = write_stage_summary(
        run_root,
        "00_scaling",
        [
            result_row(variant, result)
            for variant, result in [*results_64, result_128]
        ],
        {
            "schema_version": "1.0",
            "stage": "00_scaling",
            "status": "PASS",
            "allocation_ntasks": int(config["slurm"]["ntasks"]),
            "selected_step_ntasks": selected_ntasks,
            "parallel_steps": 1 if selected_ntasks == 128 else 2,
            "median_elapsed_64_seconds": median_64,
            "elapsed_128_seconds": elapsed_128,
            "speedup_128_vs_64": speedup,
            "minimum_speedup_required_for_128": threshold,
            "numerical_equivalence": equivalence_rows,
        },
    )
    return selected_ntasks, selected_variant, selected_result, decision


def run_campaign(config: Mapping[str, Any], run_root: Path) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=True)
    events = run_root / "events.jsonl"
    static_hashes = validate_static_files(config)
    remote_preflight(config, run_root)
    append_event(events, "CAMPAIGN_STARTED", package_id=config["package_id"])
    base_text = (PACKAGE_ROOT / str(config["system"]["base_fdf"])).read_text(
        encoding="utf-8"
    )
    atoms = int(config["system"]["atoms"])
    tolerance = float(config["numerical_policy"]["energy_tolerance_mev_per_atom"])
    force_max_tolerance = float(
        config["numerical_policy"]["max_force_delta_tolerance_ev_ang"]
    )
    force_rms_tolerance = float(
        config["numerical_policy"]["rms_force_delta_tolerance_ev_ang"]
    )
    selected_ntasks, scaling_variant, scaling_result, scaling_decision = (
        run_scaling_benchmark(config, run_root, events, base_text)
    )

    mesh_results: list[tuple[Variant, dict[str, Any]]] = [
        (scaling_variant, scaling_result)
    ]
    fixed_k = tuple(map(int, config["numerical_policy"]["mesh_fixed_kgrid"]))
    mesh_variants = [
        Variant(
            f"mesh_{mesh}ry",
            "01_mesh",
            int(mesh),
            fixed_k,
            parent_task_id=scaling_variant.task_id,
            parent_decision=scaling_decision.relative_to(run_root).as_posix(),
        )
        for mesh in config["numerical_policy"]["mesh_ry"][1:]
    ]
    mesh_results.extend(
        run_variants(
            config,
            run_root,
            events,
            base_text,
            mesh_variants,
            selected_ntasks,
        )
    )
    selected_mesh, mesh_deltas = select_plateau(
        [(item.mesh_ry, result) for item, result in mesh_results],
        tolerance,
        atoms,
        force_max_tolerance,
        force_rms_tolerance,
    )
    if selected_mesh is None:
        raise CampaignError("MESH_CONVERGENCE_NOT_REACHED")
    mesh_decision = write_stage_summary(
        run_root,
        "01_mesh",
        [result_row(item, result) for item, result in mesh_results],
        {
            "schema_version": "1.0",
            "stage": "01_mesh",
            "status": "PASS",
            "criterion": config["numerical_policy"]["plateau_rule"],
            "tolerance_mev_per_atom": tolerance,
            "max_force_delta_tolerance_ev_ang": force_max_tolerance,
            "rms_force_delta_tolerance_ev_ang": force_rms_tolerance,
            "all_stricter_comparisons": mesh_deltas,
            "selected_mesh_ry": selected_mesh,
        },
    )

    k_variants: list[Variant] = []
    for grid in config["numerical_policy"]["kgrids"]:
        kgrid = tuple(map(int, grid))
        name = "x".join(map(str, kgrid))
        k_variants.append(
            Variant(
            f"kgrid_{name}",
            "02_kgrid",
            int(selected_mesh),
            kgrid,
            parent_decision=mesh_decision.relative_to(run_root).as_posix(),
            )
        )
    k_results = run_variants(
        config, run_root, events, base_text, k_variants, selected_ntasks
    )
    selected_k, k_deltas = select_plateau(
        [(item.kgrid, result) for item, result in k_results],
        tolerance,
        atoms,
        force_max_tolerance,
        force_rms_tolerance,
    )
    optional_executed = False
    if selected_k is None:
        grid = tuple(map(int, config["numerical_policy"]["optional_kgrid"]))
        name = "x".join(map(str, grid))
        variant = Variant(
            f"kgrid_{name}",
            "02_kgrid",
            int(selected_mesh),
            grid,
            parent_decision=mesh_decision.relative_to(run_root).as_posix(),
        )
        k_results.extend(
            run_variants(
                config,
                run_root,
                events,
                base_text,
                [variant],
                selected_ntasks,
            )
        )
        optional_executed = True
        selected_k, k_deltas = select_plateau(
            [(item.kgrid, result) for item, result in k_results],
            tolerance,
            atoms,
            force_max_tolerance,
            force_rms_tolerance,
        )
    if selected_k is None:
        raise CampaignError("KGRID_CONVERGENCE_NOT_REACHED_AFTER_5X5X1")
    selected_k = tuple(map(int, selected_k))
    selected_k_variant, selected_k_result = next(
        (item, result) for item, result in k_results if item.kgrid == selected_k
    )
    k_decision = write_stage_summary(
        run_root,
        "02_kgrid",
        [result_row(item, result) for item, result in k_results],
        {
            "schema_version": "1.0",
            "stage": "02_kgrid",
            "status": "PASS",
            "criterion": config["numerical_policy"]["plateau_rule"] + "; kz=1",
            "tolerance_mev_per_atom": tolerance,
            "max_force_delta_tolerance_ev_ang": force_max_tolerance,
            "rms_force_delta_tolerance_ev_ang": force_rms_tolerance,
            "all_stricter_comparisons": k_deltas,
            "selected_kgrid": list(selected_k),
            "optional_5x5x1_executed": optional_executed,
            "selected_mesh_ry": selected_mesh,
        },
    )

    dzp_reference = register_reuse(
        run_root,
        stage="03_basis",
        task_id="basis_dzp_reference",
        source_variant=selected_k_variant,
        source_result=selected_k_result,
        reason="Selected k-grid calculation already is the matched U0/FM/DZP reference.",
        parent_decision=k_decision,
    )
    tzp_variant = Variant(
        "basis_explicit_tzp",
        "03_basis",
        int(selected_mesh),
        selected_k,
        "EXPLICIT_TZP",
        parent_task_id=selected_k_variant.task_id,
        parent_decision=k_decision.relative_to(run_root).as_posix(),
    )
    tzp_variant, tzp_result = run_variants(
        config,
        run_root,
        events,
        base_text,
        [tzp_variant],
        selected_ntasks,
    )[0]
    basis_comparison = compare_results(selected_k_result, tzp_result, atoms)
    basis_passes = convergence_passes(
        basis_comparison,
        tolerance,
        force_max_tolerance,
        force_rms_tolerance,
    )
    if basis_passes:
        selected_basis = "DZP"
        selected_basis_variant = selected_k_variant
        selected_basis_result = selected_k_result
    else:
        selected_basis = "EXPLICIT_TZP"
        selected_basis_variant = tzp_variant
        selected_basis_result = tzp_result
    basis_decision = write_stage_summary(
        run_root,
        "03_basis",
        [
            {
                **result_row(selected_k_variant, selected_k_result),
                "logical_task_id": dzp_reference.task_id,
                "reuse": True,
            },
            {**result_row(tzp_variant, tzp_result), "reuse": False},
        ],
        {
            "schema_version": "1.0",
            "stage": "03_basis",
            "status": "PASS",
            "criterion": config["numerical_policy"]["basis_rule"],
            "tolerance_mev_per_atom": tolerance,
            "max_force_delta_tolerance_ev_ang": force_max_tolerance,
            "rms_force_delta_tolerance_ev_ang": force_rms_tolerance,
            "dzp_to_tzp_comparison": basis_comparison,
            "selected_basis": selected_basis,
            "strict_basis_is_manual_pao_block": True,
        },
    )

    strict_mesh = int(config["numerical_policy"]["mesh_ry"][-1])
    strict_k = tuple(map(int, config["numerical_policy"]["optional_kgrid"]))
    closure_source_variant = selected_basis_variant
    closure_source_result = selected_basis_result
    promoted_to_strictest = False
    if (
        int(selected_mesh) == strict_mesh
        and selected_k == strict_k
        and selected_basis_variant.basis == selected_basis
    ):
        closure_variant = selected_basis_variant
        closure_result = selected_basis_result
        closure_comparison = {
            "energy_delta_mev_per_atom": 0.0,
            "max_force_delta_ev_ang": 0.0,
            "rms_force_delta_ev_ang": 0.0,
        }
        closure_passes = True
        closure_reused = True
    else:
        closure_variant = Variant(
            "closure_strictest_mesh_k_basis",
            "04_closure",
            strict_mesh,
            strict_k,
            selected_basis,
            parent_task_id=selected_basis_variant.task_id,
            parent_decision=basis_decision.relative_to(run_root).as_posix(),
        )
        closure_variant, closure_result = run_variants(
            config,
            run_root,
            events,
            base_text,
            [closure_variant],
            selected_ntasks,
        )[0]
        closure_comparison = compare_results(
            selected_basis_result, closure_result, atoms
        )
        closure_passes = convergence_passes(
            closure_comparison,
            tolerance,
            force_max_tolerance,
            force_rms_tolerance,
        )
        closure_reused = False
    if not closure_passes:
        selected_mesh = strict_mesh
        selected_k = strict_k
        selected_basis_variant = closure_variant
        selected_basis_result = closure_result
        promoted_to_strictest = True
    closure_decision = write_stage_summary(
        run_root,
        "04_closure",
        [
            {
                **result_row(closure_source_variant, closure_source_result),
                "role": "preclosure_selected_reference",
            },
            {
                **result_row(closure_variant, closure_result),
                "role": "strictest_tested_reference",
                "reuse": closure_reused,
            },
        ],
        {
            "schema_version": "1.0",
            "stage": "04_closure",
            "status": "PASS"
            if closure_passes
            else "PASS_PROMOTED_TO_STRICTEST_TESTED",
            "criterion": config["numerical_policy"]["closure_rule"],
            "comparison": closure_comparison,
            "selected_parameters_passed_closure": closure_passes,
            "promoted_to_strictest_tested": promoted_to_strictest,
            "final_mesh_ry": int(selected_mesh),
            "final_kgrid": list(selected_k),
            "final_basis": selected_basis,
        },
    )

    u0_variant = register_reuse(
        run_root,
        stage="05_u_spin",
        task_id="u0_fm_reference",
        source_variant=selected_basis_variant,
        source_result=selected_basis_result,
        reason="Matched selected numerical/basis U0/FM calculation reused without rerun.",
        parent_decision=closure_decision,
    )
    u_results: dict[tuple[float, str], tuple[Variant, dict[str, Any]]] = {}
    u_variants: list[Variant] = []
    for ueff in map(float, config["dftu"]["ueff_ev"]):
        for state in config["magnetism"]["states"]:
            token = str(ueff).replace(".", "p")
            u_variants.append(
                Variant(
                f"u{token}_{state.lower()}",
                "05_u_spin",
                int(selected_mesh),
                selected_k,
                selected_basis,
                ueff,
                str(state),
                u0_variant.task_id,
                closure_decision.relative_to(run_root).as_posix(),
                )
            )
    for variant, result in run_variants(
        config,
        run_root,
        events,
        base_text,
        u_variants,
        selected_ntasks,
    ):
        u_results[(variant.ueff_ev, variant.magnetic_state)] = (variant, result)

    selections, selected_orders, robust = evaluate_magnetic_matrix(config, u_results)
    primary_u = float(config["dftu"]["primary_literature_protocol_ueff_ev"])
    primary_order = selections[str(primary_u)][
        "selected_order_within_candidate_set"
    ]
    transfer_rows: list[dict[str, Any]] = []
    u_transfer_promoted = False
    if primary_order in {"FM", "STRIPE_AFM"}:
        source_variant, source_result = u_results[(primary_u, primary_order)]
        if int(selected_mesh) == strict_mesh and selected_k == strict_k:
            transfer_variant, transfer_result = source_variant, source_result
            transfer_comparison = {
                "energy_delta_mev_per_atom": 0.0,
                "max_force_delta_ev_ang": 0.0,
                "rms_force_delta_ev_ang": 0.0,
            }
            transfer_passes = True
            transfer_reused = True
        else:
            token = str(primary_u).replace(".", "p")
            transfer_variant = Variant(
                f"transfer_u{token}_{primary_order.lower()}_strict",
                "06_u_transfer",
                strict_mesh,
                strict_k,
                selected_basis,
                primary_u,
                primary_order,
                source_variant.task_id,
                closure_decision.relative_to(run_root).as_posix(),
            )
            transfer_variant, transfer_result = run_variants(
                config,
                run_root,
                events,
                base_text,
                [transfer_variant],
                selected_ntasks,
            )[0]
            transfer_comparison = compare_results(
                source_result, transfer_result, atoms
            )
            transfer_passes = convergence_passes(
                transfer_comparison,
                tolerance,
                force_max_tolerance,
                force_rms_tolerance,
            ) and (
                transfer_result["magnetic_analysis"]["classification"]
                == primary_order
            )
            transfer_reused = False
        transfer_rows.extend(
            [
                {
                    **result_row(source_variant, source_result),
                    "role": "selected_DFTU_magnetic_reference",
                },
                {
                    **result_row(transfer_variant, transfer_result),
                    "role": "strictest_DFTU_transfer_reference",
                    "reuse": transfer_reused,
                },
            ]
        )
        if not transfer_passes:
            promoted_variants: list[Variant] = []
            for ueff in map(float, config["dftu"]["ueff_ev"]):
                for state in config["magnetism"]["states"]:
                    token = str(ueff).replace(".", "p")
                    promoted_variants.append(
                        Variant(
                            f"strict_u{token}_{str(state).lower()}",
                            "06_u_transfer",
                            strict_mesh,
                            strict_k,
                            selected_basis,
                            ueff,
                            str(state),
                            source_variant.task_id,
                            closure_decision.relative_to(run_root).as_posix(),
                        )
                    )
            promoted_results = run_variants(
                config,
                run_root,
                events,
                base_text,
                promoted_variants,
                selected_ntasks,
            )
            u_results = {
                (variant.ueff_ev, variant.magnetic_state): (variant, result)
                for variant, result in promoted_results
            }
            selections, selected_orders, robust = evaluate_magnetic_matrix(
                config, u_results
            )
            selected_mesh = strict_mesh
            selected_k = strict_k
            u_transfer_promoted = True
            transfer_rows.extend(
                {
                    **result_row(variant, result),
                    "role": "promoted_strict_DFTU_matrix",
                }
                for variant, result in promoted_results
            )
    else:
        transfer_comparison = None
        transfer_passes = False
        transfer_reused = False
    transfer_decision = write_stage_summary(
        run_root,
        "06_u_transfer",
        transfer_rows,
        {
            "schema_version": "1.0",
            "stage": "06_u_transfer",
            "status": (
                "PASS_PROMOTED_TO_STRICTEST_TESTED"
                if u_transfer_promoted
                else "PASS"
                if transfer_passes
                else "NOT_COMPARABLE_REVIEW_REQUIRED"
            ),
            "primary_ueff_ev": primary_u,
            "primary_order_within_candidate_set": primary_order,
            "comparison": transfer_comparison,
            "original_transfer_passed": transfer_passes,
            "transfer_resolved": transfer_passes or u_transfer_promoted,
            "promoted_full_u_spin_matrix_to_strictest": u_transfer_promoted,
        },
    )
    magnetic_status = (
        "ROBUST_WITHIN_TESTED_FM_STRIPE_SET"
        if robust
        else "COMPLETED_REVIEW_REQUIRED"
    )
    u_decision = write_stage_summary(
        run_root,
        "05_u_spin",
        [
            {
                "task_id": u0_variant.task_id,
                "reuse": True,
                "source_task_id": selected_basis_variant.task_id,
                "ueff_ev": 0.0,
                "magnetic_state": "FM",
                "energy_ev": selected_basis_result["energy_ev"],
                "status": "PASS_REUSED",
            },
            *[
                {**result_row(variant, result), "reuse": False}
                for variant, result in u_results.values()
            ],
        ],
        {
            "schema_version": "1.0",
            "stage": "05_u_spin",
            "status": magnetic_status,
            "cross_U_energy_ranking_performed": False,
            "primary_ueff_ev": float(config["dftu"]["primary_literature_protocol_ueff_ev"]),
            "sensitivity_ueff_ev": float(config["dftu"]["sensitivity_ueff_ev"]),
            "within_U_selections": selections,
            "magnetic_order_robust_across_U_within_tested_candidate_set": robust,
            "selected_magnetic_order_within_candidate_set": (
                selected_orders[0] if robust else None
            ),
            "untested_orders": [
                "other_AFM_patterns",
                "ferrimagnetic",
                "non_collinear",
                "frustrated_states",
            ],
        },
    )
    build_traceability(run_root)
    final = {
        "schema_version": "1.0",
        "package_id": config["package_id"],
        "scope": config["scope"],
        "status": magnetic_status,
        "selected_mesh_ry": selected_mesh,
        "selected_kgrid": list(selected_k),
        "selected_basis": selected_basis,
        "primary_ueff_ev": float(config["dftu"]["primary_literature_protocol_ueff_ev"]),
        "selected_magnetic_order_within_candidate_set": (
            selected_orders[0] if robust else None
        ),
        "allocation_ntasks": int(config["slurm"]["ntasks"]),
        "selected_step_ntasks": selected_ntasks,
        "optional_5x5x1_executed": optional_executed,
        "decisions": {
            "scaling": scaling_decision.relative_to(run_root).as_posix(),
            "mesh": mesh_decision.relative_to(run_root).as_posix(),
            "kgrid": k_decision.relative_to(run_root).as_posix(),
            "basis": basis_decision.relative_to(run_root).as_posix(),
            "closure": closure_decision.relative_to(run_root).as_posix(),
            "u_spin": u_decision.relative_to(run_root).as_posix(),
            "u_transfer": transfer_decision.relative_to(run_root).as_posix(),
        },
        "static_input_sha256": static_hashes,
        "traceability_csv": "traceability.csv",
        "production_relaxation_executed": False,
        "electronic_postprocessing_executed": False,
    }
    atomic_json(run_root / "final_summary.json", final)
    append_event(events, "CAMPAIGN_FINISHED", status=magnetic_status)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-root",
        type=Path,
        default=PACKAGE_ROOT / "runs/autoconvergence",
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    config = load_config()
    hashes = validate_static_files(config)
    if args.validate_only:
        print(
            json.dumps(
                {
                    "status": "STATIC_VALIDATION_PASS",
                    "package_id": config["package_id"],
                    "files": hashes,
                },
                sort_keys=True,
            )
        )
        return 0
    run_root = args.run_root.resolve()
    for number in (getattr(signal, "SIGUSR1", None), signal.SIGTERM):
        if number is not None:
            signal.signal(number, signal_handler)
    try:
        final = run_campaign(config, run_root)
    except InterruptedCampaign as exc:
        build_traceability(run_root)
        atomic_json(
            run_root / "interrupted.json",
            {
                "status": "INTERRUPTED_RESUMABLE",
                "reason": str(exc),
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            },
        )
        print(f"INTERRUPTED_RESUMABLE:{exc}", file=sys.stderr)
        return 3
    except (CampaignError, OSError, subprocess.SubprocessError) as exc:
        build_traceability(run_root)
        atomic_json(
            run_root / "failure.json",
            {
                "status": "FAILED_CLOSED",
                "reason": f"{type(exc).__name__}:{exc}",
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            },
        )
        print(f"FAILED_CLOSED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2
    print(json.dumps(final, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
