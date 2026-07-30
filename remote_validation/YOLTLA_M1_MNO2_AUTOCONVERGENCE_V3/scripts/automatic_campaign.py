#!/usr/bin/env python3
"""Run the complete M1 numerical/basis/U-spin test chain in one SLURM allocation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PACKAGE_ROOT / "campaign.json"
FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
STOP_REQUESTED = False
ACTIVE_PROCESS: subprocess.Popen[bytes] | None = None


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
    if config.get("package_id") != "YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3":
        raise CampaignError("PACKAGE_ID_MISMATCH")
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
        raise CampaignError("UNDOCUMENTED_PAO_BASISSIZE_TZP_FORBIDDEN")


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
    }
    header = (
        "# generated_by=YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3\n"
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


def parse_siesta_output(stdout: Path, stderr: Path, exit_code: int) -> dict[str, Any]:
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
            energies = [float(item.replace("D", "E").replace("d", "e")) for item in matches]
            break
    iterations = [
        int(value)
        for value in re.findall(
            r"(?i)SCF cycle converged after\s+(\d+)\s+iterations", combined
        )
    ]
    edftu = [
        float(item.replace("D", "E").replace("d", "e"))
        for item in re.findall(
            r"(?im)^\s*siesta:\s+Edftu\s*=\s*(" + FLOAT + r")\s*$", combined
        )
    ]
    warning_lines = [
        line.strip()
        for line in combined.splitlines()
        if "warning" in line.casefold()
    ][:100]
    spin_lines = [
        line.strip()
        for line in combined.splitlines()
        if re.search(r"(?i)\b(spin|mulliken|magneti[cz]|Sz)\b", line)
    ][-200:]
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
    success = bool(exit_code == 0 and normal and scf and energies and not errors)
    return {
        "status": "PASS" if success else "FAIL",
        "exit_code": exit_code,
        "normal_termination": normal,
        "scf_converged": scf,
        "scf_iterations": iterations[-1] if iterations else None,
        "energy_ev": energies[-1] if energies else None,
        "edftu_ev": edftu[-1] if edftu else None,
        "warnings": warning_lines,
        "spin_evidence_lines": spin_lines,
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


def select_plateau(
    values: Iterable[tuple[Any, float]], tolerance_mev_per_unit: float, denominator: int
) -> tuple[Any | None, list[dict[str, Any]]]:
    ordered = list(values)
    if len(ordered) < 2:
        raise CampaignError("AT_LEAST_TWO_POINTS_REQUIRED")
    deltas = adjacent_deltas_mev_per_unit(ordered, denominator)
    for index, delta in enumerate(deltas):
        if all(
            item["delta_mev_per_unit"] <= tolerance_mev_per_unit
            for item in deltas[index:]
        ):
            return ordered[index + 1][0], deltas
    return None, deltas


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
    process = ACTIVE_PROCESS
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (AttributeError, OSError, ProcessLookupError):
            process.terminate()


def run_variant(
    config: Mapping[str, Any],
    run_root: Path,
    events: Path,
    base_text: str,
    variant: Variant,
) -> dict[str, Any]:
    global ACTIVE_PROCESS
    if STOP_REQUESTED:
        raise InterruptedCampaign("STOP_REQUESTED_BEFORE_TASK")
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
        },
        "slurm": {
            "job_id": os.environ.get("SLURM_JOB_ID"),
            "nodes": int(config["slurm"]["nodes"]),
            "ntasks": int(config["slurm"]["ntasks"]),
            "ntasks_per_node": int(config["slurm"]["ntasks_per_node"]),
        },
    }
    atomic_json(attempt / "lineage.json", lineage)
    command = [
        str(config["runtime"]["launcher"]),
        "--exclusive",
        "--kill-on-bad-exit=1",
        f"--nodes={int(config['slurm']['nodes'])}",
        f"--ntasks={int(config['slurm']['ntasks'])}",
        f"--ntasks-per-node={int(config['slurm']['ntasks_per_node'])}",
        f"--cpus-per-task={int(config['slurm']['cpus_per_task'])}",
        "--distribution=block:block",
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
        ACTIVE_PROCESS = subprocess.Popen(
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
        exit_code = int(ACTIVE_PROCESS.wait())
        ACTIVE_PROCESS = None
    elapsed = max(0.0, time.monotonic() - started)
    result = parse_siesta_output(stdout, stderr, exit_code)
    post_run_failures: list[str] = []
    if variant.ueff_ev > 0.0 and result.get("edftu_ev") is None:
        post_run_failures.append("DFTU_ENERGY_EVIDENCE_MISSING")
    if not result.get("spin_evidence_lines"):
        post_run_failures.append("SPIN_POPULATION_EVIDENCE_MISSING")
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
    if result["status"] != "PASS":
        raise CampaignError(f"TASK_FAILED:{variant.task_id}:{result['hard_errors']}")
    return result


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
    version = subprocess.run(
        [str(config["runtime"]["siesta_executable"]), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    version_text = version.stdout + "\n" + version.stderr
    if str(config["runtime"]["required_siesta_version"]) not in version_text:
        raise CampaignError("SIESTA_VERSION_MISMATCH")
    evidence = run_root / "preflight"
    evidence.mkdir(parents=True, exist_ok=True)
    atomic_text(evidence / "siesta_version.txt", version_text)
    atomic_json(
        evidence / "slurm_environment.json",
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith("SLURM_") or key in {"LOADEDMODULES", "MODULEPATH"}
        },
    )


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

    mesh_results: list[tuple[Variant, dict[str, Any]]] = []
    fixed_k = tuple(map(int, config["numerical_policy"]["mesh_fixed_kgrid"]))
    for mesh in config["numerical_policy"]["mesh_ry"]:
        variant = Variant(f"mesh_{mesh}ry", "01_mesh", int(mesh), fixed_k)
        mesh_results.append(
            (variant, run_variant(config, run_root, events, base_text, variant))
        )
    selected_mesh, mesh_deltas = select_plateau(
        [(item.mesh_ry, float(result["energy_ev"])) for item, result in mesh_results],
        tolerance,
        atoms,
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
            "criterion": "all subsequent adjacent deltas <= tolerance",
            "tolerance_mev_per_atom": tolerance,
            "adjacent_deltas": mesh_deltas,
            "selected_mesh_ry": selected_mesh,
        },
    )

    k_results: list[tuple[Variant, dict[str, Any]]] = []
    for grid in config["numerical_policy"]["kgrids"]:
        kgrid = tuple(map(int, grid))
        name = "x".join(map(str, kgrid))
        variant = Variant(
            f"kgrid_{name}",
            "02_kgrid",
            int(selected_mesh),
            kgrid,
            parent_decision=mesh_decision.relative_to(run_root).as_posix(),
        )
        k_results.append(
            (variant, run_variant(config, run_root, events, base_text, variant))
        )
    selected_k, k_deltas = select_plateau(
        [(item.kgrid, float(result["energy_ev"])) for item, result in k_results],
        tolerance,
        atoms,
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
        k_results.append(
            (variant, run_variant(config, run_root, events, base_text, variant))
        )
        optional_executed = True
        selected_k, k_deltas = select_plateau(
            [(item.kgrid, float(result["energy_ev"])) for item, result in k_results],
            tolerance,
            atoms,
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
            "criterion": "all subsequent adjacent deltas <= tolerance; kz=1",
            "tolerance_mev_per_atom": tolerance,
            "adjacent_deltas": k_deltas,
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
    tzp_result = run_variant(config, run_root, events, base_text, tzp_variant)
    basis_delta = (
        abs(float(tzp_result["energy_ev"]) - float(selected_k_result["energy_ev"]))
        * 1000.0
        / atoms
    )
    if basis_delta <= tolerance:
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
            "dzp_to_tzp_delta_mev_per_atom": basis_delta,
            "selected_basis": selected_basis,
            "strict_basis_is_manual_pao_block": True,
        },
    )

    u0_variant = register_reuse(
        run_root,
        stage="04_u_spin",
        task_id="u0_fm_reference",
        source_variant=selected_basis_variant,
        source_result=selected_basis_result,
        reason="Matched selected numerical/basis U0/FM calculation reused without rerun.",
        parent_decision=basis_decision,
    )
    u_results: dict[tuple[float, str], tuple[Variant, dict[str, Any]]] = {}
    for ueff in map(float, config["dftu"]["ueff_ev"]):
        for state in config["magnetism"]["states"]:
            token = str(ueff).replace(".", "p")
            variant = Variant(
                f"u{token}_{state.lower()}",
                "04_u_spin",
                int(selected_mesh),
                selected_k,
                selected_basis,
                ueff,
                str(state),
                u0_variant.task_id,
                basis_decision.relative_to(run_root).as_posix(),
            )
            u_results[(ueff, str(state))] = (
                variant,
                run_variant(config, run_root, events, base_text, variant),
            )

    mn_atoms = int(config["system"]["mn_atoms"])
    degeneracy = float(config["numerical_policy"]["magnetic_degeneracy_mev_per_mn"])
    selections: dict[str, Any] = {}
    selected_orders: list[str] = []
    for ueff in map(float, config["dftu"]["ueff_ev"]):
        fm_variant, fm_result = u_results[(ueff, "FM")]
        afm_variant, afm_result = u_results[(ueff, "STRIPE_AFM")]
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
            "selected_order": order,
            "fm_task_id": fm_variant.task_id,
            "stripe_afm_task_id": afm_variant.task_id,
            "delta_mev_per_mn": delta,
            "criterion_mev_per_mn": degeneracy,
        }
        selected_orders.append(order)
    robust = (
        len(set(selected_orders)) == 1
        and selected_orders[0] != "NUMERICALLY_DEGENERATE"
    )
    magnetic_status = "PASS_ROBUST" if robust else "COMPLETED_REVIEW_REQUIRED"
    u_decision = write_stage_summary(
        run_root,
        "04_u_spin",
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
            "stage": "04_u_spin",
            "status": magnetic_status,
            "cross_U_energy_ranking_performed": False,
            "primary_ueff_ev": float(config["dftu"]["primary_literature_protocol_ueff_ev"]),
            "sensitivity_ueff_ev": float(config["dftu"]["sensitivity_ueff_ev"]),
            "within_U_selections": selections,
            "magnetic_order_robust_across_U": robust,
            "selected_magnetic_order": selected_orders[0] if robust else None,
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
        "selected_magnetic_order": selected_orders[0] if robust else None,
        "optional_5x5x1_executed": optional_executed,
        "decisions": {
            "mesh": mesh_decision.relative_to(run_root).as_posix(),
            "kgrid": k_decision.relative_to(run_root).as_posix(),
            "basis": basis_decision.relative_to(run_root).as_posix(),
            "u_spin": u_decision.relative_to(run_root).as_posix(),
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
