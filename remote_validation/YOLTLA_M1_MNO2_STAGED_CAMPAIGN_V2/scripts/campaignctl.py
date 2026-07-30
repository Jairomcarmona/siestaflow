#!/usr/bin/env python3
"""Fail-closed V2 materializer for phases and allocation bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "runtime"))
import profilectl
from siestaflow.execution.time_utils import canonical_slurm_walltime

PACKAGE_ID = "YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V2"
BASE_FDF = ROOT / "inputs/base/M1_U0_FM.pilot.NO_PRODUCTION.fdf"
BASE_FDF_SHA256 = "714d16dabd1732f0d21ac8d7947abc2d00748fce509b1a052e3e31c2c9ebc35c"
PSEUDO_HASHES = {
    "Mn.psml": "0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6",
    "O.psml": "224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e",
}
PREPARABLE = {
    "PREPARED",
    "PREPARED_DYNAMIC",
    "PREPARED_TECHNICAL_CALIBRATION",
    "PREPARED_WITH_AUTOMATIC_TECHNICAL_TRANSITION",
}
PROFILE_READY = "VERIFIED_FOR_PRODUCTION"


class CampaignError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"INVALID_JSON:{path}:{exc}") from exc
    if not isinstance(data, dict):
        raise CampaignError(f"JSON_OBJECT_REQUIRED:{path}")
    return data


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def safe_relative(value: str) -> Path:
    posix = PurePosixPath(str(value).replace("\\", "/"))
    if not value or posix.is_absolute() or ".." in posix.parts:
        raise CampaignError(f"UNSAFE_RELATIVE_PATH:{value}")
    return Path(*posix.parts)


def definition(identifier: str) -> tuple[str, Path, dict[str, Any]]:
    bundle = ROOT / "bundles" / f"{identifier}.json"
    phase = ROOT / "campaigns" / f"{identifier}.json"
    if bundle.is_file():
        return "bundle", bundle, load_json(bundle)
    if phase.is_file():
        return "phase", phase, load_json(phase)
    raise CampaignError(f"UNKNOWN_PHASE_OR_BUNDLE:{identifier}")


def gate_ids(data: dict[str, Any]) -> list[str]:
    values = data.get("required_gates")
    if values is None:
        values = [data.get("required_gate")] if data.get("required_gate") else []
    if not isinstance(values, list) or not values:
        raise CampaignError("AT_LEAST_ONE_REQUIRED_GATE_REQUIRED")
    return [str(item) for item in values]


def validate_gate(
    gate_id: str,
    *,
    identifier: str | None = None,
    profile_relative: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    path = ROOT / "gates/decisions" / f"{gate_id}.json"
    if not path.is_file():
        raise CampaignError(f"{gate_id}:GATE_FILE_MISSING")
    gate = load_json(path)
    if gate.get("schema_version") != "1.0" or gate.get("gate_id") != gate_id:
        raise CampaignError(f"{gate_id}:GATE_IDENTITY_MISMATCH")
    if gate.get("decision") != "ACCEPTED":
        raise CampaignError(f"{gate_id}:DECISION_NOT_ACCEPTED")
    if not str(gate.get("accepted_by") or "").strip() or not str(
        gate.get("accepted_at") or ""
    ).strip():
        raise CampaignError(f"{gate_id}:EXPLICIT_ACCEPTANCE_METADATA_REQUIRED")
    evidence = gate.get("evidence_sha256")
    if not isinstance(evidence, dict) or not evidence:
        raise CampaignError(f"{gate_id}:EVIDENCE_HASHES_REQUIRED")
    for name, expected in evidence.items():
        target = ROOT / safe_relative(str(name))
        if not target.is_file():
            raise CampaignError(f"{gate_id}:MISSING_EVIDENCE:{name}")
        if sha256(target) != str(expected).lower():
            raise CampaignError(f"{gate_id}:EVIDENCE_HASH_MISMATCH:{name}")
    if gate_id == "F0_EXECUTION_AUTHORIZATION" and identifier is not None:
        scope = gate.get("authorized_scope")
        authorized = (
            identifier in scope
            if isinstance(scope, list)
            else str(scope or "") == identifier
        )
        if not authorized:
            raise CampaignError(f"{gate_id}:SCOPE_DOES_NOT_AUTHORIZE:{identifier}")
        if not str(gate.get("output_directory") or "").strip():
            raise CampaignError(f"{gate_id}:OUTPUT_DIRECTORY_REQUIRED")
        required_evidence = {
            "inputs/base/M1_U0_FM.pilot.NO_PRODUCTION.fdf",
            "external/pseudopotentials/Mn.psml",
            "external/pseudopotentials/O.psml",
            "scripts/runtime_preflight.py",
            "scripts/profilectl.py",
        }
        if profile_relative:
            required_evidence.add(profile_relative)
        if not required_evidence <= set(map(str, evidence)):
            missing = sorted(required_evidence - set(map(str, evidence)))
            raise CampaignError(f"{gate_id}:REQUIRED_BINDING_MISSING:{missing}")
    return path, gate


def verify_pseudos(root: Path | None = None) -> dict[str, str]:
    source = root or ROOT / "external/pseudopotentials"
    found: dict[str, str] = {}
    for name, expected in PSEUDO_HASHES.items():
        path = source / name
        if not path.is_file():
            raise CampaignError(f"PSEUDOPOTENTIAL_MISSING:{name}")
        actual = sha256(path)
        if actual != expected:
            raise CampaignError(
                f"PSEUDOPOTENTIAL_HASH_MISMATCH:{name}:expected={expected}:actual={actual}"
            )
        found[name] = actual
    return found


def replace_unique(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.I | re.M)
    if count != 1:
        raise CampaignError(f"FDF_UNIQUE_REPLACEMENT_FAILED:{label}:{count}")
    return updated


def materialize_fdf(base: str, task: dict[str, Any], gate_map: dict[str, Any]) -> str:
    stripped = re.sub(
        r"^# (?:generated_phase_variant|generation_policy|source_base_sha256)=.*\n",
        "",
        base,
        flags=re.M,
    )
    mesh: Any = task.get("mesh_ry")
    if mesh is None:
        mesh = gate_map.get("selected_mesh_ry")
    try:
        mesh_value = int(mesh)
    except (TypeError, ValueError) as exc:
        raise CampaignError(f"INVALID_OR_UNAPPROVED_MESH:{mesh}") from exc
    if mesh_value not in {200, 250, 300, 350}:
        raise CampaignError(f"INVALID_OR_UNAPPROVED_MESH:{mesh_value}")
    kgrid = task.get("kgrid")
    if (
        not isinstance(kgrid, list)
        or len(kgrid) != 3
        or any(int(value) <= 0 for value in kgrid)
        or int(kgrid[2]) != 1
    ):
        raise CampaignError(f"INVALID_KGRID:{kgrid}")
    text = replace_unique(
        stripped,
        r"^\s*SystemLabel\s+\S+\s*$",
        f"SystemLabel {task['system_label']}",
        "SystemLabel",
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
    for pattern, message in (
        (r"^\s*MD\.Steps\s+0\s*$", "FDF_REQUIRES_MD_STEPS_ZERO"),
        (r"^\s*NetCharge\s+0\s*$", "FDF_REQUIRES_NET_CHARGE_ZERO"),
    ):
        if not re.search(pattern, text, re.I | re.M):
            raise CampaignError(message)
    provenance = (
        f"# generated_phase_variant={task['task_id']}\n"
        "# generation_policy=base_hash_plus_gate_hash_fail_closed\n"
        f"# source_base_sha256={BASE_FDF_SHA256}\n"
    )
    result = provenance + text
    if result.count("# generation_policy=") != 1:
        raise CampaignError("FDF_GENERATION_POLICY_NOT_UNIQUE")
    return result


def task_definitions(kind: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("tasks" if kind == "bundle" else "variants")
    if not isinstance(raw, list) or not raw:
        raise CampaignError("TASK_DEFINITIONS_REQUIRED")
    tasks = [dict(item) for item in raw if isinstance(item, dict)]
    if len(tasks) != len(raw):
        raise CampaignError("TASK_DEFINITION_MUST_BE_OBJECT")
    ids = [str(item.get("task_id") or "") for item in tasks]
    if any(not item or "/" in item or "\\" in item for item in ids) or len(ids) != len(
        set(ids)
    ):
        raise CampaignError("INVALID_OR_DUPLICATE_TASK_ID")
    return tasks


def module_lines(profile: dict[str, Any]) -> list[str]:
    modules = profilectl._structured_modules(profile.get("modules"))
    lines = ["module purge"] if modules["purge"] else []
    lines.extend(f"module load {item}" for item in modules["load"])
    return lines


def memory_directive(resources: dict[str, Any]) -> str:
    policy = resources["memory_policy"]
    if policy["mode"] == "partition_default":
        return "# Memory request intentionally omitted: partition_default policy."
    return f"#SBATCH --mem={int(policy['value'])}M"


def render_submit(
    identifier: str, data: dict[str, Any], profile: dict[str, Any], profile_relative: str
) -> str:
    slurm = profile["slurm"]
    resources = profile["resources"]
    modules = "\n".join(module_lines(profile))
    job = re.sub(r"[^A-Za-z0-9_-]", "_", str(data["campaign_id"]))[:64]
    return f"""#!/usr/bin/env bash
# Generated for explicit review and manual submission only.
# automatic_submission=false
#SBATCH --job-name={job}
#SBATCH --partition={slurm['partition']}
#SBATCH --account={slurm['account']}
#SBATCH --qos={slurm['qos']}
#SBATCH --nodes={resources['nodes']}
#SBATCH --ntasks={resources['total_cpus']}
#SBATCH --ntasks-per-node={resources['tasks_per_node']}
#SBATCH --cpus-per-task=1
{memory_directive(resources)}
#SBATCH --time={canonical_slurm_walltime(resources['walltime'])}
#SBATCH --signal=B:USR1@{int(resources['shutdown_margin_seconds'])}
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err
set -euo pipefail
[[ -n "${{SLURM_SUBMIT_DIR:-}}" ]] || {{ echo SLURM_SUBMIT_DIR_NOT_SET >&2; exit 2; }}
RUN_ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
PACKAGE_ROOT=$(cd "$RUN_ROOT/../.." && pwd -P)
[[ "$RUN_ROOT" = "$PACKAGE_ROOT/generated/{identifier}" ]] || {{ echo INVALID_RUN_ROOT >&2; exit 2; }}
cd "$RUN_ROOT"
{modules}
export PYTHONPATH="$PACKAGE_ROOT/runtime"
export PYTHONDONTWRITEBYTECODE=1
python3 "$PACKAGE_ROOT/verify_package.py"
python3 "$PACKAGE_ROOT/scripts/campaignctl.py" check-run --phase-or-bundle {identifier} --profile "$PACKAGE_ROOT/{profile_relative}" --prepared-root "$RUN_ROOT"
python3 "$PACKAGE_ROOT/scripts/runtime_preflight.py" --profile "$PACKAGE_ROOT/{profile_relative}" --prepared-root "$RUN_ROOT"
exec python3 "$PACKAGE_ROOT/scripts/run_phase.py" "$RUN_ROOT/controller.json" "$RUN_ROOT"
"""


def render_login_preflight(identifier: str, profile_relative: str) -> str:
    return f"""#!/usr/bin/env bash
# Login-node checks only; does not prove runtime launcher compatibility.
set -euo pipefail
RUN_ROOT=$(cd "$(dirname "$0")" && pwd -P)
PACKAGE_ROOT=$(cd "$RUN_ROOT/../.." && pwd -P)
cd "$PACKAGE_ROOT"
{chr(10).join(module_lines(profilectl.validate(ROOT / profile_relative)))}
python3 verify_package.py
python3 scripts/profilectl.py validate --production "{profile_relative}"
python3 scripts/profilectl.py check-version --executable siesta --required 5.4.2
python3 scripts/campaignctl.py check-run --phase-or-bundle "{identifier}" --profile "{profile_relative}" --prepared-root "generated/{identifier}"
sbatch --test-only "generated/{identifier}/submit.slurm"
echo LOGIN_PREFLIGHT_AND_SBATCH_TEST_ONLY_PASS
echo RUNTIME_PREFLIGHT_STILL_REQUIRED_INSIDE_ALLOCATION
"""


def prepare(identifier: str, profile_path: Path) -> dict[str, Any]:
    kind, source_path, data = definition(identifier)
    if data.get("status") not in PREPARABLE:
        raise CampaignError(
            f"DEFINITION_BLOCKED_BY_DESIGN:{data.get('status')}:{data.get('reason')}"
        )
    try:
        profile_relative = profile_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise CampaignError("PROFILE_MUST_LIVE_INSIDE_PACKAGE") from exc
    if not profile_relative.startswith("site/profiles/"):
        raise CampaignError("DERIVED_PROFILE_MUST_LIVE_UNDER_SITE_PROFILES")
    try:
        profile = profilectl.validate(profile_path.resolve())
    except profilectl.ProfileError as exc:
        raise CampaignError(str(exc)) from exc
    gates: dict[str, tuple[Path, dict[str, Any]]] = {
        gate_id: validate_gate(
            gate_id, identifier=identifier, profile_relative=profile_relative
        )
        for gate_id in gate_ids(data)
    }
    gate_values: dict[str, Any] = {}
    for _, gate in gates.values():
        gate_values.update(gate)
    verify_pseudos()
    if sha256(BASE_FDF) != BASE_FDF_SHA256:
        raise CampaignError("BASE_FDF_HASH_MISMATCH")
    tasks_raw = task_definitions(kind, data)
    layout_name = profile["resource_layouts"]["selected"]
    layout = profile["resource_layouts"]["available"][layout_name]
    destination = ROOT / "generated" / identifier
    if destination.exists():
        raise CampaignError(f"PREPARED_DESTINATION_ALREADY_EXISTS:{destination}")
    temporary = destination.parent / f".{identifier}.{os.getpid()}.tmp"
    temporary.mkdir(parents=True, exist_ok=False)
    tasks: list[dict[str, Any]] = []
    try:
        (temporary / "input").mkdir()
        (temporary / "pseudopotentials").mkdir()
        for name in PSEUDO_HASHES:
            shutil.copy2(
                ROOT / "external/pseudopotentials" / name,
                temporary / "pseudopotentials" / name,
            )
        base = BASE_FDF.read_text(encoding="utf-8")
        defaults = profile["task_defaults"]
        for item in tasks_raw:
            fdf_name = f"{item['task_id']}.fdf"
            fdf_path = temporary / "input" / fdf_name
            atomic_write(fdf_path, materialize_fdf(base, item, gate_values))
            mpi = int(item.get("mpi_processes", layout["mpi_processes_per_step"]))
            nodes_required = int(item.get("nodes_required", layout["nodes_per_step"]))
            tasks.append(
                {
                    "task_id": item["task_id"],
                    "input": f"input/{fdf_name}",
                    "input_hashes": {
                        f"input/{fdf_name}": sha256(fdf_path),
                        "pseudopotentials/Mn.psml": PSEUDO_HASHES["Mn.psml"],
                        "pseudopotentials/O.psml": PSEUDO_HASHES["O.psml"],
                    },
                    "required_artifacts": list(data.get("required_artifacts", [])),
                    "mpi_processes": mpi,
                    "cpus_per_process": int(defaults["cpus_per_process"]),
                    "nodes_required": nodes_required,
                    "estimated_runtime_seconds": float(
                        defaults["estimated_runtime_seconds"]
                    ),
                    "max_attempts": int(defaults["max_attempts"]),
                    "retry_backoff_seconds": float(
                        defaults.get("retry_backoff_seconds", 0)
                    ),
                    "retryable_exit_codes": list(
                        defaults.get("retryable_exit_codes", [])
                    ),
                    "require_scf_converged": bool(
                        defaults.get("require_scf_converged", True)
                    ),
                    "depends_on": list(item.get("depends_on", [])),
                    "postcondition": item.get("postcondition"),
                }
            )
        resources = dict(profile["resources"])
        resources["max_parallel_steps"] = int(layout["max_parallel_steps"])
        controller = {
            "schema_version": "2.0",
            "campaign_id": data["campaign_id"],
            "system_id": data["system_id"],
            "slurm": dict(profile["slurm"]),
            "resources": resources,
            "runtime": dict(profile["runtime"]),
            "failure_policy": "continue_independent",
            "tasks": tasks,
        }
        atomic_write(temporary / "controller.json", json_text(controller))
        guard = {
            "schema_version": "2.0",
            "package_id": PACKAGE_ID,
            "definition_kind": kind,
            "identifier": identifier,
            "definition_sha256": sha256(source_path),
            "profile": profile_relative,
            "profile_sha256": sha256(profile_path),
            "gate_sha256": {
                gate_id: sha256(path) for gate_id, (path, _) in gates.items()
            },
            "base_fdf_sha256": BASE_FDF_SHA256,
            "pseudopotential_sha256": PSEUDO_HASHES,
            "profile_status_at_generation": profile.get("profile_status"),
            "resource_layout": layout_name,
        }
        atomic_write(temporary / "launch_guard.json", json_text(guard))
        atomic_write(
            temporary / "submit.slurm",
            render_submit(identifier, data, profile, profile_relative),
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, destination)
        atomic_write(
            destination / "login_preflight.sh",
            render_login_preflight(identifier, profile_relative),
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    ready = profile.get("profile_status") == PROFILE_READY
    return {
        "status": (
            "PREPARED_FOR_MANUAL_SBATCH_TEST_ONLY"
            if ready
            else "PREPARED_FOR_INSPECTION_PROFILE_NOT_PRODUCTION"
        ),
        "identifier": identifier,
        "kind": kind,
        "tasks": len(tasks),
        "resource_layout": layout_name,
        "destination": str(destination),
        "automatic_submission": False,
    }


def check_run(identifier: str, profile_path: Path, prepared_root: Path) -> dict[str, Any]:
    kind, source_path, data = definition(identifier)
    try:
        profile = profilectl.validate(profile_path.resolve(), production=True)
    except profilectl.ProfileError as exc:
        raise CampaignError(str(exc)) from exc
    guard = load_json(prepared_root / "launch_guard.json")
    expected: dict[str, Any] = {
        "package_id": PACKAGE_ID,
        "definition_kind": kind,
        "identifier": identifier,
        "definition_sha256": sha256(source_path),
        "profile_sha256": sha256(profile_path),
        "base_fdf_sha256": BASE_FDF_SHA256,
        "profile_status_at_generation": PROFILE_READY,
        "resource_layout": profile["resource_layouts"]["selected"],
    }
    for field, value in expected.items():
        if guard.get(field) != value:
            raise CampaignError(f"LAUNCH_GUARD_MISMATCH:{field}")
    try:
        profile_relative = profile_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise CampaignError("PROFILE_MUST_LIVE_INSIDE_PACKAGE") from exc
    current_gates = {
        gate_id: sha256(
            validate_gate(
                gate_id, identifier=identifier, profile_relative=profile_relative
            )[0]
        )
        for gate_id in gate_ids(data)
    }
    if guard.get("gate_sha256") != current_gates:
        raise CampaignError("LAUNCH_GUARD_MISMATCH:gate_sha256")
    verify_pseudos(prepared_root / "pseudopotentials")
    from siestaflow.execution.allocation_controller import load_controller_config

    config = load_controller_config(prepared_root / "controller.json")
    if (
        config.total_cpus != profile["resources"]["total_cpus"]
        or config.tasks_per_node != profile["resources"]["tasks_per_node"]
        or config.required_siesta_version != "5.4.2"
    ):
        raise CampaignError("CONTROLLER_PROFILE_MISMATCH")
    return {
        "status": "RUN_GUARDS_PASS_RUNTIME_PREFLIGHT_STILL_REQUIRED",
        "identifier": identifier,
        "tasks": len(config.tasks),
    }


def xyz_count(path: Path, expected: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or int(lines[0]) != expected or len(lines) != expected + 2:
        raise CampaignError(f"XYZ_ATOM_COUNT_MISMATCH:{path.name}")


def verify(_with_external: bool = True) -> dict[str, Any]:
    if not BASE_FDF.is_file() or sha256(BASE_FDF) != BASE_FDF_SHA256:
        raise CampaignError("BASE_FDF_HASH_MISMATCH")
    text = BASE_FDF.read_text(encoding="utf-8")
    for label, pattern in {
        "54 atoms": r"^\s*NumberOfAtoms\s+54\s*$",
        "VDW": r"^\s*XC\.Functional\s+VDW\s*$",
        "LMKLL": r"^\s*XC\.Authors\s+LMKLL\s*$",
        "charge zero": r"^\s*NetCharge\s+0\s*$",
        "zero geometry steps": r"^\s*MD\.Steps\s+0\s*$",
    }.items():
        if not re.search(pattern, text, re.I | re.M):
            raise CampaignError(f"BASE_FDF_POLICY_MISMATCH:{label}")
    graph = load_json(ROOT / "campaign_graph.json")
    graph_phase_ids = sorted(
        {
            "01_sanity",
            "03a_mesh",
            "03b_kgrid",
            *map(str, graph.get("blocked_phases", {}).keys()),
        }
    )
    phase_ids = sorted(path.stem for path in (ROOT / "campaigns").glob("*.json"))
    if graph_phase_ids != phase_ids:
        raise CampaignError("CAMPAIGN_GRAPH_COVERAGE_MISMATCH")
    graph_bundle_ids = sorted(
        str(item["id"]) for item in graph.get("allocation_bundles", [])
    )
    bundle_ids = sorted(path.stem for path in (ROOT / "bundles").glob("*.json"))
    if graph_bundle_ids != bundle_ids:
        raise CampaignError("BUNDLE_GRAPH_COVERAGE_MISMATCH")
    profilectl.validate(ROOT / "profiles/yoltla_qz2d_128p.template.json")
    verify_pseudos()
    xyz_count(ROOT / "geometry/seeds/M1_delta_MnO2_neutral_surface_control_v01.xyz", 54)
    xyz_count(ROOT / "geometry/seeds/ADSORB_M1_Ca8w_OS_v01.xyz", 79)
    xyz_count(ROOT / "geometry/seeds/ADSORB_M1_Mg6w_OS_v01.xyz", 73)
    return {
        "status": "PACKAGE_SCIENTIFIC_STRUCTURE_VERIFIED",
        "package_id": PACKAGE_ID,
        "phases": len(phase_ids),
        "bundles": len(bundle_ids),
        "pseudopotentials_packaged_and_verified": True,
    }


def status() -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    for folder, kind in (("bundles", "bundle"), ("campaigns", "phase")):
        for path in sorted((ROOT / folder).glob("*.json")):
            data = load_json(path)
            reasons: list[str] = []
            if data.get("status") not in PREPARABLE:
                reasons.append(str(data.get("reason") or data.get("status")))
            try:
                for gate_id in gate_ids(data):
                    validate_gate(gate_id)
            except CampaignError as exc:
                reasons.append(str(exc))
            values.append(
                {
                    "kind": kind,
                    "identifier": path.stem,
                    "design_status": data.get("status"),
                    "ready_now": not reasons,
                    "blocking_reasons": reasons,
                }
            )
    return {
        "package_id": PACKAGE_ID,
        "pseudopotentials": verify_pseudos(),
        "definitions": values,
        "automatic_submission": False,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--with-external", action="store_true")
    sub.add_parser("status")
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--phase-or-bundle", required=True)
    prepare_cmd.add_argument("--profile", required=True, type=Path)
    check_cmd = sub.add_parser("check-run")
    check_cmd.add_argument("--phase-or-bundle", required=True)
    check_cmd.add_argument("--profile", required=True, type=Path)
    check_cmd.add_argument("--prepared-root", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "verify":
            value = verify(args.with_external)
        elif args.command == "status":
            value = status()
        elif args.command == "prepare":
            value = prepare(args.phase_or_bundle, args.profile.resolve())
        else:
            value = check_run(
                args.phase_or_bundle,
                args.profile.resolve(),
                args.prepared_root.resolve(),
            )
    except (
        CampaignError,
        profilectl.ProfileError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json_text(value), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
