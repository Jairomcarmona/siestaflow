"""Minimal FDF -> plan -> allocation-local SIESTA vertical."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import tomllib
except ImportError:  # pragma: no cover - QRAFT requires Python >= 3.11.
    tomllib = None  # type: ignore[assignment]

from .. import __version__ as QRAFT_VERSION
from ..contracts import (
    ArtifactReference,
    ArtifactRole,
    CapabilityRegistry,
    CompiledWorkflow,
    WorkflowInputBinding,
    WorkflowTaskKind,
    WorkflowTaskNode,
)
from ..core import (
    Attempt,
    DAGNode,
    ExecutionSpec,
    NodeResult,
    ScientificIdentity,
    TechnicalValidation,
)
from ..engines.siesta.fdf_parser import FDFParser
from ..engines.siesta.input_validator import SiestaInputValidator
from ..engines.siesta.models import FDFBlock, FDFInclude, OutputClassification
from ..engines.siesta.output_parser import SiestaOutputParser
from ..execution.adapters import launcher_registry
from ..execution.capability_plugins import SIESTA_ENGINE_CAPABILITY, register_siesta_engine
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.runtime_composition import compose_runtime
from ..execution.slurm_environment import SlurmEnvironment
from ..execution.srun_launcher import StepLaunchSpec, StepOutcome
from ..models import DecisionStatus
from ..output import (
    DagEntry, ExecutionSession, NodeEntry, OutputMessage, OutputModel,
    QraftOutputWriter,
)


DEFAULT_EXECUTION: dict[str, Any] = {
    # ``local`` is a non-scheduler label used only for an explicitly selected
    # direct launcher.  No SLURM partition is inferred by QRAFT.
    "partition": "local",
    "nodes": 1,
    "mpi_ranks": 1,
    "cpus_per_rank": 1,
    "memory_mb": None,
    "walltime_seconds": 3600,
    "environment": {},
    "executable_arguments": [],
    "launcher_command": [],
    "launcher_arguments": [],
}

# Placement and executable selection are properties of a deployment, not of a
# scientific FDF.  They must therefore enter via profile, project/recipe
# configuration or an explicit CLI/REPL override.
_REQUIRED_EXECUTION_FIELDS = ("partition", "launcher", "executable")
_EXECUTION_FIELDS = frozenset((*DEFAULT_EXECUTION, *_REQUIRED_EXECUTION_FIELDS))

SINGLE_FDF_DAG = (
    DAGNode("validate_input", "validate_input"),
    DAGNode("run_siesta", "run_siesta", ("validate_input",)),
    DAGNode("technical_validate", "technical_validate", ("run_siesta",)),
)


def _sha_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _sha_bytes(encoded)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_mapping(source: Path | Mapping[str, Any] | None) -> dict[str, Any]:
    if source is None:
        return {}
    if isinstance(source, Mapping):
        data = dict(source)
        nested = data.get("execution")
        if nested is not None:
            if not isinstance(nested, Mapping):
                raise ValueError("execution section must be a mapping")
            data = dict(nested)
        return data
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"execution configuration does not exist: {path}")
    if path.suffix.casefold() == ".toml":
        if tomllib is None:
            raise RuntimeError("TOML configuration requires Python 3.11+")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"execution configuration must be a mapping: {path}")
    nested = data.get("execution")
    if nested is not None:
        if not isinstance(nested, dict):
            raise ValueError(f"execution section must be a mapping: {path}")
        data = nested
    return dict(data)


def resolve_execution_spec(
    *,
    profile: Path | Mapping[str, Any] | None = None,
    project_config: Path | None = None,
    recipe: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> tuple[ExecutionSpec, dict[str, str]]:
    """Resolve defaults < profile < project < recipe < CLI overrides."""

    allowed = _EXECUTION_FIELDS
    resolved = dict(DEFAULT_EXECUTION)
    provenance = {key: "defaults" for key in resolved}
    layers = (
        ("profile", _read_mapping(profile)),
        ("project", _read_mapping(project_config)),
        ("recipe", _read_mapping(recipe)),
        ("cli", {key: value for key, value in dict(overrides or {}).items() if value is not None}),
    )
    for source, layer in layers:
        unknown = sorted(set(layer) - allowed)
        if unknown:
            raise ValueError(f"unknown execution fields in {source}: {', '.join(unknown)}")
        for key, value in layer.items():
            resolved[key] = value
            provenance[key] = source
    missing = [name for name in _REQUIRED_EXECUTION_FIELDS if not str(resolved.get(name, "")).strip()]
    if missing:
        if "launcher" in missing and int(resolved["mpi_ranks"]) > 1:
            raise ValueError(
                "MPI execution requested but no launcher is configured; "
                "provide --launcher or an execution profile"
            )
        raise ValueError(
            "execution configuration is incomplete; provide "
            + ", ".join(missing)
            + " through a profile, configuration file, or CLI override"
        )
    for name in ("nodes", "mpi_ranks", "cpus_per_rank", "walltime_seconds"):
        value = resolved[name]
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a positive integer")
        resolved[name] = int(value)
    if resolved["memory_mb"] is not None:
        if isinstance(resolved["memory_mb"], bool):
            raise ValueError("memory_mb must be a positive integer")
        resolved["memory_mb"] = int(resolved["memory_mb"])
    for name in ("executable_arguments", "launcher_command", "launcher_arguments"):
        value = resolved[name]
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{name} must be a list")
        resolved[name] = tuple(map(str, value))
    if not isinstance(resolved["environment"], Mapping):
        raise ValueError("environment must be a mapping")
    spec = ExecutionSpec(**resolved)
    launcher_registry.require(spec.launcher).validate_resources(
        mpi_ranks=spec.mpi_ranks, nodes=spec.nodes
    )
    return spec, provenance


def _safe_scientific_path(root: Path, owner: Path, target: str) -> Path:
    clean = str(target).strip().strip("\"'")
    candidate = (owner.parent / clean).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"scientific include escapes the FDF root: {target}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"included scientific file does not exist: {candidate}")
    return candidate


def _collect_fdf_files(root_fdf: Path) -> tuple[Path, dict[str, Path], list[Any]]:
    root_fdf = root_fdf.resolve()
    if not root_fdf.is_file():
        raise FileNotFoundError(f"FDF does not exist: {root_fdf}")
    root = root_fdf.parent
    files: dict[str, Path] = {}
    documents: list[Any] = []
    visiting: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in visiting:
            raise ValueError(f"cyclic FDF include detected at {resolved}")
        relative = resolved.relative_to(root).as_posix()
        if relative in files:
            return
        visiting.add(resolved)
        document = FDFParser().parse_path(resolved)
        files[relative] = resolved
        documents.append(document)
        targets: list[str] = []
        for node in document.nodes:
            if isinstance(node, FDFInclude):
                targets.append(node.target)
            elif isinstance(node, FDFBlock) and node.redirected_to:
                targets.append(node.redirected_to)
        for target in targets:
            visit(_safe_scientific_path(root, resolved, target))
        visiting.remove(resolved)

    visit(root_fdf)
    return root, dict(sorted(files.items())), documents


def _block_payloads(documents: Sequence[Any], names: set[str]) -> list[str]:
    normalized = {"".join(c.lower() for c in name if c not in ".-_ ") for name in names}
    result: list[str] = []
    for document in documents:
        for block in document.blocks():
            key = "".join(c.lower() for c in block.name if c not in ".-_ ")
            if key in normalized:
                result.append(block.raw)
    return result


def _scalar_payloads(documents: Sequence[Any], names: set[str]) -> list[str]:
    normalized = {"".join(c.lower() for c in name if c not in ".-_ ") for name in names}
    result: list[str] = []
    for document in documents:
        for scalar in document.scalars():
            key = "".join(c.lower() for c in scalar.label if c not in ".-_ ")
            if key in normalized:
                result.append(scalar.raw)
    return result


def _species(documents: Sequence[Any]) -> tuple[str, ...]:
    rows = _block_payloads(documents, {"ChemicalSpeciesLabel"})
    labels: list[str] = []
    for payload in rows:
        for line in payload.splitlines()[1:-1]:
            clean = line.split("#", 1)[0].strip()
            tokens = clean.split()
            if len(tokens) >= 3:
                labels.append(tokens[2])
    if not labels:
        raise ValueError("ChemicalSpeciesLabel must declare at least one species")
    if len(set(label.casefold() for label in labels)) != len(labels):
        raise ValueError("ChemicalSpeciesLabel contains duplicate species labels")
    return tuple(labels)


def _resolve_pseudopotentials(
    root: Path,
    species: Sequence[str],
    pseudo_manifest: Path | None,
) -> dict[str, Path]:
    manifest_entries: dict[str, Path] = {}
    if pseudo_manifest is not None:
        data = _read_mapping(pseudo_manifest)
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("pseudopotential manifest requires an entries list")
        for item in entries:
            if not isinstance(item, dict) or not str(item.get("species", "")).strip():
                raise ValueError("invalid pseudopotential manifest entry")
            source = item.get("path") or item.get("filename")
            if not source:
                raise ValueError(f"pseudopotential path missing for {item.get('species')}")
            candidate = Path(str(source))
            if not candidate.is_absolute():
                candidate = (pseudo_manifest.parent / candidate).resolve()
            manifest_entries[str(item["species"]).casefold()] = candidate
    resolved: dict[str, Path] = {}
    for label in species:
        if manifest_entries:
            candidates = [manifest_entries[label.casefold()]] if label.casefold() in manifest_entries else []
        else:
            candidates = [
                candidate
                for extension in ("psml", "psf")
                if (candidate := root / f"{label}.{extension}").is_file()
            ]
        candidates = [path.resolve() for path in candidates if path.is_file()]
        if len(candidates) != 1:
            raise ValueError(
                f"exactly one psml/psf pseudopotential is required for {label}; found {len(candidates)}"
            )
        resolved[label] = candidates[0]
    return resolved


def build_scientific_identity(
    fdf: Path,
    *,
    pseudo_manifest: Path | None = None,
) -> ScientificIdentity:
    root, files, documents = _collect_fdf_files(fdf)
    species = _species(documents)
    pseudos = _resolve_pseudopotentials(root, species, pseudo_manifest)
    included_hashes = {name: _sha_path(path) for name, path in files.items()}
    effective = _canonical_sha(included_hashes)
    geometry = _canonical_sha(
        _block_payloads(
            documents,
            {"LatticeVectors", "AtomicCoordinatesAndAtomicSpecies", "AtomicCoordinates"},
        )
        + _scalar_payloads(
            documents,
            {"LatticeConstant", "AtomicCoordinatesFormat", "NumberOfAtoms"},
        )
    )
    species_mapping = _canonical_sha(
        _block_payloads(documents, {"ChemicalSpeciesLabel"})
        + _scalar_payloads(documents, {"NumberOfSpecies"})
    )
    component_groups = {
        "charge_spin": {"NetCharge", "Spin", "SpinPolarized", "TotalSpin"},
        "basis": {"PAO.BasisSize", "PAO.Basis", "PAO.EnergyShift", "PAO.SplitNorm"},
        "xc": {"XC.Functional", "XC.Authors"},
        "k_grid": {"kgrid_Monkhorst_Pack", "BandLines", "BandPoints"},
        "mesh_cutoff": {"MeshCutoff"},
        "dft_u_projectors": {"LDAU.ProjectorGenerationMethod", "LDAU.Proj", "DM.Projectors"},
    }
    components = {
        name: _canonical_sha(
            _scalar_payloads(documents, labels) + _block_payloads(documents, labels)
        )
        for name, labels in component_groups.items()
    }
    return ScientificIdentity(
        engine="siesta",
        effective_fdf_sha256=effective,
        geometry_sha256=geometry,
        species_mapping_sha256=species_mapping,
        pseudopotentials={label: _sha_path(path) for label, path in pseudos.items()},
        components=components,
        included_scientific_files=included_hashes,
    )


def build_fdf_plan(
    fdf: Path,
    *,
    pseudo_manifest: Path | None = None,
    profile: Path | Mapping[str, Any] | None = None,
    project_config: Path | None = None,
    recipe: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    identity = build_scientific_identity(fdf, pseudo_manifest=pseudo_manifest)
    execution, provenance = resolve_execution_spec(
        profile=profile,
        project_config=project_config,
        recipe=recipe,
        overrides=overrides,
    )
    return {
        "schema_version": "1.0",
        "status": "EXECUTABLE_PLAN",
        "fdf": str(fdf.resolve()),
        "engine": "siesta",
        "scientific_identity": identity.to_dict(),
        "execution_spec": execution.to_dict(),
        "configuration_sources": provenance,
        "dag": [asdict(node) for node in SINGLE_FDF_DAG],
        "execution_authorized": False,
    }


def validate_technical_result(
    *,
    exit_code: int | None,
    stdout: Path,
    stderr: Path,
    required_artifacts: Sequence[Path] = (),
) -> TechnicalValidation:
    reasons: list[str] = []
    if exit_code != 0:
        reasons.append(f"NONZERO_EXIT:{exit_code}")
    if not stdout.is_file():
        reasons.append("MISSING_STDOUT")
        output_text = ""
    else:
        output_text = stdout.read_text(encoding="utf-8", errors="replace")
    if not stderr.is_file():
        reasons.append("MISSING_STDERR")
        error_text = ""
    else:
        error_text = stderr.read_text(encoding="utf-8", errors="replace")
    missing = [str(path) for path in required_artifacts if not path.is_file()]
    reasons.extend(f"MISSING_ARTIFACT:{path}" for path in missing)
    record = SiestaOutputParser().parse(
        (output_text + "\n" + error_text).splitlines(keepends=True), synthetic=False
    )
    if record.classification is not OutputClassification.COMPLETED:
        reasons.append(f"PARSER:{record.classification.value}")
    if not record.normal_termination:
        reasons.append("NORMAL_TERMINATION_MISSING")
    status = "PASS" if not reasons else "FAIL"
    return TechnicalValidation(
        status=status,
        classification=record.classification.value,
        reasons=tuple(reasons),
        parser_summary={
            "started": record.started,
            "normal_termination": record.normal_termination,
            "scf_started": record.scf_started,
            "scf_converged": record.scf_converged,
            "warnings": list(record.warnings),
            "errors": list(record.errors),
            "line_count": record.line_count,
        },
    )


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _exclusive_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, ensure_ascii=False)
        handle.write("\n")


def _event(path: Path, event: str, **data: object) -> None:
    payload = {"timestamp": _utc_now(), "event": event, **data}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def _output_warning(events: Path, operation: str, exc: Exception) -> None:
    _event(
        events,
        "OUTPUT_CORE_FAILURE",
        operation=operation,
        error=f"{type(exc).__name__}: {exc}",
    )


def _render_output(events: Path, operation: str, callback: Any) -> None:
    try:
        callback()
    except Exception as exc:  # Human output is derived and cannot invalidate science.
        _output_warning(events, operation, exc)


def _single_fdf_start_model(
    plan: Mapping[str, Any], fdf: Path, runs_root: Path,
    profile_metadata: Mapping[str, Any] | None = None,
) -> OutputModel:
    execution = plan["execution_spec"]
    identity = plan["scientific_identity"]
    adapter = launcher_registry.require(str(execution["launcher"]))
    scheduler = str((profile_metadata or {}).get("scheduler") or adapter.scheduler)
    return OutputModel(
        header={
            "Version": QRAFT_VERSION,
            "Started": _utc_now(),
            "Campaign": f"single_fdf:{fdf.stem}",
            "Campaign ID": identity["fingerprint"][:16],
            "Campaign root": str(runs_root.resolve()),
            "Host": socket.gethostname(),
            "SLURM Job": os.environ.get("SLURM_JOB_ID"),
            "Partition": execution["partition"],
            "Nodes": execution["nodes"],
            "MPI ranks": execution["mpi_ranks"],
            "Launcher": execution["launcher"],
            "Engine": "SIESTA",
            "Engine version": "runtime-resolved",
        },
        configuration={
            "engine": "siesta",
            "input FDF": str(fdf.resolve()),
            "protocol": "single_fdf",
            "working root": str(runs_root.resolve()),
            "partition": execution["partition"],
            "nodes": execution["nodes"],
            "mpi ranks": execution["mpi_ranks"],
            "cpus/rank": execution["cpus_per_rank"],
            "launcher": execution["launcher"],
            "executable": execution["executable"],
            "walltime seconds": execution["walltime_seconds"],
        },
        execution={
            "Scheduler": scheduler,
            "Launcher": execution["launcher"],
            "Executable": execution["executable"],
            "Command": _resolved_command(execution),
            "Partition": execution["partition"],
            "Nodes": execution["nodes"],
            "MPI ranks": execution["mpi_ranks"],
            "Ranks/node": execution["ranks_per_node"],
            "CPUs/rank": execution["cpus_per_rank"],
            "Profile": (profile_metadata or {}).get("name", "none"),
        },
        identity={
            "Scientific ID": str(identity["fingerprint"])[:16],
            "Execution ID": str(execution["fingerprint"])[:16],
            "QRAFT version": QRAFT_VERSION,
            "QRAFT commit": os.environ.get("QRAFT_COMMIT"),
            "Engine": "SIESTA",
            "Engine version": (profile_metadata or {}).get("engine_version", "runtime-resolved"),
        },
        dag=tuple(
            DagEntry(
                item["node_id"],
                item["kind"],
                "READY" if not item["depends_on"] else "WAITING",
                tuple(item["depends_on"]),
            )
            for item in plan["dag"]
        ),
        paths={"QRAFT output": str(runs_root.resolve() / "qraft.out")},
    )


def _validated_input(fdf: Path) -> tuple[bool, list[dict[str, str]]]:
    document = FDFParser().parse_path(fdf)
    result = SiestaInputValidator().validate(document)
    findings = [
        {"code": item.code, "status": item.status.value, "message": item.message}
        for item in result.findings
    ]
    hard = [
        item
        for item in result.findings
        if item.status in {DecisionStatus.FAIL, DecisionStatus.BLOCKED}
        and item.code != "UNRESOLVED_INCLUDE"
    ]
    return not hard, findings


def _stage_inputs(
    fdf: Path,
    pseudo_manifest: Path | None,
    attempt_dir: Path,
) -> Path:
    root, files, documents = _collect_fdf_files(fdf)
    pseudos = _resolve_pseudopotentials(root, _species(documents), pseudo_manifest)
    for relative, source in files.items():
        destination = attempt_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for source in pseudos.values():
        destination = attempt_dir / source.name
        if destination.exists() and _sha_path(destination) != _sha_path(source):
            raise ValueError(f"staged scientific input collision: {destination.name}")
        if not destination.exists():
            shutil.copy2(source, destination)
    return attempt_dir / fdf.resolve().relative_to(root)


def _direct_launch(spec: StepLaunchSpec) -> StepOutcome:
    command = (spec.executable, *spec.executable_arguments)
    started = time.monotonic()
    env = os.environ.copy()
    env.update(dict(spec.environment or {}))
    with (
        spec.input_path.open("rb") as stdin_handle,
        spec.stdout_path.open("xb") as stdout_handle,
        spec.stderr_path.open("xb") as stderr_handle,
    ):
        completed = subprocess.run(
            command,
            cwd=spec.workdir,
            stdin=stdin_handle,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            check=False,
        )
    return StepOutcome(
        spec.task_id,
        spec.attempt_id,
        tuple(command),
        int(completed.returncode),
        max(0.0, time.monotonic() - started),
        False,
    )


def _active_slurm(execution: ExecutionSpec) -> SlurmEnvironment | None:
    if not str(os.environ.get("SLURM_JOB_ID", "")).strip():
        return None
    active_partition = str(os.environ.get("SLURM_JOB_PARTITION", "")).strip()
    if active_partition and active_partition != execution.partition:
        raise ValueError(
            "execution partition does not match active allocation: "
            f"{execution.partition}!={active_partition}"
        )
    values = dict(os.environ)
    values.setdefault("SLURM_SUBMIT_DIR", str(Path.cwd()))
    values.setdefault(
        "SLURM_JOB_END_TIME", str(time.time() + execution.walltime_seconds)
    )
    slurm = SlurmEnvironment.from_mapping(values)
    slurm.validate_capacity(
        nodes=execution.nodes, total_cpus=execution.allocated_cpus
    )
    return slurm


def _launch(execution: ExecutionSpec, spec: StepLaunchSpec) -> StepOutcome:
    adapter = launcher_registry.require(execution.launcher)
    if execution.launcher == "direct":
        return _direct_launch(spec)
    slurm = _active_slurm(execution) if adapter.scheduler == "slurm" else None
    if adapter.requires_allocation and slurm is None:
        raise ValueError(
            f"{adapter.name} launcher requires an active {adapter.scheduler.upper()} allocation"
        )
    launch_spec = spec
    if adapter.requires_hosts:
        assert slurm is not None
        launch_spec = StepLaunchSpec(
            **{
                **asdict(spec),
                "hosts": slurm.resolve_hostnames()[: execution.nodes],
                "processes_per_node": execution.ranks_per_node,
            }
        )
    launcher = adapter.create(
        command=execution.launcher_command,
        arguments=execution.launcher_arguments,
        bootstrap="ssh",
    )
    return launcher.launch(launch_spec)


def _resolved_command(execution: Mapping[str, Any]) -> str:
    launcher = str(execution["launcher"])
    adapter = launcher_registry.require(launcher)
    return shlex.join(adapter.preview_command(
        command=execution.get("launcher_command", ()),
        arguments=execution.get("launcher_arguments", ()),
        executable=str(execution["executable"]),
        executable_arguments=execution.get("executable_arguments", ()),
        mpi_ranks=int(execution["mpi_ranks"]),
        cpus_per_rank=int(execution["cpus_per_rank"]),
    ))


def _next_session_epoch(events: Path) -> int:
    if not events.is_file():
        return 1
    count = 0
    try:
        with events.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    if json.loads(line).get("event") == "EXECUTION_SESSION_STARTED":
                        count += 1
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        return 1
    return count + 1


def _relevant_output(paths: Sequence[Path], *, limit: int = 6) -> tuple[str, ...]:
    pattern = re.compile(r"error|fatal|abort|termination|converg|scf", re.IGNORECASE)
    selected: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 65536))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            clean = line.strip()
            if clean and pattern.search(clean):
                selected.append(clean[:500])
    return tuple(selected[-limit:])


def _find_reusable_attempt(root: Path, scientific_fingerprint: str) -> dict[str, Any] | None:
    if not root.is_dir():
        return None
    for manifest in sorted(root.glob("*/attempt.json"), reverse=True):
        try:
            digest_path = manifest.with_name("attempt.sha256.json")
            digest_record = json.loads(digest_path.read_text(encoding="utf-8"))
            if digest_record.get("sha256") != _sha_path(manifest):
                continue
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("scientific_identity_sha256") != scientific_fingerprint:
                continue
            result = data.get("result", {})
            technical = result.get("technical_validation", {})
            if technical.get("status") != "PASS":
                continue
            artifacts = data.get("artifacts", {})
            if not isinstance(artifacts, dict) or any(
                not (manifest.parent / relative).is_file()
                or _sha_path(manifest.parent / relative) != digest
                for relative, digest in artifacts.items()
            ):
                continue
            return data
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            continue
    return None


def _execute_fdf_plan_legacy(
    fdf: Path,
    *,
    pseudo_manifest: Path | None = None,
    profile: Path | Mapping[str, Any] | None = None,
    project_config: Path | None = None,
    recipe: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    runs_root: Path = Path(".qraft-runs"),
    force_new_attempt: bool = False,
    invocation: str | None = None,
    profile_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    session_clock = time.monotonic()
    session_started = _utc_now()
    session_id = uuid.uuid4().hex
    resolved_runs = runs_root.resolve()
    events = resolved_runs / "events.jsonl"
    output_writer = QraftOutputWriter(
        resolved_runs / "qraft.out", campaign_root=resolved_runs
    )
    initial_output_exists = output_writer.exists
    epoch = _next_session_epoch(events)
    session_command = invocation or f"qraft run {shlex.quote(str(fdf))}"
    try:
        plan = build_fdf_plan(
            fdf,
            pseudo_manifest=pseudo_manifest,
            profile=profile,
            project_config=project_config,
            recipe=recipe,
            overrides=overrides,
        )
    except Exception as exc:
        _event(
            events,
            "PLAN_BUILD_FAILED",
            input_fdf=str(fdf.resolve()),
            error=f"{type(exc).__name__}: {exc}",
        )
        if not output_writer.exists:
            _render_output(
                events,
                "initialize",
                lambda: output_writer.initialize(OutputModel(
                    header={
                        "Version": QRAFT_VERSION,
                        "Started": _utc_now(),
                        "Campaign": f"single_fdf:{fdf.stem}",
                        "Campaign root": str(resolved_runs),
                        "Host": socket.gethostname(),
                        "Engine": "SIESTA",
                        "Engine version": "not-resolved",
                    },
                    configuration={
                        "engine": "siesta",
                        "input FDF": str(fdf.resolve()),
                        "protocol": "single_fdf",
                        "working root": str(resolved_runs),
                    },
                    paths={"QRAFT output": str(output_writer.path), "Evidence": str(events)},
                )),
            )
        _event(
            events,
            "EXECUTION_SESSION_STARTED",
            session_id=session_id,
            controller_epoch=epoch,
            mode="RESUME" if initial_output_exists else "NEW",
            command=session_command,
        )
        _render_output(
            events,
            "session_started",
            lambda: output_writer.start_session(ExecutionSession(
                session_id=session_id,
                controller_epoch=epoch,
                mode="RESUME" if initial_output_exists else "NEW",
                started=session_started,
                command=session_command,
                previous_state=None,
                working_root=str(resolved_runs),
            )),
        )
        _render_output(
            events,
            "planning_failure",
            lambda: output_writer.append(
                "PLANNING FAILURE",
                OutputModel(messages=(OutputMessage(
                    "BLOCKED",
                    f"{type(exc).__name__}: {exc}",
                    code="PLAN_BUILD_FAILED",
                    node_id="plan",
                    paths={"input": str(fdf.resolve()), "evidence": str(events)},
                    details={
                        "Technical state": "NOT_STARTED",
                        "DAG action": "EXECUTION BLOCKED BEFORE ATTEMPT",
                    },
                ),)),
            ),
        )
        _render_output(
            events,
            "session_finished",
            lambda: output_writer.finish_session(
                result="BLOCKED",
                finished=_utc_now(),
                elapsed_seconds=time.monotonic() - session_clock,
            ),
        )
        _render_output(
            events,
            "summary",
            lambda: output_writer.finish({
                "Campaign status": "BLOCKED",
                "Nodes total": 0,
                "Validated": 0,
                "Failed": 0,
                "Blocked": 1,
                "Pending": 0,
                "Root": str(resolved_runs),
                "QRAFT output": str(output_writer.path),
                "Evidence": str(events),
            }),
        )
        _event(
            events,
            "EXECUTION_SESSION_FINISHED",
            session_id=session_id,
            status="BLOCKED",
        )
        raise
    scientific_fingerprint = plan["scientific_identity"]["fingerprint"]
    execution = ExecutionSpec(
        **{
            key: value
            for key, value in plan["execution_spec"].items()
            if key
            not in {"fingerprint", "ranks_per_node", "allocated_cpus"}
        }
    )
    run_root = resolved_runs / scientific_fingerprint
    reusable = None if force_new_attempt else _find_reusable_attempt(run_root, scientific_fingerprint)
    output_existed = output_writer.exists
    start_model = _single_fdf_start_model(
        plan, fdf, resolved_runs, profile_metadata=profile_metadata
    )
    if not output_existed:
        _render_output(
            events,
            "initialize",
            lambda: output_writer.initialize(
                OutputModel(
                    header=start_model.header,
                )
            ),
        )
    previous_state = None
    state_path = run_root / "state.json"
    if state_path.is_file():
        try:
            previous_state = str(json.loads(state_path.read_text(encoding="utf-8")).get("technical_status"))
        except (OSError, json.JSONDecodeError, AttributeError):
            previous_state = "UNKNOWN"
    mode = "RECOVERY" if reusable is not None else "RESUME" if output_existed else "NEW"
    _event(
        events,
        "EXECUTION_SESSION_STARTED",
        session_id=session_id,
        controller_epoch=epoch,
        mode=mode,
        command=session_command,
    )
    _render_output(
        events,
        "session_started",
        lambda: output_writer.start_session(
            ExecutionSession(
                session_id=session_id,
                controller_epoch=epoch,
                mode=mode,
                started=session_started,
                command=session_command,
                previous_state=previous_state,
                working_root=str(resolved_runs),
            ),
            start_model,
        ),
    )
    if reusable is not None:
        _render_output(
            events,
            "recovery",
            lambda: output_writer.append_recovery({
                "Node": "run_siesta",
                "Attempt": reusable["attempt_id"],
                "Action": "REUSED_VALIDATED_ATTEMPT",
                "Result": "no SIESTA relaunch required",
                "Evidence": str(run_root / reusable["attempt_id"] / "attempt.json"),
            }),
        )
        _render_output(
            events,
            "session_finished",
            lambda: output_writer.finish_session(
                result="COMPLETED",
                finished=_utc_now(),
                elapsed_seconds=time.monotonic() - session_clock,
            ),
        )
        _render_output(
            events,
            "summary",
            lambda: output_writer.finish({
                "Campaign status": "COMPLETED",
                "Nodes total": 1,
                "Validated": 1,
                "Failed": 0,
                "Root": str(run_root),
                "QRAFT output": str(output_writer.path),
                "Evidence": str(events),
                "Resume": "validated attempt already reused",
            }),
        )
        _event(
            events,
            "EXECUTION_SESSION_FINISHED",
            session_id=session_id,
            status="COMPLETED",
        )
        return {
            "status": "REUSED_VALIDATED_ATTEMPT",
            "attempt": reusable,
            "plan": plan,
            "qraft_output": str(output_writer.path),
        }

    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:8]
    attempt_dir = run_root / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    started_at = _utc_now()
    _event(
        events,
        "ATTEMPT_STARTED",
        node_id="run_siesta",
        attempt_id=attempt_id,
        scientific_identity_sha256=scientific_fingerprint,
        execution_spec_sha256=execution.fingerprint,
    )
    _render_output(
        events,
        "node_started",
        lambda: output_writer.append(
            "NODE START",
            OutputModel(nodes=(NodeEntry(
                node_id="run_siesta",
                node_type="run_siesta",
                attempt_id=attempt_id,
                status="RUNNING",
                workdir=str(attempt_dir),
                input_path=str(fdf.resolve()),
                stdout_path=str(attempt_dir / "stdout.txt"),
                stderr_path=str(attempt_dir / "stderr.txt"),
                evidence_path=str(attempt_dir / "attempt.json"),
                resources={
                    "Nodes": execution.nodes,
                    "MPI ranks": execution.mpi_ranks,
                    "CPUs/rank": execution.cpus_per_rank,
                },
                depends_on=("validate_input",),
                event="START",
                started=started_at,
                command=_resolved_command(plan["execution_spec"]),
            ),)),
        ),
    )
    _exclusive_json(attempt_dir / "plan.json", plan)
    valid_input, input_findings = _validated_input(fdf)
    _exclusive_json(
        attempt_dir / "input_validation.json",
        {"status": "PASS" if valid_input else "FAIL", "findings": input_findings},
    )
    stdout = attempt_dir / "stdout.txt"
    stderr = attempt_dir / "stderr.txt"
    outcome: StepOutcome | None = None
    staged_fdf: Path | None = None
    launch_error: str | None = None
    try:
        staged_fdf = _stage_inputs(fdf, pseudo_manifest, attempt_dir)
        if valid_input:
            launch_spec = StepLaunchSpec(
                task_id="run_siesta",
                attempt_id=attempt_id,
                workdir=attempt_dir,
                input_path=staged_fdf,
                stdout_path=stdout,
                stderr_path=stderr,
                mpi_processes=execution.mpi_ranks,
                cpus_per_process=execution.cpus_per_rank,
                executable=execution.executable,
                executable_arguments=execution.executable_arguments,
                environment=execution.environment,
            )
            outcome = _launch(execution, launch_spec)
        else:
            stdout.write_text("", encoding="utf-8", newline="\n")
            stderr.write_text("QRAFT input validation failed before launch\n", encoding="utf-8", newline="\n")
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
        if not stdout.exists():
            stdout.write_text("", encoding="utf-8", newline="\n")
        if not stderr.exists():
            stderr.write_text(launch_error + "\n", encoding="utf-8", newline="\n")

    exit_code = outcome.exit_code if outcome is not None else None
    technical = validate_technical_result(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        required_artifacts=(attempt_dir / "input_validation.json",),
    )
    reasons = list(technical.reasons)
    if not valid_input:
        reasons.append("INPUT_VALIDATION_FAILED")
    if launch_error:
        reasons.append(f"LAUNCH_ERROR:{launch_error}")
    if reasons != list(technical.reasons):
        technical = TechnicalValidation(
            "FAIL", technical.classification, tuple(reasons), technical.parser_summary
        )
    artifacts = {
        path.name: _sha_path(path)
        for path in (stdout, stderr, attempt_dir / "input_validation.json", attempt_dir / "plan.json")
        if path.is_file()
    }
    attempt = Attempt(
        node_id="run_siesta",
        attempt_id=attempt_id,
        scientific_identity_sha256=scientific_fingerprint,
        execution_spec_sha256=execution.fingerprint,
        started_at=started_at,
        finished_at=_utc_now(),
        stdout="stdout.txt",
        stderr="stderr.txt",
        exit_code=exit_code,
        artifacts=artifacts,
        result=NodeResult(
            execution_state="COMPLETED" if outcome is not None else "FAILED",
            technical_validation=technical,
        ),
    )
    attempt_manifest = attempt_dir / "attempt.json"
    _exclusive_json(attempt_manifest, attempt.to_dict())
    attempt_manifest_sha256 = _sha_path(attempt_manifest)
    _exclusive_json(
        attempt_dir / "attempt.sha256.json",
        {"algorithm": "sha256", "sha256": attempt_manifest_sha256},
    )
    state = {
        "schema_version": "1.0",
        "single_writer": "controller",
        "latest_attempt_id": attempt_id,
        "scientific_identity_sha256": scientific_fingerprint,
        "attempt_manifest_sha256": attempt_manifest_sha256,
        "technical_status": technical.status,
        "updated_at": _utc_now(),
    }
    _atomic_json(run_root / "state.json", state)
    _event(
        events,
        "ATTEMPT_FINISHED",
        node_id="run_siesta",
        attempt_id=attempt_id,
        technical_status=technical.status,
        execution_state=attempt.result.execution_state,
    )
    messages = tuple(
        OutputMessage(
            "ERROR" if technical.status == "FAIL" else "REVIEW_REQUIRED",
            reason,
            code=reason.split(":", 1)[0],
            node_id="run_siesta",
            attempt_id=attempt_id,
            paths={"stdout": str(stdout), "stderr": str(stderr), "evidence": str(attempt_manifest)},
            details={
                "Technical state": technical.status,
                "DAG action": (
                    "NODE VALIDATED"
                    if technical.status == "PASS"
                    else "CAMPAIGN FAILED; NODE NOT REUSABLE"
                ),
            },
        )
        for reason in technical.reasons
    )
    _render_output(
        events,
        "node_finished",
        lambda: output_writer.append(
            "NODE RESULT",
            OutputModel(
                nodes=(NodeEntry(
                    node_id="run_siesta",
                    node_type="run_siesta",
                    attempt_id=attempt_id,
                    status=technical.status,
                    workdir=str(attempt_dir),
                    input_path=str(staged_fdf or fdf.resolve()),
                    stdout_path=str(stdout),
                    stderr_path=str(stderr),
                    evidence_path=str(attempt_manifest),
                    resources={"MPI ranks": execution.mpi_ranks},
                    depends_on=("validate_input",),
                    event="RESULT",
                    started=attempt.started_at,
                    finished=attempt.finished_at,
                    elapsed_seconds=outcome.elapsed_seconds if outcome is not None else None,
                    command=shlex.join(outcome.command) if outcome is not None else _resolved_command(plan["execution_spec"]),
                ),),
                metrics={
                    "exit_code": exit_code,
                    "technical status": technical.status,
                    "classification": technical.classification,
                    "SCF started": technical.parser_summary.get("scf_started"),
                    "SCF converged": technical.parser_summary.get("scf_converged"),
                    "normal termination": technical.parser_summary.get("normal_termination"),
                },
                paths={"stdout": str(stdout), "stderr": str(stderr), "attempt manifest": str(attempt_manifest)},
                messages=messages,
                diagnostic=(
                    {
                        "Classification": technical.classification,
                        "Exit code": exit_code,
                        "SCF started": technical.parser_summary.get("scf_started"),
                        "SCF converged": technical.parser_summary.get("scf_converged"),
                        "Normal end": technical.parser_summary.get("normal_termination"),
                        "Reason": "; ".join(technical.reasons),
                    }
                    if technical.status != "PASS" else {}
                ),
                relevant_output=(
                    _relevant_output((stdout, stderr))
                    if technical.status != "PASS" else ()
                ),
                decisions={"scientific decision": attempt.result.scientific_decision.value},
            ),
        ),
    )
    _render_output(
        events,
        "session_finished",
        lambda: output_writer.finish_session(
            result="COMPLETED" if technical.status == "PASS" else "FAILED",
            finished=_utc_now(),
            elapsed_seconds=time.monotonic() - session_clock,
        ),
    )
    _render_output(
        events,
        "summary",
        lambda: output_writer.finish({
            "Campaign status": "COMPLETED" if technical.status == "PASS" else "FAILED",
            "Nodes total": 1,
            "Validated": int(technical.status == "PASS"),
            "Failed": int(technical.status != "PASS"),
            "Blocked": 0,
            "Pending": 0,
            "Root": str(run_root),
            "QRAFT output": str(output_writer.path),
            "Evidence": str(events),
            "Resume": f"qraft run {fdf.resolve()}",
        }),
    )
    _event(
        events,
        "EXECUTION_SESSION_FINISHED",
        session_id=session_id,
        status="COMPLETED" if technical.status == "PASS" else "FAILED",
    )
    return {
        "status": "ATTEMPT_FINISHED",
        "attempt": attempt.to_dict(),
        "plan": plan,
        "qraft_output": str(output_writer.path),
    }


def _single_fdf_runtime_workflow(
    fdf: Path, *, pseudo_manifest: Path | None = None
) -> tuple[CompiledWorkflow, Path]:
    """Adapt one FDF input set into the canonical runtime's single node."""

    fdf_root, fdf_files, documents = _collect_fdf_files(fdf)
    pseudos = _resolve_pseudopotentials(
        fdf_root, _species(documents), pseudo_manifest
    )
    root_fdf = fdf.resolve()
    entries: list[tuple[str, Path, str, ArtifactRole, str]] = [
        ("fdf", root_fdf, root_fdf.name, ArtifactRole.INPUT, "application/x-siesta-fdf")
    ]
    for index, (relative, source) in enumerate(fdf_files.items(), start=1):
        if source.resolve() != root_fdf:
            entries.append((
                f"include-{index:03d}", source, relative,
                ArtifactRole.INPUT, "application/x-siesta-fdf",
            ))
    for index, source in enumerate(sorted(pseudos.values()), start=1):
        entries.append((
            f"pseudo-{index:03d}", source, source.name,
            ArtifactRole.PSEUDOPOTENTIAL, "application/x-siesta-pseudopotential",
        ))
    destinations = [item[2] for item in entries]
    if len(set(destinations)) != len(destinations):
        raise ValueError("single-FDF canonical input destinations collide")
    source_root = Path(os.path.commonpath([str(item[1].parent) for item in entries]))
    artifacts: list[ArtifactReference] = []
    bindings: list[WorkflowInputBinding] = []
    for index, (name, source, destination, role, media_type) in enumerate(entries, start=1):
        artifact_id = f"input-{index:03d}"
        artifacts.append(ArtifactReference(
            artifact_id=artifact_id,
            role=role,
            relative_path=source.resolve().relative_to(source_root).as_posix(),
            sha256=_sha_path(source),
            size_bytes=source.stat().st_size,
            media_type=media_type,
        ))
        bindings.append(WorkflowInputBinding(
            name=name,
            destination=destination,
            media_type=media_type,
            external_artifact_id=artifact_id,
        ))
    definition_sha256 = _canonical_sha({
        "protocol": "single_fdf",
        "inputs": [
            {"destination": item[2], "sha256": _sha_path(item[1])}
            for item in entries
        ],
    })
    task = WorkflowTaskNode(
        task_id="run_siesta",
        kind=WorkflowTaskKind.CALCULATION,
        capability_id=SIESTA_ENGINE_CAPABILITY,
        dependencies=(),
        inputs=tuple(bindings),
        outputs=(),
        resources={"max_attempts": 2},
        settings={"primary_input": "fdf"},
    )
    return CompiledWorkflow(
        workflow_id=f"single-fdf-{definition_sha256[:16]}",
        project_id="single-fdf",
        definition_sha256=definition_sha256,
        tasks=(task,),
        edges=(),
        external_artifacts=tuple(artifacts),
        metadata={"protocol": "single_fdf"},
    ), source_root


def _write_single_fdf_plan_failure(
    *,
    fdf: Path,
    runs_root: Path,
    events: Path,
    session_id: str,
    epoch: int,
    session_started: str,
    session_clock: float,
    command: str,
    initial_output_exists: bool,
    error: Exception,
) -> None:
    writer = QraftOutputWriter(runs_root / "qraft.out", campaign_root=runs_root)
    if not writer.exists:
        writer.initialize(OutputModel(
            header={"Version": QRAFT_VERSION, "Campaign": f"single_fdf:{fdf.stem}"},
            configuration={"engine": "siesta", "input FDF": str(fdf.resolve())},
            paths={"QRAFT output": str(writer.path), "Evidence": str(events)},
        ))
    _event(events, "PLAN_BUILD_FAILED", input_fdf=str(fdf.resolve()), error=f"{type(error).__name__}: {error}")
    writer.start_session(ExecutionSession(
        session_id, epoch, "RESUME" if initial_output_exists else "NEW", session_started,
        command, None, str(runs_root),
    ))
    writer.append("PLANNING FAILURE", OutputModel(messages=(OutputMessage(
        "BLOCKED", f"{type(error).__name__}: {error}", code="PLAN_BUILD_FAILED",
        node_id="plan", paths={"input": str(fdf.resolve()), "evidence": str(events)},
        details={"Technical state": "NOT_STARTED", "DAG action": "EXECUTION BLOCKED BEFORE ATTEMPT"},
    ),)))
    writer.finish_session(
        result="BLOCKED", finished=_utc_now(), elapsed_seconds=time.monotonic() - session_clock
    )
    writer.finish({"Campaign status": "BLOCKED", "Nodes total": 0, "Blocked": 1, "QRAFT output": str(writer.path), "Evidence": str(events)})
    _event(events, "EXECUTION_SESSION_FINISHED", session_id=session_id, status="BLOCKED")


def _single_fdf_public_attempt(attempt: Attempt) -> dict[str, Any]:
    """Map canonical evidence to the historical single-FDF result surface."""

    payload = attempt.to_dict()
    technical = payload["result"]["technical_validation"]
    if technical["status"] != "PASS":
        technical["status"] = "FAIL"
        payload["result"]["execution_state"] = "FAILED"
        if not technical["parser_summary"].get("normal_termination", False):
            technical["reasons"] = tuple(
                (*technical["reasons"], "NORMAL_TERMINATION_MISSING")
            )
    return payload


def execute_fdf_plan(
    fdf: Path,
    *,
    pseudo_manifest: Path | None = None,
    profile: Path | Mapping[str, Any] | None = None,
    project_config: Path | None = None,
    recipe: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    runs_root: Path = Path(".qraft-runs"),
    force_new_attempt: bool = False,
    invocation: str | None = None,
    profile_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run single-FDF work through the canonical workflow runtime only."""

    session_clock = time.monotonic()
    session_started = _utc_now()
    session_id = uuid.uuid4().hex
    resolved_runs = runs_root.resolve()
    events = resolved_runs / "events.jsonl"
    output_writer = QraftOutputWriter(
        resolved_runs / "qraft.out", campaign_root=resolved_runs
    )
    initial_output_exists = output_writer.exists
    epoch = _next_session_epoch(events)
    command = invocation or f"qraft run {shlex.quote(str(fdf))}"
    _event(
        events,
        "EXECUTION_SESSION_STARTED",
        session_id=session_id,
        controller_epoch=epoch,
        mode="RESUME" if initial_output_exists else "NEW",
        command=command,
    )
    try:
        plan = build_fdf_plan(
            fdf,
            pseudo_manifest=pseudo_manifest,
            profile=profile,
            project_config=project_config,
            recipe=recipe,
            overrides=overrides,
        )
        execution = ExecutionSpec(**{
            key: value
            for key, value in plan["execution_spec"].items()
            if key not in {"fingerprint", "ranks_per_node", "allocated_cpus"}
        })
        workflow, source_root = _single_fdf_runtime_workflow(
            fdf, pseudo_manifest=pseudo_manifest
        )
    except Exception as exc:
        _write_single_fdf_plan_failure(
            fdf=fdf, runs_root=resolved_runs, events=events, session_id=session_id,
            epoch=epoch, session_started=session_started, session_clock=session_clock,
            command=command, initial_output_exists=initial_output_exists, error=exc,
        )
        raise

    registry = CapabilityRegistry()
    register_siesta_engine(registry)
    registry.freeze()
    composition = compose_runtime(execution, max_parallel_steps=1)
    runtime_key = _canonical_sha({
        "scientific": plan["scientific_identity"]["fingerprint"],
        "execution": execution.fingerprint,
    })[:16]
    runtime_root = resolved_runs / "runtime" / runtime_key
    runtime_result = CompiledWorkflowRuntime(
        workflow=workflow,
        registry=registry,
        root=runtime_root,
        source_root=source_root,
        scientific_identities={
            "run_siesta": build_scientific_identity(
                fdf, pseudo_manifest=pseudo_manifest
            )
        },
        execution_specs=execution,
        launcher=composition.launcher,
        allocation=composition.allocation,
        force_new_attempts=force_new_attempt,
    ).run()

    attempt = runtime_result.attempts.get("run_siesta")
    if attempt is None:
        raise RuntimeError("canonical single-FDF runtime produced no attempt")
    reused = "run_siesta" in runtime_result.reused_nodes
    technical = attempt.result.technical_validation
    public_attempt = _single_fdf_public_attempt(attempt)
    public_technical = public_attempt["result"]["technical_validation"]
    public_status = str(public_technical["status"])
    attempt_root = runtime_root / "work" / attempt.node_id / attempt.attempt_id
    stdout = attempt_root / attempt.stdout
    stderr = attempt_root / attempt.stderr
    manifest = attempt_root / "attempt.json"
    writer = output_writer
    output_existed = initial_output_exists
    start_model = _single_fdf_start_model(
        plan, fdf, resolved_runs, profile_metadata=profile_metadata
    )
    if not output_existed:
        writer.initialize(OutputModel(header=start_model.header))
    mode = "RECOVERY" if reused else "RESUME" if output_existed else "NEW"
    writer.start_session(ExecutionSession(
        session_id, epoch, mode, session_started, command, None, str(resolved_runs)
    ), start_model)
    writer.append("NODE START", OutputModel(nodes=(NodeEntry(
        node_id="run_siesta", node_type="run_siesta", attempt_id=attempt.attempt_id,
        status="RUNNING", workdir=str(attempt_root), input_path=str(fdf.resolve()),
        stdout_path=str(stdout), stderr_path=str(stderr), evidence_path=str(manifest),
        resources={"Nodes": execution.nodes, "MPI ranks": execution.mpi_ranks, "CPUs/rank": execution.cpus_per_rank},
        depends_on=("validate_input",), event="START", started=attempt.started_at,
        command=_resolved_command(plan["execution_spec"]),
    ),)))
    if reused:
        writer.append_recovery({
            "Node": "run_siesta", "Attempt": attempt.attempt_id,
            "Action": "REUSED_VALIDATED_ATTEMPT",
            "Result": "no SIESTA relaunch required", "Evidence": str(manifest),
        })
    messages = tuple(OutputMessage(
        "ERROR" if public_status == "FAIL" else "REVIEW_REQUIRED", reason,
        code=reason.split(":", 1)[0], node_id="run_siesta", attempt_id=attempt.attempt_id,
        paths={"stdout": str(stdout), "stderr": str(stderr), "evidence": str(manifest)},
        details={"Technical state": public_status, "DAG action": "NODE VALIDATED" if public_status == "PASS" else "CAMPAIGN FAILED; NODE NOT REUSABLE"},
    ) for reason in public_technical["reasons"])
    writer.append("NODE RESULT", OutputModel(
        nodes=(NodeEntry(
            node_id="run_siesta", node_type="run_siesta", attempt_id=attempt.attempt_id,
            status=public_status, workdir=str(attempt_root), input_path=str(fdf.resolve()),
            stdout_path=str(stdout), stderr_path=str(stderr), evidence_path=str(manifest),
            resources={"MPI ranks": execution.mpi_ranks}, depends_on=("validate_input",),
            event="RESULT", started=attempt.started_at, finished=attempt.finished_at,
            command=_resolved_command(plan["execution_spec"]),
        ),),
        metrics={"exit_code": attempt.exit_code, "technical status": public_status, "classification": technical.classification},
        paths={"stdout": str(stdout), "stderr": str(stderr), "attempt manifest": str(manifest)},
        messages=messages,
        diagnostic={"Classification": technical.classification, "Exit code": attempt.exit_code, "Reason": "; ".join(public_technical["reasons"])} if public_status != "PASS" else {},
        relevant_output=_relevant_output((stdout, stderr)) if public_status != "PASS" else (),
        decisions={"scientific decision": attempt.result.scientific_decision.value},
    ))
    completed = public_status == "PASS"
    writer.finish_session(
        result="COMPLETED" if completed else "FAILED", finished=_utc_now(),
        elapsed_seconds=time.monotonic() - session_clock,
    )
    writer.finish({
        "Campaign status": "COMPLETED" if completed else "FAILED",
        "Nodes total": 1, "Validated": int(completed), "Failed": int(not completed),
        "Blocked": 0, "Pending": 0, "Root": str(runtime_root),
        "QRAFT output": str(writer.path), "Evidence": str(events),
        "Resume": f"qraft run {fdf.resolve()}",
    })
    _event(events, "EXECUTION_SESSION_FINISHED", session_id=session_id, status="COMPLETED" if completed else "FAILED")
    return {
        "status": "REUSED_VALIDATED_ATTEMPT" if reused else "ATTEMPT_FINISHED",
        "attempt": public_attempt, "plan": plan, "qraft_output": str(writer.path),
    }
