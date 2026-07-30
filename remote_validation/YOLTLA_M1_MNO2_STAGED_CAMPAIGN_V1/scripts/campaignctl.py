#!/usr/bin/env python3
"""Fail-closed preparation and inspection for the staged Yoltla M1 campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_FDF = ROOT / "inputs/base/M1_U0_FM.pilot.NO_PRODUCTION.fdf"
BASE_FDF_SHA256 = "714d16dabd1732f0d21ac8d7947abc2d00748fce509b1a052e3e31c2c9ebc35c"
PSEUDO_HASHES = {
    "Mn.psml": "0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6",
    "O.psml": "224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e",
}
PREPARABLE = {"PREPARED", "PREPARED_DYNAMIC"}
PROFILE_READY = "VERIFIED_FOR_PRODUCTION"
SAFE_DIRECTIVE = re.compile(r"^[A-Za-z0-9_.:+-]+$")
SAFE_MODULE = re.compile(r"^module\s+(?:purge|load|use)(?:\s+[A-Za-z0-9_./:+-]+)*$")


class CampaignError(RuntimeError):
    """A scientific or operational guard failed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"INVALID_JSON:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def safe_relative(value: str) -> Path:
    posix = PurePosixPath(str(value).replace("\\", "/"))
    if not value or posix.is_absolute() or ".." in posix.parts:
        raise CampaignError(f"UNSAFE_RELATIVE_PATH:{value}")
    return Path(*posix.parts)


def phase_path(phase_id: str) -> Path:
    path = ROOT / "campaigns" / f"{phase_id}.json"
    if not path.is_file():
        raise CampaignError(f"UNKNOWN_PHASE:{phase_id}")
    return path


def gate_path(gate_id: str) -> Path:
    return ROOT / "gates" / "decisions" / f"{gate_id}.json"


def validate_evidence_hashes(data: dict[str, Any], owner: str) -> None:
    evidence = data.get("evidence_sha256")
    if not isinstance(evidence, dict) or not evidence:
        raise CampaignError(f"{owner}:EVIDENCE_HASHES_REQUIRED")
    for name, expected in evidence.items():
        relative = safe_relative(str(name))
        target = ROOT / relative
        digest = str(expected).lower()
        if not target.is_file():
            raise CampaignError(f"{owner}:MISSING_EVIDENCE:{relative.as_posix()}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CampaignError(f"{owner}:INVALID_EVIDENCE_SHA256:{relative.as_posix()}")
        if sha256(target) != digest:
            raise CampaignError(f"{owner}:EVIDENCE_HASH_MISMATCH:{relative.as_posix()}")


def validate_gate(gate_id: str) -> tuple[Path, dict[str, Any]]:
    path = gate_path(gate_id)
    if not path.is_file():
        raise CampaignError(f"{gate_id}:GATE_FILE_MISSING")
    data = load_json(path)
    if data.get("schema_version") != "1.0" or data.get("gate_id") != gate_id:
        raise CampaignError(f"{gate_id}:GATE_IDENTITY_MISMATCH")
    if data.get("decision") != "ACCEPTED":
        raise CampaignError(f"{gate_id}:DECISION_NOT_ACCEPTED")
    if not str(data.get("accepted_by") or "").strip():
        raise CampaignError(f"{gate_id}:ACCEPTED_BY_REQUIRED")
    if not str(data.get("accepted_at") or "").strip():
        raise CampaignError(f"{gate_id}:ACCEPTED_AT_REQUIRED")
    validate_evidence_hashes(data, gate_id)
    return path, data


def validate_profile(path: Path, *, require_production: bool) -> dict[str, Any]:
    data = load_json(path)
    if data.get("schema_version") != "1.0":
        raise CampaignError("PROFILE_SCHEMA_MISMATCH")
    if require_production and data.get("profile_status") != PROFILE_READY:
        raise CampaignError(
            f"PROFILE_NOT_VERIFIED_FOR_PRODUCTION:{data.get('profile_status')}"
        )
    slurm = data.get("slurm")
    resources = data.get("resources")
    runtime = data.get("runtime")
    defaults = data.get("task_defaults")
    if not all(isinstance(item, dict) for item in (slurm, resources, runtime, defaults)):
        raise CampaignError("PROFILE_SECTIONS_REQUIRED")
    for field in ("partition", "account", "qos"):
        directive(slurm.get(field), f"slurm.{field}")
    for field in ("nodes", "total_cpus"):
        positive_int(resources.get(field), f"resources.{field}")
    directive(resources.get("memory"), "resources.memory")
    walltime = directive(resources.get("walltime"), "resources.walltime")
    if not re.fullmatch(r"\d{1,3}:\d{2}:\d{2}", walltime):
        raise CampaignError("INVALID_WALLTIME")
    positive_int(defaults.get("mpi_processes"), "task_defaults.mpi_processes")
    positive_int(defaults.get("cpus_per_process"), "task_defaults.cpus_per_process")
    positive_int(defaults.get("max_attempts"), "task_defaults.max_attempts")
    estimate = float(defaults.get("estimated_runtime_seconds", 0))
    if estimate <= 0:
        raise CampaignError("INVALID_RUNTIME_ESTIMATE")
    modules = runtime.get("module_commands", [])
    if not isinstance(modules, list) or any(
        not isinstance(item, str) or not SAFE_MODULE.fullmatch(item) for item in modules
    ):
        raise CampaignError("UNSAFE_MODULE_COMMAND")
    if require_production:
        validate_evidence_hashes(data, "SITE_PROFILE")
    return data


def directive(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or text.upper().startswith(("CONFIGURE", "MISSING", "REQUIRED")):
        raise CampaignError(f"EXPLICIT_CONFIGURATION_REQUIRED:{field}")
    if not SAFE_DIRECTIVE.fullmatch(text):
        raise CampaignError(f"UNSAFE_SLURM_VALUE:{field}")
    return text


def positive_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CampaignError(f"POSITIVE_INTEGER_REQUIRED:{field}") from exc
    if result <= 0:
        raise CampaignError(f"POSITIVE_INTEGER_REQUIRED:{field}")
    return result


def verify_pseudos(root: Path | None = None) -> dict[str, str]:
    selected = root or ROOT / "external/pseudopotentials"
    found: dict[str, str] = {}
    for name, expected in PSEUDO_HASHES.items():
        path = selected / name
        if not path.is_file():
            raise CampaignError(f"PSEUDOPOTENTIAL_MISSING:{name}")
        actual = sha256(path)
        if actual != expected:
            raise CampaignError(f"PSEUDOPOTENTIAL_HASH_MISMATCH:{name}:{actual}")
        found[name] = actual
    return found


def replace_unique(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.I | re.M)
    if count != 1:
        raise CampaignError(f"FDF_UNIQUE_REPLACEMENT_FAILED:{label}:{count}")
    return updated


def materialize_fdf(base: str, variant: dict[str, Any], gate: dict[str, Any]) -> str:
    label = str(variant["system_label"])
    mesh = variant.get("mesh_ry")
    if mesh is None:
        mesh = gate.get("selected_mesh_ry")
    try:
        mesh_value = int(mesh)
    except (TypeError, ValueError) as exc:
        raise CampaignError(f"INVALID_OR_UNAPPROVED_MESH:{mesh}") from exc
    if mesh_value not in {200, 250, 300, 350}:
        raise CampaignError(f"INVALID_OR_UNAPPROVED_MESH:{mesh}")
    kgrid = variant.get("kgrid")
    if (
        not isinstance(kgrid, list)
        or len(kgrid) != 3
        or any(int(value) <= 0 for value in kgrid)
        or int(kgrid[2]) != 1
    ):
        raise CampaignError(f"INVALID_KGRID:{kgrid}")
    text = replace_unique(
        base, r"^\s*SystemLabel\s+\S+\s*$", f"SystemLabel {label}", "SystemLabel"
    )
    text = replace_unique(
        text,
        r"^\s*Mesh\.Cutoff\s+[0-9.eEdD+-]+\s+Ry\s*$",
        f"Mesh.Cutoff {mesh_value} Ry",
        "Mesh.Cutoff",
    )
    block = (
        "%block kgrid.MonkhorstPack\n"
        f"  {int(kgrid[0])} 0 0 0.0\n"
        f"  0 {int(kgrid[1])} 0 0.0\n"
        "  0 0 1 0.0\n"
        "%endblock kgrid.MonkhorstPack"
    )
    text = replace_unique(
        text,
        r"(?s:%block\s+kgrid\.MonkhorstPack.*?%endblock\s+kgrid\.MonkhorstPack)",
        block,
        "kgrid.MonkhorstPack",
    )
    if not re.search(r"^\s*MD\.Steps\s+0\s*$", text, re.I | re.M):
        raise CampaignError("FDF_SANITY_REQUIRES_MD_STEPS_ZERO")
    if not re.search(r"^\s*NetCharge\s+0\s*$", text, re.I | re.M):
        raise CampaignError("FDF_SANITY_REQUIRES_NET_CHARGE_ZERO")
    provenance = (
        f"# generated_phase_variant={variant['task_id']}\n"
        f"# generated_at={datetime.now(timezone.utc).isoformat()}\n"
        "# generation_policy=base_hash_plus_gate_hash_fail_closed\n"
    )
    return provenance + text


def selected_variants(phase: dict[str, Any], gate: dict[str, Any]) -> list[dict[str, Any]]:
    variants = phase.get("variants")
    if not isinstance(variants, list) or not variants:
        raise CampaignError("PHASE_VARIANTS_REQUIRED")
    selected = [dict(item) for item in variants if isinstance(item, dict)]
    optional = phase.get("optional_variant")
    if isinstance(optional, dict):
        field = optional.get("requires_explicit_gate_field")
        if field and gate.get(str(field)) is True:
            selected.append(dict(optional))
    ids = [str(item.get("task_id")) for item in selected]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise CampaignError("INVALID_OR_DUPLICATE_TASK_ID")
    return selected


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def render_slurm(
    phase: dict[str, Any],
    profile: dict[str, Any],
    profile_relative: str,
) -> str:
    slurm = profile["slurm"]
    resources = profile["resources"]
    modules = profile["runtime"].get("module_commands", [])
    module_text = "\n".join(modules) if modules else ": # no module commands configured"
    job_name = re.sub(r"[^A-Za-z0-9_-]", "_", str(phase["campaign_id"]))[:64]
    phase_id = str(phase["phase_id"])
    return f"""#!/usr/bin/env bash
# Generated for inspection. This file never submits itself.
# Profile status at generation: {profile.get("profile_status")}
#SBATCH --job-name={job_name}
#SBATCH --partition={directive(slurm["partition"], "partition")}
#SBATCH --account={directive(slurm["account"], "account")}
#SBATCH --qos={directive(slurm["qos"], "qos")}
#SBATCH --nodes={positive_int(resources["nodes"], "nodes")}
#SBATCH --ntasks={positive_int(resources["total_cpus"], "total_cpus")}
#SBATCH --cpus-per-task=1
#SBATCH --mem={directive(resources["memory"], "memory")}
#SBATCH --time={directive(resources["walltime"], "walltime")}
#SBATCH --signal=B:USR1@{positive_int(resources["shutdown_margin_seconds"], "shutdown_margin_seconds")}
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err
set -euo pipefail
[[ -n "${{SLURM_SUBMIT_DIR:-}}" ]] || {{ echo SLURM_SUBMIT_DIR_NOT_SET >&2; exit 2; }}
PHASE_ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
PACKAGE_ROOT=$(cd "$PHASE_ROOT/../.." && pwd -P)
[[ "$PHASE_ROOT" = "$PACKAGE_ROOT/generated/{phase_id}" ]] || {{ echo INVALID_PHASE_ROOT >&2; exit 2; }}
cd "$PHASE_ROOT"
{module_text}
export PYTHONPATH="$PACKAGE_ROOT/runtime"
export PYTHONDONTWRITEBYTECODE=1
python3 "$PACKAGE_ROOT/verify_package.py"
python3 "$PACKAGE_ROOT/scripts/campaignctl.py" check-run --phase {phase_id} --profile "$PACKAGE_ROOT/{profile_relative}" --prepared-root "$PHASE_ROOT"
exec python3 "$PACKAGE_ROOT/scripts/run_phase.py" "$PHASE_ROOT/controller.json" "$PHASE_ROOT"
"""


def prepare(phase_id: str, profile_path: Path) -> dict[str, Any]:
    phase_file = phase_path(phase_id)
    phase = load_json(phase_file)
    if phase.get("status") not in PREPARABLE:
        raise CampaignError(f"PHASE_BLOCKED_BY_DESIGN:{phase.get('status')}:{phase.get('reason')}")
    required_gate = str(phase.get("required_gate") or "")
    gate_file, gate = validate_gate(required_gate)
    profile_path = profile_path.resolve()
    try:
        profile_relative = profile_path.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise CampaignError("PROFILE_MUST_LIVE_INSIDE_PACKAGE") from exc
    profile = validate_profile(profile_path, require_production=False)
    verify_pseudos()
    if sha256(BASE_FDF) != BASE_FDF_SHA256:
        raise CampaignError("BASE_FDF_HASH_MISMATCH")

    destination = ROOT / "generated" / phase_id
    if destination.exists():
        raise CampaignError(f"PREPARED_PHASE_ALREADY_EXISTS:{destination}")
    temporary = ROOT / "generated" / f".{phase_id}.{os.getpid()}.tmp"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        input_dir = temporary / "input"
        pseudo_dir = temporary / "pseudopotentials"
        input_dir.mkdir()
        pseudo_dir.mkdir()
        for name in PSEUDO_HASHES:
            shutil.copy2(ROOT / "external/pseudopotentials" / name, pseudo_dir / name)
        base = BASE_FDF.read_text(encoding="utf-8")
        tasks: list[dict[str, Any]] = []
        defaults = profile["task_defaults"]
        for variant in selected_variants(phase, gate):
            fdf_name = f"{variant['task_id']}.fdf"
            fdf_path = input_dir / fdf_name
            atomic_write(fdf_path, materialize_fdf(base, variant, gate))
            hashes = {
                f"input/{fdf_name}": sha256(fdf_path),
                "pseudopotentials/Mn.psml": PSEUDO_HASHES["Mn.psml"],
                "pseudopotentials/O.psml": PSEUDO_HASHES["O.psml"],
            }
            tasks.append(
                {
                    "task_id": variant["task_id"],
                    "input": f"input/{fdf_name}",
                    "input_hashes": hashes,
                    "required_artifacts": list(phase.get("required_artifacts", [])),
                    "mpi_processes": positive_int(
                        defaults["mpi_processes"], "task_defaults.mpi_processes"
                    ),
                    "cpus_per_process": positive_int(
                        defaults["cpus_per_process"], "task_defaults.cpus_per_process"
                    ),
                    "estimated_runtime_seconds": float(
                        defaults["estimated_runtime_seconds"]
                    ),
                    "max_attempts": positive_int(
                        defaults["max_attempts"], "task_defaults.max_attempts"
                    ),
                    "require_scf_converged": bool(
                        defaults.get("require_scf_converged", True)
                    ),
                }
            )
        runtime = dict(profile["runtime"])
        runtime.pop("module_commands", None)
        runtime.pop("required_siesta_version", None)
        controller = {
            "schema_version": "1.0",
            "campaign_id": phase["campaign_id"],
            "system_id": phase["system_id"],
            "slurm": profile["slurm"],
            "resources": profile["resources"],
            "runtime": runtime,
            "tasks": tasks,
        }
        atomic_write(temporary / "controller.json", json_text(controller))
        guard = {
            "schema_version": "1.0",
            "phase_id": phase_id,
            "profile": profile_relative,
            "phase_sha256": sha256(phase_file),
            "profile_sha256": sha256(profile_path),
            "gate": required_gate,
            "gate_sha256": sha256(gate_file),
            "base_fdf_sha256": BASE_FDF_SHA256,
            "pseudopotential_sha256": PSEUDO_HASHES,
            "profile_status_at_generation": profile.get("profile_status"),
        }
        atomic_write(temporary / "launch_guard.json", json_text(guard))
        atomic_write(
            temporary / "submit.slurm",
            render_slurm(phase, profile, profile_relative),
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "status": (
            "PREPARED_FOR_MANUAL_SUBMISSION"
            if profile.get("profile_status") == PROFILE_READY
            else "PREPARED_FOR_INSPECTION_PROFILE_STILL_BLOCKED"
        ),
        "phase_id": phase_id,
        "tasks": len(tasks),
        "destination": str(destination),
        "submit_file": str(destination / "submit.slurm"),
    }


def check_run(phase_id: str, profile_path: Path, prepared_root: Path) -> dict[str, Any]:
    profile_path = profile_path.resolve()
    profile = validate_profile(profile_path, require_production=True)
    phase_file = phase_path(phase_id)
    phase = load_json(phase_file)
    gate_file, _ = validate_gate(str(phase.get("required_gate")))
    guard = load_json(prepared_root / "launch_guard.json")
    required = {
        "phase_id": phase_id,
        "phase_sha256": sha256(phase_file),
        "profile_sha256": sha256(profile_path),
        "gate_sha256": sha256(gate_file),
        "base_fdf_sha256": BASE_FDF_SHA256,
    }
    for field, expected in required.items():
        if guard.get(field) != expected:
            raise CampaignError(f"LAUNCH_GUARD_MISMATCH:{field}")
    if guard.get("profile_status_at_generation") != PROFILE_READY:
        raise CampaignError("PHASE_MUST_BE_REPREPARED_WITH_VERIFIED_PROFILE")
    verify_pseudos(prepared_root / "pseudopotentials")
    sys.path.insert(0, str(ROOT / "runtime"))
    from siestaflow.execution.allocation_controller import load_controller_config

    config = load_controller_config(prepared_root / "controller.json")
    if config.total_cpus != int(profile["resources"]["total_cpus"]):
        raise CampaignError("CONTROLLER_PROFILE_CPU_MISMATCH")
    return {
        "status": "RUN_GUARDS_PASS",
        "phase_id": phase_id,
        "tasks": len(config.tasks),
    }


def xyz_count(path: Path, expected: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or int(lines[0]) != expected or len(lines) != expected + 2:
        raise CampaignError(f"XYZ_ATOM_COUNT_MISMATCH:{path.name}")


def verify(with_external: bool) -> dict[str, Any]:
    if not BASE_FDF.is_file() or sha256(BASE_FDF) != BASE_FDF_SHA256:
        raise CampaignError("BASE_FDF_HASH_MISMATCH")
    text = BASE_FDF.read_text(encoding="utf-8")
    required_patterns = {
        "54 atoms": r"^\s*NumberOfAtoms\s+54\s*$",
        "VDW": r"^\s*XC\.Functional\s+VDW\s*$",
        "LMKLL": r"^\s*XC\.Authors\s+LMKLL\s*$",
        "charge zero": r"^\s*NetCharge\s+0\s*$",
        "zero geometry steps": r"^\s*MD\.Steps\s+0\s*$",
    }
    for name, pattern in required_patterns.items():
        if not re.search(pattern, text, re.I | re.M):
            raise CampaignError(f"BASE_FDF_POLICY_MISMATCH:{name}")
    graph = load_json(ROOT / "campaign_graph.json")
    graph_ids = [str(item["id"]) for item in graph.get("phases", [])]
    file_ids = sorted(path.stem for path in (ROOT / "campaigns").glob("*.json"))
    if sorted(graph_ids) != file_ids:
        raise CampaignError("CAMPAIGN_GRAPH_COVERAGE_MISMATCH")
    for phase_id in file_ids:
        data = load_json(phase_path(phase_id))
        if data.get("phase_id") != phase_id:
            raise CampaignError(f"PHASE_ID_MISMATCH:{phase_id}")
    xyz_count(ROOT / "geometry/seeds/M1_delta_MnO2_neutral_surface_control_v01.xyz", 54)
    xyz_count(ROOT / "geometry/seeds/ADSORB_M1_Ca8w_OS_v01.xyz", 79)
    xyz_count(ROOT / "geometry/seeds/ADSORB_M1_Mg6w_OS_v01.xyz", 73)
    if with_external:
        verify_pseudos()
    return {
        "status": "PACKAGE_SCIENTIFIC_STRUCTURE_VERIFIED",
        "base_fdf_sha256": BASE_FDF_SHA256,
        "phases": len(file_ids),
        "external_pseudopotentials_verified": with_external,
    }


def phase_status() -> dict[str, Any]:
    statuses = []
    for path in sorted((ROOT / "campaigns").glob("*.json")):
        phase = load_json(path)
        status = str(phase.get("status"))
        reasons: list[str] = []
        gate_ids = phase.get("required_gates")
        if not isinstance(gate_ids, list):
            gate_ids = [phase.get("required_gate")] if phase.get("required_gate") else []
        for gate_id in gate_ids:
            try:
                validate_gate(str(gate_id))
            except (CampaignError, OSError) as exc:
                reasons.append(str(exc))
        if status not in PREPARABLE:
            reasons.insert(0, str(phase.get("reason") or status))
        statuses.append(
            {
                "phase_id": phase["phase_id"],
                "design_status": status,
                "ready_now": status in PREPARABLE and not reasons,
                "blocking_reasons": reasons,
            }
        )
    try:
        verify_pseudos()
        pseudos = "VERIFIED"
    except CampaignError as exc:
        pseudos = str(exc)
    return {"package_id": ROOT.name, "pseudopotentials": pseudos, "phases": statuses}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--with-external", action="store_true")
    sub.add_parser("status")
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--phase", required=True)
    prepare_cmd.add_argument("--profile", required=True, type=Path)
    check_cmd = sub.add_parser("check-run")
    check_cmd.add_argument("--phase", required=True)
    check_cmd.add_argument("--profile", required=True, type=Path)
    check_cmd.add_argument("--prepared-root", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "verify":
            result = verify(args.with_external)
        elif args.command == "status":
            result = phase_status()
        elif args.command == "prepare":
            result = prepare(args.phase, args.profile)
        elif args.command == "check-run":
            result = check_run(args.phase, args.profile, args.prepared_root.resolve())
        else:  # pragma: no cover
            raise CampaignError("UNKNOWN_COMMAND")
    except (CampaignError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json_text(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
