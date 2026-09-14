#!/usr/bin/env python3
"""Build evidence-bound, manual-only M10 Yoltla acceptance bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
from pathlib import Path
from typing import Any, Mapping

from qraft.controller_package import ControllerPackageBuilder
from qraft.execution.allocation_controller import load_controller_config
from qraft.execution.legacy_translation import translate_controller_config
try:
    from tools.resolve_yoltla_m10_runtime import validate_runtime_compatibility
except ModuleNotFoundError:  # Direct execution places tools/, not its parent, on sys.path.
    from resolve_yoltla_m10_runtime import validate_runtime_compatibility


CAMPAIGN_ID = "QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE"
SYSTEM_ID = "SURF_Gr5x5_clean_v01_TECHNICAL_ACCEPTANCE"
CONTINUATION_CAMPAIGN_ID = "QRAFT_M10_ALLOCATION_CONTINUATION_TECHNICAL"
HISTORICAL_HINT = {
    "partition": "tt2d-64p", "account": "vini", "qos": "normal",
    "status": "HISTORICAL_ONLY_NOT_CURRENT_AUTHORITY",
}
CONTINUATION_FIRST_ALLOCATION_SECONDS = 60
CONTINUATION_SECOND_ALLOCATION_SECONDS = 180
CONTINUATION_STAGE_A_ESTIMATE_SECONDS = 5
CONTINUATION_STAGE_B_ESTIMATE_SECONDS = 90
CONTINUATION_SHUTDOWN_MARGIN_SECONDS = 10
_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _copy_linux_text(source: Path, destination: Path) -> None:
    """Materialize a Linux-targeted text file with LF line endings."""

    destination.write_bytes(source.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


def _write_linux_text(destination: Path, text: str) -> None:
    destination.write_bytes(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def _required_scheduler_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE.fullmatch(value):
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: invalid {field}")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: invalid {field}")
    return value


def _resolved_placement(selection: Mapping[str, Any]) -> dict[str, Any]:
    placement = selection.get("derived_placement")
    capacity = selection.get("capacity_evidence")
    if not isinstance(placement, Mapping) or not isinstance(capacity, Mapping):
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: capacity evidence and derived placement are required"
        )
    result = {
        field: _positive_int(placement.get(field), f"derived_placement.{field}")
        for field in (
            "nodes",
            "ntasks",
            "cpus_per_task",
            "processes_per_node",
            "total_cpus",
        )
    }
    walltime = placement.get("walltime")
    if not isinstance(walltime, str) or not walltime.strip():
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: invalid derived_placement.walltime")
    result["walltime"] = walltime
    if placement.get("policy") != "MAXIMUM_LEGAL_PLACEMENT_FIXED_PARTITION":
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: unsupported placement policy")
    if result["nodes"] * result["processes_per_node"] != result["ntasks"]:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: inconsistent derived placement")
    cpus_per_node = _positive_int(
        capacity.get("cpus_per_node"), "capacity_evidence.cpus_per_node"
    )
    if result["processes_per_node"] * result["cpus_per_task"] > cpus_per_node:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: CPU overcommit")
    if result["total_cpus"] != result["nodes"] * cpus_per_node:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: total CPU capacity mismatch")
    for field in ("nodes", "ntasks", "cpus_per_task", "processes_per_node", "walltime"):
        if selection.get(field) != result[field]:
            raise ValueError(
                f"M10_REMOTE_PROFILE_UNRESOLVED: top-level {field} disagrees with derived placement"
            )
    return result


def _load_scheduler_selection(path: Path) -> dict[str, Any]:
    """Validate the existing M3 scheduler-selection shape without a fallback."""

    if not path.is_file():
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: selection file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: selection must be an object")
    result = dict(data)
    for field in ("partition", "memory"):
        result[field] = _required_scheduler_text(result.get(field), field)
    account = result.get("account")
    if account is not None:
        result["account"] = _required_scheduler_text(account, "account")
    qos = result.get("qos")
    if qos is not None:
        result["qos"] = _required_scheduler_text(qos, "qos")
    _resolved_placement(result)
    evidence = result.get("evidence_status_by_field")
    if not isinstance(evidence, Mapping):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: missing evidence statuses")
    for field in ("account", "partition", "qos", "memory", "resource_shape"):
        if field not in evidence:
            raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: missing {field} evidence status")
    if result.get("resource_shape_status") != "DERIVED_FROM_RESOURCE_REQUEST_AND_CURRENT_CLUSTER_CAPABILITIES":
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: placement is not derived from cluster capabilities")
    if not isinstance(result.get("source_files"), list) or not result["source_files"]:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: missing scheduler source files")
    return result


def _live_placement_value(
    placement: Mapping[str, Any], legacy_field: str, live_field: str,
) -> int:
    """Read one placement value without translating live provenance to legacy."""

    value = placement.get(live_field, placement.get(legacy_field))
    return _positive_int(value, f"derived_placement.{live_field}")


def _live_node_memory(
    sources: Mapping[str, Any], partition: str, placement: Mapping[str, Any],
) -> int:
    """Bind campaign memory to homogeneous node-level live evidence."""

    capabilities = sources.get("node_capabilities")
    if not isinstance(capabilities, list):
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: live node capability evidence is missing"
        )
    by_node: dict[str, tuple[int, int]] = {}
    for item in capabilities:
        if not isinstance(item, Mapping) or item.get("partition") != partition:
            continue
        node = item.get("node")
        if not isinstance(node, str) or not node.strip():
            raise ValueError(
                "M10_REMOTE_PROFILE_UNRESOLVED: invalid live node capability name"
            )
        capacity = (
            _positive_int(item.get("cpus_per_node"), "node_capabilities.cpus_per_node"),
            _positive_int(item.get("memory_mb"), "node_capabilities.memory_mb"),
        )
        previous = by_node.get(node)
        if previous is not None and previous != capacity:
            raise ValueError(
                "M10_REMOTE_PROFILE_UNRESOLVED: contradictory live node capability evidence"
            )
        by_node[node] = capacity
    if not by_node:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: live node capability evidence is missing"
        )
    if len(by_node) < _positive_int(placement.get("nodes"), "derived_placement.nodes"):
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: live node capability evidence is insufficient"
        )
    cpu_values = {capacity[0] for capacity in by_node.values()}
    memory_values = {capacity[1] for capacity in by_node.values()}
    if len(cpu_values) != 1 or len(memory_values) != 1:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: live node capability evidence is heterogeneous"
        )
    observed_cpus = next(iter(cpu_values))
    if observed_cpus != _positive_int(
        placement.get("safe_cpus_per_node"),
        "derived_placement.safe_cpus_per_node",
    ):
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: live node CPU capacity disagrees with derived placement"
        )
    return next(iter(memory_values))


def _load_live_slurm_selection(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Mapping[str, Any]]:
    """Validate ADR-0004 provenance without resolving or recalculating placement."""

    if not path.is_file():
        raise ValueError(f"M10_REMOTE_PROFILE_UNRESOLVED: selection file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: live Slurm selection is not JSON"
        ) from error
    if not isinstance(data, dict) or data.get("authority") != "LIVE_SLURM_SELECTION_EVIDENCE":
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live Slurm selection is invalid")
    if data.get("runtime_authority_for_future_runs") is not False:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: live Slurm selection authority is invalid"
        )
    observed_at = data.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live observation time is missing")
    human = data.get("human_selection")
    resolved = data.get("resolved_selection")
    sources = data.get("sources")
    placement_value = data.get("derived_placement")
    if not all(isinstance(item, Mapping) for item in (human, resolved, sources, placement_value)):
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live Slurm selection is incomplete")
    if sources.get("authority") != "LIVE_SLURM_DISCOVERY":
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live Slurm source evidence is invalid")
    if human.get("explicit") is not True:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live partition selection is not explicit")
    partition = _required_scheduler_text(human.get("partition"), "human_selection.partition")
    if placement_value.get("partition") != partition:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: human partition disagrees with derived placement"
        )
    account_value = resolved.get("account")
    qos_value = resolved.get("qos")
    account = (
        _required_scheduler_text(account_value, "resolved_selection.account")
        if account_value is not None else None
    )
    qos = (
        _required_scheduler_text(qos_value, "resolved_selection.qos")
        if qos_value is not None else None
    )
    placement = dict(placement_value)
    for field in (
        "nodes", "tasks_per_node", "ntasks", "cpus_per_task",
        "safe_cpus_per_node", "total_allocated_cpus",
    ):
        _positive_int(placement.get(field), f"derived_placement.{field}")
    walltime = placement.get("walltime")
    if not isinstance(walltime, str) or not walltime.strip():
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: invalid derived_placement.walltime")
    if placement["ntasks"] != placement["nodes"] * placement["tasks_per_node"]:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: inconsistent live derived placement")
    if placement["tasks_per_node"] * placement["cpus_per_task"] > placement["safe_cpus_per_node"]:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live derived placement CPU overcommit")
    if placement["total_allocated_cpus"] != placement["nodes"] * placement["safe_cpus_per_node"]:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live derived placement total CPU mismatch")
    commands = sources.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("M10_REMOTE_PROFILE_UNRESOLVED: live source command evidence is missing")
    for command in commands:
        if (
            not isinstance(command, Mapping)
            or not isinstance(command.get("argv"), list)
            or command.get("returncode") != 0
            or not isinstance(command.get("stdout_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", command["stdout_sha256"])
        ):
            raise ValueError(
                "M10_REMOTE_PROFILE_UNRESOLVED: live source command evidence is invalid"
            )
    memory_mb = _live_node_memory(sources, partition, placement)
    scheduler = {
        "partition": partition,
        "account": account,
        "qos": qos,
        "memory": f"{memory_mb}M",
    }
    return scheduler, placement, dict(data), sources


def _runtime_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE.fullmatch(value):
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: invalid {field}")
    return value


def _runtime_commands(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: invalid {field}")
    return list(value)


def _hydra_bootstrap(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "M10_RUNTIME_PROFILE_UNRESOLVED: invalid launchers.hydra.bootstrap"
        )
    return value.strip()


def _load_runtime_selection(path: Path) -> dict[str, Any]:
    """Load only a reviewed, evidence-bound M10 runtime selection."""

    if not path.is_file():
        raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: selection file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: runtime selection is not JSON") from error
    if not isinstance(data, dict) or data.get("status") != "RESOLVED_FROM_CURRENT_CLUSTER_EVIDENCE":
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: runtime selection is unresolved")
    result = dict(data)
    for component in ("python", "siesta"):
        payload = result.get(component)
        if not isinstance(payload, dict):
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: missing {component} selection")
        if payload.get("selected_mechanism") not in {"PATH", "MODULE", "OTHER_EVIDENCE_BOUND"}:
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: invalid {component} mechanism")
        _runtime_text(payload.get("selected_executable"), f"{component}.selected_executable")
        if component == "python":
            _selected_python_path({"python": payload})
        _runtime_text(payload.get("observed_version"), f"{component}.observed_version")
        _runtime_commands(payload.get("environment_setup", []), f"{component}.environment_setup")
        if not payload.get("evidence_source"):
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: missing {component} evidence")
    if result["python"].get("requirement") != ">=3.11":
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: Python requirement must be >=3.11")
    launchers = result.get("launchers")
    if not isinstance(launchers, dict) or not isinstance(launchers.get("srun"), dict):
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: srun selection missing")
    for name, payload in launchers.items():
        if name not in {"srun", "hydra"} or not isinstance(payload, dict):
            raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: invalid launcher selection")
        if payload.get("required") is False and name == "hydra":
            continue
        _runtime_text(payload.get("selected_executable"), f"launchers.{name}.selected_executable")
        _runtime_commands(payload.get("arguments", []), f"launchers.{name}.arguments")
        _runtime_commands(payload.get("environment_setup", []), f"launchers.{name}.environment_setup")
        if not payload.get("evidence_source"):
            raise ValueError(f"M10_RUNTIME_PROFILE_UNRESOLVED: missing {name} evidence")
        if name == "hydra":
            _hydra_bootstrap(payload.get("bootstrap"))
            validate_runtime_compatibility(result["siesta"], payload, "Hydra")
    srun_args = result["launchers"]["srun"]["arguments"]
    placement_options = ("--nodes", "--ntasks", "--ntasks-per-node", "--cpus-per-task")
    if any(
        argument == option or argument.startswith(f"{option}=")
        for argument in srun_args for option in placement_options
    ):
        raise ValueError(
            "M10_RUNTIME_PROFILE_UNRESOLVED: runtime selection cannot carry placement"
        )
    return result


def _srun_arguments(runtime: Mapping[str, Any], placement: Mapping[str, Any]) -> list[str]:
    # Placement is carried by campaign resources -> ExecutionSpec ->
    # StepLaunchSpec.  Launcher arguments contain launcher policy only.
    del placement
    return list(runtime["launchers"]["srun"]["arguments"])


def _slurm(selection: Mapping[str, Any]) -> dict[str, str]:
    result = {"partition": str(selection["partition"])}
    if selection.get("account") is not None:
        result["account"] = str(selection["account"])
    if selection.get("qos") is not None:
        result["qos"] = str(selection["qos"])
    return result


def _fixture(repository: Path, destination: Path) -> dict[str, str]:
    source = repository / "remote_validation" / "M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE"
    (destination / "input").mkdir(parents=True)
    (destination / "pseudopotentials").mkdir()
    shutil.copy2(source / "input" / "smoke.fdf", destination / "input" / "smoke.fdf")
    shutil.copy2(source / "pseudopotentials" / "C.psml", destination / "pseudopotentials" / "C.psml")
    return {
        "input/smoke.fdf": _sha(destination / "input" / "smoke.fdf"),
        "pseudopotentials/C.psml": _sha(destination / "pseudopotentials" / "C.psml"),
    }


def _runtime_setup(runtime: Mapping[str, Any], launcher: str | None = None) -> list[str]:
    commands = [*runtime["python"]["environment_setup"], *runtime["siesta"]["environment_setup"]]
    if launcher is not None:
        commands.extend(runtime["launchers"][launcher]["environment_setup"])
    return commands


def _selected_python_path(runtime: Mapping[str, Any]) -> str:
    value = runtime["python"].get("observed_path")
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value != value.strip()
        or "\x00" in value
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError(
            "M10_RUNTIME_PROFILE_UNRESOLVED: Python observed_path must be an absolute executable path"
        )
    return value


def _siesta_campaign(
    repository: Path, selection: Mapping[str, Any], runtime: Mapping[str, Any],
    launcher: str, source: Path, *, placement: Mapping[str, Any] | None = None,
) -> Path:
    hashes = _fixture(repository, source)
    placement = _resolved_placement(selection) if placement is None else placement
    processes_per_node = _live_placement_value(
        placement, "processes_per_node", "tasks_per_node"
    )
    total_cpus = _live_placement_value(
        placement, "total_cpus", "total_allocated_cpus"
    )
    selected_launcher = runtime["launchers"][launcher]
    launcher_data: dict[str, Any] = {
        "kind": launcher, "command": [selected_launcher["selected_executable"]],
        "arguments": (
            _srun_arguments(runtime, placement)
            if launcher == "srun" else selected_launcher["arguments"]
        ),
        "processes_per_node": processes_per_node,
    }
    if launcher == "hydra":
        launcher_data["bootstrap"] = _hydra_bootstrap(selected_launcher.get("bootstrap"))
    runtime_environment = {
        "QRAFT_PYTHON": _selected_python_path(runtime),
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    campaign = {
        "schema_version": "2.0", "campaign_id": CAMPAIGN_ID, "system_id": SYSTEM_ID,
        "classification": ["NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "ENERGY_INTERPRETATION_FORBIDDEN"],
        "slurm": _slurm(selection),
        "resources": {"nodes": placement["nodes"], "total_cpus": total_cpus, "ntasks": placement["ntasks"], "cpus_per_task": placement["cpus_per_task"], "memory": selection["memory"], "walltime": placement["walltime"], "max_parallel_steps": 1, "shutdown_margin_seconds": 120, "termination_grace_seconds": 30},
        "runtime": {"module_commands": _runtime_setup(runtime, launcher), "siesta_executable": runtime["siesta"]["selected_executable"], "executable_arguments": [], "launcher": launcher_data, "exclusive": True, "environment": runtime_environment},
        "tasks": [{"task_id": "M10_SIESTA_SMOKE", "input": "input/smoke.fdf", "input_hashes": hashes, "required_artifacts": [], "mpi_processes": placement["ntasks"], "cpus_per_process": placement["cpus_per_task"], "nodes": placement["nodes"], "estimated_runtime_seconds": 600, "max_attempts": 1, "require_scf_converged": True}],
    }
    path = source / "campaign.json"
    _write_json(path, campaign)
    return path


def _continuation_campaign(
    selection: Mapping[str, Any], runtime: Mapping[str, Any], source: Path,
    *, placement: Mapping[str, Any] | None = None,
) -> Path:
    derived_placement_supplied = placement is not None
    placement = _resolved_placement(selection) if placement is None else placement
    processes_per_node = _live_placement_value(
        placement, "processes_per_node", "tasks_per_node"
    )
    total_cpus = _live_placement_value(
        placement, "total_cpus", "total_allocated_cpus"
    )
    (source / "input").mkdir(parents=True)
    input_path = source / "input" / "continuation-input.json"
    _write_json(input_path, {"classification": "NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "purpose": "M10 allocation continuation"})
    digest = _sha(input_path)
    task_base = {"input": "input/continuation-input.json", "input_hashes": {"input/continuation-input.json": digest}, "required_artifacts": [], "mpi_processes": 1, "cpus_per_process": 1, "nodes": 0, "max_attempts": 2, "kind": "gate"}
    campaign = {
        "schema_version": "2.0", "campaign_id": CONTINUATION_CAMPAIGN_ID, "system_id": "M10_ALLOCATION_CONTINUATION_TECHNICAL",
        "classification": ["NON_SCIENTIFIC_TECHNICAL_ACCEPTANCE", "ENERGY_INTERPRETATION_FORBIDDEN"], "slurm": _slurm(selection),
        "resources": {"nodes": placement["nodes"], "total_cpus": total_cpus, "ntasks": placement["ntasks"], "cpus_per_task": placement["cpus_per_task"], "memory": selection["memory"], "walltime": placement["walltime"] if derived_placement_supplied else "00:03:00", "max_parallel_steps": 1, "shutdown_margin_seconds": CONTINUATION_SHUTDOWN_MARGIN_SECONDS, "termination_grace_seconds": 10},
        "runtime": {"module_commands": _runtime_setup(runtime, "srun"), "siesta_executable": runtime["python"]["selected_executable"], "executable_arguments": [], "launcher": {"kind": "srun", "command": [runtime["launchers"]["srun"]["selected_executable"]], "arguments": _srun_arguments(runtime, placement), "processes_per_node": processes_per_node}, "exclusive": True, "environment": {"QRAFT_PYTHON": _selected_python_path(runtime)}},
        "tasks": [
            {"task_id": "STAGE_A", "command": [runtime["python"]["selected_executable"], "-c", "from pathlib import Path; import time; time.sleep(4); Path('stage_a.complete').write_text('complete\\n', encoding='utf-8')"], "estimated_runtime_seconds": CONTINUATION_STAGE_A_ESTIMATE_SECONDS, **task_base},
            {"task_id": "STAGE_B", "command": [runtime["python"]["selected_executable"], "-c", "from pathlib import Path; import time; time.sleep(2); Path('stage_b.complete').write_text('complete\\n', encoding='utf-8')"], "depends_on": ["STAGE_A"], "estimated_runtime_seconds": CONTINUATION_STAGE_B_ESTIMATE_SECONDS, **task_base},
        ],
    }
    path = source / "campaign.json"
    _write_json(path, campaign)
    return path


def _equivalence(hydra: Path, srun: Path) -> dict[str, Any]:
    first = translate_controller_config(load_controller_config(hydra), root=hydra.parent)
    second = translate_controller_config(load_controller_config(srun), root=srun.parent)
    task = "M10_SIESTA_SMOKE"
    payload = {
        "workflow_id_equal": first.workflow.workflow_id == second.workflow.workflow_id,
        "workflow_definition_sha256_equal": first.workflow.definition_sha256 == second.workflow.definition_sha256,
        "scientific_identity_equal": first.scientific_identities[task].fingerprint == second.scientific_identities[task].fingerprint,
        "execution_spec_different": first.execution_specs[task].fingerprint != second.execution_specs[task].fingerprint,
        "workflow_id": first.workflow.workflow_id, "workflow_definition_sha256": first.workflow.definition_sha256,
        "scientific_identity_sha256": first.scientific_identities[task].fingerprint,
        "hydra_execution_spec_sha256": first.execution_specs[task].fingerprint,
        "srun_execution_spec_sha256": second.execution_specs[task].fingerprint,
    }
    if not all(payload[key] for key in ("workflow_id_equal", "workflow_definition_sha256_equal", "scientific_identity_equal", "execution_spec_different")):
        raise ValueError("M10 backend equivalence precheck failed")
    return payload


def _preflight_script(
    selection: Mapping[str, Any], runtime: Mapping[str, Any],
    *, placement: Mapping[str, Any] | None = None,
) -> str:
    placement = _resolved_placement(selection) if placement is None else placement
    processes_per_node = _live_placement_value(
        placement, "processes_per_node", "tasks_per_node"
    )
    qos = f"#SBATCH --qos={selection['qos']}\n" if selection.get("qos") is not None else ""
    account = f"#SBATCH --account={selection['account']}\n" if selection.get("account") is not None else ""
    setup = "\n".join(_runtime_setup(runtime, "srun"))
    hydra = runtime["launchers"].get("hydra")
    hydra_setup = ""
    hydra_check = ""
    if isinstance(hydra, Mapping) and hydra.get("required") is not False:
        bootstrap = _hydra_bootstrap(hydra.get("bootstrap"))
        hydra_arguments = _runtime_commands(hydra.get("arguments"), "launchers.hydra.arguments")
        if "-bootstrap" in hydra_arguments:
            raise ValueError(
                "M10_RUNTIME_PROFILE_UNRESOLVED: Hydra bootstrap must be supplied only by launchers.hydra.bootstrap"
            )
        hydra_setup = "\n".join(_runtime_setup(runtime, "hydra"))
        hydra_command = " ".join(
            [
                shlex.quote(str(hydra["selected_executable"])),
                *(shlex.quote(item) for item in hydra_arguments),
                "-bootstrap",
                shlex.quote(bootstrap),
                "-hosts",
                '"$M10_HOST_CSV"',
                "-np",
                str(placement["ntasks"]),
                "-ppn",
                str(processes_per_node),
                "hostname",
            ]
        )
        hydra_check = f"""
  {hydra_command} | LC_ALL=C sort | uniq -c | tee "evidence/hydra-placement.${{SLURM_JOB_ID}}.txt"
  validate_placement "evidence/hydra-placement.${{SLURM_JOB_ID}}.txt" M10_PREFLIGHT_HYDRA_PLACEMENT_INVALID
"""
    return f"""#!/usr/bin/env bash
#SBATCH --job-name=QRAFT_M10_PREFLIGHT
#SBATCH --partition={selection['partition']}
{account}{qos}#SBATCH --nodes={placement['nodes']}
#SBATCH --ntasks={placement['ntasks']}
#SBATCH --ntasks-per-node={processes_per_node}
#SBATCH --cpus-per-task={placement['cpus_per_task']}
#SBATCH --time={placement['walltime']}
#SBATCH --output=preflight/preflight.%j.out
#SBATCH --error=preflight/preflight.%j.err
set -euo pipefail
ROOT="$(cd "${{SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR required}}" && pwd -P)"
cd "$ROOT"; mkdir -p evidence
MARKER="$ROOT/evidence/m10-shared-filesystem.marker"; MANIFEST="$ROOT/bundle_manifest.json"
printf 'QRAFT M10 shared filesystem marker\\n' > "$MARKER"
{{
  scontrol --version || scontrol version || true
  printf 'SLURM_JOB_ID=%s\\nSLURM_JOB_PARTITION=%s\\nSLURM_NNODES=%s\\nSLURM_SUBMIT_DIR=%s\\n' "$SLURM_JOB_ID" "${{SLURM_JOB_PARTITION:-}}" "$SLURM_NNODES" "$ROOT"
  mapfile -t M10_HOSTS < <(scontrol show hostnames "${{SLURM_JOB_NODELIST:?SLURM_JOB_NODELIST required}}")
  [[ "${{#M10_HOSTS[@]}}" -eq {placement['nodes']} ]] || {{ echo "M10_PREFLIGHT_ALLOCATION_HOST_COUNT_INVALID:${{#M10_HOSTS[@]}}" >&2; exit 1; }}
  M10_HOST_CSV="$(IFS=,; echo "${{M10_HOSTS[*]}}")"
  validate_placement() {{
    local evidence_file="$1" failure_code="$2"
    awk -v expected_nodes={placement['nodes']} -v expected_ppn={processes_per_node} -v expected_tasks={placement['ntasks']} '
      {{ if ($1 != expected_ppn) exit 2; rows += 1; tasks += $1 }}
      END {{ if (rows != expected_nodes || tasks != expected_tasks) exit 3 }}
    ' "$evidence_file" || {{ echo "$failure_code" >&2; exit 1; }}
  }}
  {setup}
  {hydra_setup}
  test -x /usr/bin/srun
  command -v {shlex.quote(runtime['launchers']['srun']['selected_executable'])}
  export M10_SELECTED_PYTHON={shlex.quote(runtime['python']['selected_executable'])}
  export M10_SELECTED_SIESTA={shlex.quote(runtime['siesta']['selected_executable'])}
  export M10_SELECTED_HYDRA={shlex.quote(runtime['launchers']['hydra']['selected_executable'])}
  srun --nodes={placement['nodes']} --ntasks={placement['nodes']} --ntasks-per-node=1 --cpus-per-task=1 bash -c 'set -eu; command -v "$M10_SELECTED_PYTHON"; "$M10_SELECTED_PYTHON" -c "import sys; assert sys.version_info >= (3, 11), sys.version"; command -v "$M10_SELECTED_SIESTA"; test -x /usr/bin/srun; command -v "$M10_SELECTED_HYDRA"'
  env | LC_ALL=C sort | grep '^SLURM_' || true
  export M10_SHARED_MARKER="$MARKER" M10_SHARED_MANIFEST="$MANIFEST"
  srun --nodes={placement['nodes']} --ntasks={placement['nodes']} --ntasks-per-node=1 --cpus-per-task=1 bash -c 'set -eu; printf "host=%s path=%s marker_sha256=%s manifest_sha256=%s\\n" "$(hostname -f 2>/dev/null || hostname)" "$M10_SHARED_MARKER" "$(sha256sum "$M10_SHARED_MARKER" | awk "{{print \\$1}}")" "$(sha256sum "$M10_SHARED_MANIFEST" | awk "{{print \\$1}}")"'
  srun --nodes={placement['nodes']} --ntasks={placement['ntasks']} --ntasks-per-node={processes_per_node} --cpus-per-task={placement['cpus_per_task']} hostname | LC_ALL=C sort | uniq -c | tee "evidence/srun-placement.${{SLURM_JOB_ID}}.txt"
  validate_placement "evidence/srun-placement.${{SLURM_JOB_ID}}.txt" M10_PREFLIGHT_SRUN_PLACEMENT_INVALID{hydra_check}
}} 2>&1 | tee "evidence/preflight.${{SLURM_JOB_ID}}.txt"
"""


def _discovery_readme() -> str:
    return """# M10 scheduler discovery (manual)

`HISTORICAL_ONLY_NOT_CURRENT_AUTHORITY`: prior observations were partition
`tt2d-64p`, account `vini`, QoS `normal`. They are hints only and are not used
by this bundle. This directory is self-contained for login-node discovery:
`run_login_probe.sh` captures Bash-only, read-only raw evidence and never calls
Python. Review its available module names before explicitly running
`run_runtime_candidate_probe.sh`; that isolated Bash probe verifies selected
module environments without launching ranks. On a machine with Python >=3.11,
`build_login_summary.py --runtime-probe ...`, `resolve_m10_scheduler.py`, and
`resolve_m10_runtime.py` produce reviewed selections. They never submit a job.
Both selections need human approval.
"""


def _unresolved(repository: Path, output: Path) -> dict[str, Any]:
    fixture = output / "scientific_fixture"
    hashes = _fixture(repository, fixture)
    discovery = output / "scheduler_discovery"
    discovery.mkdir()
    raw_probe = repository / "tools" / "m10_yoltla_raw_login_probe.sh"
    runtime_probe = repository / "tools" / "m10_yoltla_runtime_candidate_probe.sh"
    summary_builder = repository / "tools" / "build_yoltla_m10_login_summary.py"
    scheduler_resolver = repository / "tools" / "resolve_yoltla_m10_scheduler.py"
    scheduler_resolution = repository / "src" / "qraft" / "validation" / "scheduler_resolution.py"
    runtime_resolver = repository / "tools" / "resolve_yoltla_m10_runtime.py"
    runtime_compatibility = repository / "src" / "qraft" / "runtime_compatibility.py"
    _copy_linux_text(raw_probe, discovery / "run_login_probe.sh")
    _copy_linux_text(runtime_probe, discovery / "run_runtime_candidate_probe.sh")
    _copy_linux_text(summary_builder, discovery / "build_login_summary.py")
    _copy_linux_text(scheduler_resolver, discovery / "resolve_m10_scheduler.py")
    _copy_linux_text(scheduler_resolution, discovery / "scheduler_resolution.py")
    _copy_linux_text(runtime_resolver, discovery / "resolve_m10_runtime.py")
    _copy_linux_text(runtime_compatibility, discovery / "runtime_compatibility.py")
    (discovery / "README.md").write_text(_discovery_readme(), encoding="utf-8", newline="\n")
    _write_json(discovery / "resource_requirements.json", {"allocation_policy": "MAXIMUM_LEGAL_PLACEMENT_FIXED_PARTITION", "cpus_per_task": 1, "walltime": "00:20:00"})
    manifest = {"schema_version": "1.0", "scheduler_profile_status": "UNRESOLVED", "runtime_profile_status": "UNRESOLVED", "placement_status": "UNRESOLVED", "historical_hint": HISTORICAL_HINT, "scientific_fixture_hashes": hashes, "raw_login_probe": {"source": "tools/m10_yoltla_raw_login_probe.sh", "sha256": _sha(raw_probe), "python_required": False, "module_required": False}, "runtime_candidate_probe": {"source": "tools/m10_yoltla_runtime_candidate_probe.sh", "sha256": _sha(runtime_probe), "python_required": False, "requires_explicit_modules": True, "launches_work": False}, "m10_scheduler_resolver": {"source": "tools/resolve_yoltla_m10_scheduler.py", "sha256": _sha(scheduler_resolver), "generic_engine_source": "src/qraft/validation/scheduler_resolution.py", "generic_engine_sha256": _sha(scheduler_resolution)}, "m10_runtime_resolver": {"source": "tools/resolve_yoltla_m10_runtime.py", "sha256": _sha(runtime_resolver), "compatibility_authority_source": "src/qraft/runtime_compatibility.py", "compatibility_authority_sha256": _sha(runtime_compatibility)}, "remote_execution_status": "PENDING_REMOTE", "scientific_submit_scripts_generated": False}
    _write_json(output / "bundle_manifest.json", manifest)
    (output / "README.md").write_text("# QRAFT M10 unresolved discovery bundle\n\nNo scientific submit scripts are generated until a current, human-reviewed scheduler selection is supplied.\n", encoding="utf-8", newline="\n")
    return manifest


def _resolved(repository: Path, output: Path, selection_path: Path, runtime_path: Path) -> dict[str, Any]:
    selection = _load_scheduler_selection(selection_path)
    placement = _resolved_placement(selection)
    runtime = _load_runtime_selection(runtime_path)
    if not isinstance(runtime["launchers"].get("hydra"), Mapping) or runtime["launchers"]["hydra"].get("required") is False:
        raise ValueError("M10_RUNTIME_PROFILE_UNRESOLVED: resolved M10 bundle requires reviewed Hydra acceptance")
    provenance = output / "provenance"; provenance.mkdir()
    copied_selection = provenance / "scheduler_selection.json"; shutil.copy2(selection_path, copied_selection)
    copied_runtime = provenance / "runtime_selection.json"; shutil.copy2(runtime_path, copied_runtime)
    sources = output / "sources"
    hydra = _siesta_campaign(repository, selection, runtime, "hydra", sources / "hydra")
    srun = _siesta_campaign(repository, selection, runtime, "srun", sources / "srun")
    continuation = _continuation_campaign(selection, runtime, sources / "continuation")
    packages = output / "packages"; packages.mkdir()
    builder = ControllerPackageBuilder(repository)
    provenance_files = {"provenance/scheduler_selection.json": copied_selection, "provenance/runtime_selection.json": copied_runtime}
    results = {"hydra": builder.build(hydra, packages / "hydra", provenance_files=provenance_files).__dict__, "srun": builder.build(srun, packages / "srun", provenance_files=provenance_files).__dict__, "continuation": builder.build(continuation, packages / "continuation", provenance_files=provenance_files).__dict__}
    equivalence = _equivalence(hydra, srun)
    _write_json(output / "backend_equivalence.json", equivalence)
    preflight = output / "preflight"; preflight.mkdir()
    _write_linux_text(preflight / "submit_m10_preflight.slurm", _preflight_script(selection, runtime))
    manifest = {"schema_version": "1.0", "scheduler_profile_status": "RESOLVED_FROM_CLUSTER_EVIDENCE", "runtime_profile_status": "RESOLVED_FROM_CLUSTER_EVIDENCE", "capacity_evidence": selection["capacity_evidence"], "derived_placement": placement, "scheduler_selection": {"relative_path": "provenance/scheduler_selection.json", "sha256": _sha(copied_selection), "account": selection.get("account"), "partition": selection["partition"], "qos": selection.get("qos"), "source_files": selection["source_files"], "evidence_status_by_field": selection["evidence_status_by_field"]}, "runtime_selection": {"relative_path": "provenance/runtime_selection.json", "sha256": _sha(copied_runtime), "python_requirement": runtime["python"]["requirement"], "environment_setup": [*runtime["python"]["environment_setup"], *runtime["siesta"]["environment_setup"]]}, "packages": results, "backend_equivalence": equivalence, "continuation_external_allocations": {"first_seconds": 60, "second_seconds": 180, "same_package_root_and_config": True}, "execution_authority": "ControllerPackageBuilder -> CanonicalController -> CompiledWorkflowRuntime", "remote_execution_status": "PENDING_REMOTE"}
    _write_json(output / "bundle_manifest.json", manifest)
    return manifest


def _resolved_live(
    repository: Path, output: Path, live_selection_path: Path, runtime_path: Path,
) -> dict[str, Any]:
    scheduler, placement, live_selection, sources = _load_live_slurm_selection(
        live_selection_path
    )
    runtime = _load_runtime_selection(runtime_path)
    if (
        not isinstance(runtime["launchers"].get("hydra"), Mapping)
        or runtime["launchers"]["hydra"].get("required") is False
    ):
        raise ValueError(
            "M10_RUNTIME_PROFILE_UNRESOLVED: resolved M10 bundle requires reviewed Hydra acceptance"
        )
    provenance = output / "provenance"
    provenance.mkdir()
    copied_live = provenance / "live-slurm-selection.json"
    copied_runtime = provenance / "runtime_selection.json"
    shutil.copy2(live_selection_path, copied_live)
    shutil.copy2(runtime_path, copied_runtime)
    sources_root = output / "sources"
    hydra = _siesta_campaign(
        repository, scheduler, runtime, "hydra", sources_root / "hydra",
        placement=placement,
    )
    srun = _siesta_campaign(
        repository, scheduler, runtime, "srun", sources_root / "srun",
        placement=placement,
    )
    continuation = _continuation_campaign(
        scheduler, runtime, sources_root / "continuation", placement=placement,
    )
    packages = output / "packages"
    packages.mkdir()
    builder = ControllerPackageBuilder(repository)
    provenance_files = {
        "provenance/live-slurm-selection.json": copied_live,
        "provenance/runtime_selection.json": copied_runtime,
    }
    results = {
        "hydra": builder.build(
            hydra, packages / "hydra", provenance_files=provenance_files
        ).__dict__,
        "srun": builder.build(
            srun, packages / "srun", provenance_files=provenance_files
        ).__dict__,
        "continuation": builder.build(
            continuation, packages / "continuation", provenance_files=provenance_files
        ).__dict__,
    }
    equivalence = _equivalence(hydra, srun)
    _write_json(output / "backend_equivalence.json", equivalence)
    preflight = output / "preflight"
    preflight.mkdir()
    _write_linux_text(
        preflight / "submit_m10_preflight.slurm",
        _preflight_script(scheduler, runtime, placement=placement),
    )
    manifest = {
        "schema_version": "1.0",
        "scheduler_profile_status": "RESOLVED_FROM_LIVE_SLURM_SELECTION",
        "runtime_profile_status": "RESOLVED_FROM_CLUSTER_EVIDENCE",
        "derived_placement": placement,
        "live_slurm_selection": {
            "relative_path": "provenance/live-slurm-selection.json",
            "sha256": _sha(copied_live),
            "observed_at": live_selection["observed_at"],
            "account": scheduler["account"],
            "partition": scheduler["partition"],
            "qos": scheduler["qos"],
            "source_command_evidence": sources["commands"],
            "node_capability_evidence_count": len(sources["node_capabilities"]),
        },
        "runtime_selection": {
            "relative_path": "provenance/runtime_selection.json",
            "sha256": _sha(copied_runtime),
            "python_requirement": runtime["python"]["requirement"],
            "environment_setup": [
                *runtime["python"]["environment_setup"],
                *runtime["siesta"]["environment_setup"],
            ],
        },
        "packages": results,
        "backend_equivalence": equivalence,
        "continuation_external_allocations": {
            "first_seconds": 60,
            "second_seconds": 180,
            "same_package_root_and_config": True,
        },
        "execution_authority": "ControllerPackageBuilder -> CanonicalController -> CompiledWorkflowRuntime",
        "remote_execution_status": "PENDING_REMOTE",
    }
    _write_json(output / "bundle_manifest.json", manifest)
    return manifest


def build_bundle(
    repository: Path, output: Path, *, scheduler_selection: Path | None = None,
    live_slurm_selection: Path | None = None, runtime_selection: Path | None = None,
) -> dict[str, Any]:
    repository, output = repository.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite M10 bundle: {output}")
    output.mkdir(parents=True)
    if (
        scheduler_selection is None
        and live_slurm_selection is None
        and runtime_selection is None
    ):
        return _unresolved(repository, output)
    if scheduler_selection is not None and live_slurm_selection is not None:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: select either legacy scheduler evidence or live Slurm evidence"
        )
    if runtime_selection is None:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: resolved bundle requires runtime_selection.json"
        )
    if live_slurm_selection is not None:
        return _resolved_live(
            repository, output, live_slurm_selection.resolve(), runtime_selection.resolve()
        )
    if scheduler_selection is None:
        raise ValueError(
            "M10_REMOTE_PROFILE_UNRESOLVED: resolved bundle requires scheduler_selection.json or live-slurm-selection.json"
        )
    return _resolved(repository, output, scheduler_selection.resolve(), runtime_selection.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scheduler-selection", type=Path,
        help="legacy M10 scheduler evidence; not current runtime authority",
    )
    parser.add_argument("--live-slurm-selection", type=Path)
    parser.add_argument("--runtime-selection", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_bundle(Path(__file__).resolve().parents[1], args.output, scheduler_selection=args.scheduler_selection, live_slurm_selection=args.live_slurm_selection, runtime_selection=args.runtime_selection), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
