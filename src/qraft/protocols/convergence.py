"""General one-axis numerical-convergence protocol built on ``single_fdf``."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import __version__
from ..campaign_spec import CampaignSpec, ParameterMode, PreflightSeverity, ScientificValue
from ..contracts import CapabilityRegistry
from ..engines.siesta.campaign_adapter import MaterializedFDF, SiestaCampaignAdapter
from ..engines.siesta.fdf_parser import FDFParser
from ..engines.siesta.input_validator import SiestaInputValidator
from ..engines.siesta.models import FDFBlock, FDFInclude
from ..models import DecisionStatus
from ..output import DagEntry, ExecutionSession, NodeEntry, OutputModel, OutputTable, QraftOutputWriter
from ..execution.capability_plugins import SIESTA_ENGINE_CAPABILITY, register_siesta_engine
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.resource_coordinator import CooperativeShutdown
from ..execution.runtime_composition import compose_runtime
from ..execution.slurm_environment import SignalHandlers
from ..workflows import WorkflowCompiler
from .single_fdf import build_scientific_identity, resolve_execution_spec


ALGORITHM = "qraft.convergence.v1"


def build_convergence_plan(
    campaign_file: Path, *, pseudo_manifest: Path | None = None,
    profile: Mapping[str, Any] | None = None, project_config: Path | None = None,
    recipe: Path | None = None, overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """ProtocolRegistry-compatible planner; campaign science owns its pseudos."""
    if pseudo_manifest is not None:
        raise ValueError("CampaignSpec declares its own pseudo_manifest")
    return ConvergenceProtocol().plan(
        CampaignSpec.load(campaign_file), profile=profile,
        project_config=project_config, recipe=recipe, overrides=overrides,
    )


def execute_convergence_plan(
    campaign_file: Path, *, pseudo_manifest: Path | None = None,
    profile: Mapping[str, Any] | None = None, project_config: Path | None = None,
    recipe: Path | None = None, overrides: Mapping[str, Any] | None = None,
    runs_root: Path = Path(".qraft-runs"), force_new_attempt: bool = False,
    invocation: str | None = None,
    profile_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """ProtocolRegistry-compatible runner backed by the campaign controller."""
    if pseudo_manifest is not None:
        raise ValueError("CampaignSpec declares its own pseudo_manifest")
    return ConvergenceProtocol().run(
        CampaignSpec.load(campaign_file), profile=profile,
        project_config=project_config, recipe=recipe, overrides=overrides,
        runs_root=runs_root, force_new_attempt=force_new_attempt,
        invocation=invocation, profile_metadata=profile_metadata,
    )


@dataclass(frozen=True)
class PreflightFinding:
    layer: str
    severity: PreflightSeverity
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"layer": self.layer, "severity": self.severity.value, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class ConvergencePoint:
    index: int
    value: ScientificValue
    technical_status: str
    energy_ev: float | None
    energy_per_atom_ev: float | None
    delta: float | None
    attempt_id: str | None
    fdf: str
    stdout: str | None
    stderr: str | None
    reused: bool = False


class ConvergenceProtocol:
    def __init__(self, adapter: SiestaCampaignAdapter | None = None) -> None:
        self.adapter = adapter or SiestaCampaignAdapter()

    def preflight(self, campaign: CampaignSpec) -> dict[str, Any]:
        findings: list[PreflightFinding] = []
        if not campaign.system.fdf.is_file():
            findings.append(PreflightFinding("universal", PreflightSeverity.ERROR, "FDF_MISSING", str(campaign.system.fdf)))
        else:
            validation = SiestaInputValidator().validate(FDFParser().parse_path(campaign.system.fdf))
            for item in validation.findings:
                severity = PreflightSeverity.ERROR if item.status in {DecisionStatus.FAIL, DecisionStatus.BLOCKED} else PreflightSeverity.WARNING
                findings.append(PreflightFinding("siesta", severity, item.code, item.message))
            for include in (
                node for node in FDFParser().parse_path(campaign.system.fdf).nodes
                if isinstance(node, FDFInclude)
            ):
                target = (campaign.system.fdf.parent / include.target).resolve()
                if not target.is_file():
                    findings.append(PreflightFinding("siesta", PreflightSeverity.ERROR, "INCLUDE_MISSING", str(target)))
            try:
                build_scientific_identity(
                    campaign.system.fdf,
                    pseudo_manifest=campaign.system.pseudo_manifest,
                )
            except (OSError, ValueError) as exc:
                findings.append(PreflightFinding("siesta", PreflightSeverity.ERROR, "SCIENTIFIC_INPUT_INCOMPLETE", str(exc)))
        for name, parameter in campaign.parameters.items():
            try:
                self.adapter.validate_parameter(name, parameter.unit)
                for value in parameter.resolved_values():
                    if parameter.mode in {ParameterMode.FIXED, ParameterMode.SCAN, ParameterMode.INHERIT}:
                        self.adapter._apply("", name, value, parameter.unit)
            except ValueError as exc:
                findings.append(PreflightFinding("protocol", PreflightSeverity.ERROR, "PARAMETER_INVALID", str(exc)))
            if parameter.mode is ParameterMode.INHERIT:
                evidence = Path(parameter.inheritance.evidence) if parameter.inheritance else Path("")
                if not evidence.is_absolute() and campaign.source is not None:
                    evidence = (campaign.source.parent / evidence).resolve()
                if not evidence.is_file():
                    findings.append(PreflightFinding("universal", parameter.severity, "INHERIT_EVIDENCE_MISSING", str(evidence)))
                elif parameter.inheritance and parameter.inheritance.evidence_sha256:
                    if _sha(evidence) != parameter.inheritance.evidence_sha256.casefold():
                        findings.append(PreflightFinding("universal", parameter.severity, "INHERIT_EVIDENCE_HASH_MISMATCH", str(evidence)))
                if parameter.inheritance and parameter.inheritance.compatible_identity and evidence.is_file():
                    identities = _evidence_identities(evidence)
                    if parameter.inheritance.compatible_identity not in identities:
                        findings.append(PreflightFinding("universal", parameter.severity, "INHERIT_IDENTITY_INCOMPATIBLE", str(evidence)))
            if parameter.mode is ParameterMode.AUTO_SUGGEST:
                findings.append(PreflightFinding("protocol", PreflightSeverity.ADVICE, "AUTO_SUGGEST_NOT_EXECUTED", parameter.suggestion or name))
        if campaign.system.fdf.is_file():
            try:
                self._variants(campaign)
            except (OSError, ValueError) as exc:
                findings.append(PreflightFinding("siesta", PreflightSeverity.ERROR, "VARIANT_MATERIALIZATION_FAILED", str(exc)))
        status = "BLOCKED" if any(item.severity is PreflightSeverity.ERROR for item in findings) else "PASS"
        return {"status": status, "findings": [item.to_dict() for item in findings]}

    def plan(
        self, campaign: CampaignSpec, *, profile: Mapping[str, Any] | None = None,
        project_config: Path | None = None, recipe: Path | None = None,
        overrides: Mapping[str, Any] | None = None, output_root: Path | None = None,
    ) -> dict[str, Any]:
        preflight = self.preflight(campaign)
        execution, provenance = resolve_execution_spec(profile=profile, project_config=project_config, recipe=recipe, overrides=overrides)
        variants = self._variants(campaign)
        dag = _dag(len(variants))
        root = (output_root or Path(".qraft-render") / campaign.campaign_id).resolve()
        return {
            "schema_version": "1.0", "status": "BLOCKED" if preflight["status"] != "PASS" else "EXECUTABLE_PLAN",
            "campaign_id": campaign.campaign_id, "protocol": "convergence", "engine": campaign.engine,
            "campaign_fingerprint": campaign.fingerprint, "parameter": campaign.scanned_parameter[0],
            "values": [item.value for item in variants], "variants": [
                {"node_id": f"point_{i:03d}", "value": item.value, "fdf": str(root / f"point_{i:03d}" / "input.fdf"), "sha256": item.sha256}
                for i, item in enumerate(variants, 1)
            ], "dag": dag, "execution_spec": execution.to_dict(), "configuration_sources": provenance,
            "preflight": preflight, "submitted": False,
        }

    def render(self, campaign: CampaignSpec, output_root: Path) -> dict[str, Any]:
        preflight = self.preflight(campaign)
        if preflight["status"] != "PASS":
            raise ValueError("campaign preflight contains ERROR findings")
        root = output_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        variants = self._variants(campaign)
        scan_name, scan = campaign.scanned_parameter
        fixed = {
            name: (parameter.resolved_values()[0], parameter.unit)
            for name, parameter in campaign.parameters.items()
            if parameter.mode in {ParameterMode.FIXED, ParameterMode.INHERIT}
        }
        paths: list[dict[str, Any]] = []
        for index, item in enumerate(variants, 1):
            point = root / f"point_{index:03d}"
            point.mkdir(parents=True, exist_ok=True)
            rendered = self.adapter.materialize_effective(
                campaign.system.fdf, point,
                resolved={**fixed, scan_name: (item.value, scan.unit)},
                engine_options=campaign.engine_options,
                primary_destination="input.fdf",
            )
            fdf = rendered.root_fdf
            generated_manifest = self._copy_dependencies(campaign, point)
            paths.append({"node_id": f"point_{index:03d}", "value": item.value, "fdf": str(fdf), "sha256": _sha(fdf), "closure_sha256": rendered.closure_sha256, "closure_files": rendered.file_sha256, "pseudo_manifest": str(generated_manifest) if generated_manifest else None})
        manifest = {"schema_version": "1.0", "campaign_id": campaign.campaign_id, "campaign_fingerprint": campaign.fingerprint, "parameter": campaign.scanned_parameter[0], "points": paths, "dag": _dag(len(paths))}
        _atomic_json(root / "render-manifest.json", manifest)
        return {"status": "RENDERED", "root": str(root), "manifest": str(root / "render-manifest.json"), "points": paths, "executed": False, "submitted": False}

    def run(
        self, campaign: CampaignSpec, *, profile: Mapping[str, Any] | None = None,
        project_config: Path | None = None, recipe: Path | None = None,
        overrides: Mapping[str, Any] | None = None, runs_root: Path = Path(".qraft-runs"),
        force_new_attempt: bool = False, invocation: str | None = None,
        profile_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        root = runs_root.resolve()
        rendered_root = root / "rendered"
        rendered = self.render(campaign, rendered_root)
        execution, _ = resolve_execution_spec(profile=profile, project_config=project_config, recipe=recipe, overrides=overrides)
        writer = QraftOutputWriter(root / "qraft.out", campaign_root=root)
        if not writer.exists:
            writer.initialize(OutputModel(header={"Version": __version__, "Campaign": campaign.campaign_id, "Protocol": "convergence", "Started": _utc_now()}))
        session_id = uuid.uuid4().hex
        writer.start_session(ExecutionSession(session_id, _next_epoch(root), "RESUME" if (root / "state" / "workflow_runtime.json").is_file() else "NEW", _utc_now(), invocation or f"qraft run {campaign.source}", None, str(root)), OutputModel(
            configuration={"campaign": str(campaign.source), "parameter scanned": campaign.scanned_parameter[0], "values": json.dumps(list(campaign.scanned_parameter[1].resolved_values())), "metric": campaign.criterion.metric, "criterion": campaign.criterion.delta, "consecutive": campaign.criterion.consecutive},
            execution={"partition": execution.partition, "nodes": execution.nodes, "MPI ranks": execution.mpi_ranks, "launcher": execution.launcher},
            dag=tuple(DagEntry(item["node_id"], item["kind"], "READY" if not item["depends_on"] else "WAITING", tuple(item["depends_on"])) for item in _dag(len(rendered["points"]))),
        ))
        definition = rendered_root / "convergence-workflow.json"
        _atomic_json(
            definition,
            self._workflow_definition(campaign, rendered["points"], execution),
        )
        compilation = WorkflowCompiler().compile(definition)
        if not compilation.valid or compilation.compiled is None:
            raise ValueError(
                "canonical convergence workflow compilation failed: "
                + "; ".join(item.code for item in compilation.report.findings)
            )
        identities = {
            item["node_id"]: build_scientific_identity(
                Path(item["fdf"]),
                pseudo_manifest=(
                    Path(item["pseudo_manifest"])
                    if item.get("pseudo_manifest")
                    else None
                ),
            )
            for item in rendered["points"]
        }
        registry = CapabilityRegistry()
        register_siesta_engine(registry)
        registry.freeze()
        composition = compose_runtime(
            execution,
            max_parallel_steps=1,
            placement_probe_root=root,
        )
        shutdown = CooperativeShutdown()
        runtime = CompiledWorkflowRuntime(
            workflow=compilation.compiled,
            registry=registry,
            root=root,
            source_root=rendered_root,
            scientific_identities=identities,
            execution_specs=execution,
            launcher=composition.launcher,
            allocation=composition.allocation,
            shutdown=shutdown,
            force_new_attempts=force_new_attempt,
        )
        with SignalHandlers(shutdown):
            runtime_result = runtime.run()
        points: list[ConvergencePoint] = []
        for index, item in enumerate(rendered["points"], 1):
            attempt = runtime_result.attempts.get(item["node_id"])
            if attempt is None:
                continue
            technical = (
                "PASS"
                if attempt.result.technical_validation.status == "PASS"
                else "FAIL"
            )
            attempt_dir = root / "work" / attempt.node_id / attempt.attempt_id
            stdout = attempt_dir / attempt.stdout
            stderr = attempt_dir / attempt.stderr
            energy = extract_total_energy(stdout) if technical == "PASS" else None
            atoms = _atom_count(Path(item["fdf"]))
            points.append(ConvergencePoint(index, item["value"], technical, energy, energy / atoms if energy is not None and atoms else None, None, attempt.attempt_id, item["fdf"], str(stdout), str(stderr), item["node_id"] in runtime_result.reused_nodes))
        if runtime_result.status != "COMPLETED":
            technical = "INCOMPLETE" if runtime_result.status == "INTERRUPTED" else "FAIL"
            writer.append("CONVERGENCE", OutputModel(
                nodes=tuple(NodeEntry(f"point_{point.index:03d}", "convergence_point", point.technical_status, point.attempt_id, input_path=point.fdf, stdout_path=point.stdout, stderr_path=point.stderr) for point in points),
                decisions={"execution state": runtime_result.status, "scientific decision": "NOT_EVALUATED"},
                paths={"workflow runtime state": str(root / "state" / "workflow_runtime.json")},
            ))
            writer.finish_session(result=runtime_result.status, finished=_utc_now(), elapsed_seconds=time.monotonic() - started)
            writer.finish({"Campaign status": runtime_result.status, "Technical validation": technical, "Scientific decision": "NOT_EVALUATED", "QRAFT output": str(root / "qraft.out"), "Workflow state": str(root / "state" / "workflow_runtime.json")})
            return {"status": runtime_result.status, "technical_validation": technical, "scientific_decision": "NOT_EVALUATED", "selected_point": None, "points": [asdict(point) for point in points], "result_manifest": None, "qraft_output": str(root / "qraft.out")}
        evaluated, decision, selected = evaluate_convergence(points, campaign.criterion.metric, campaign.criterion.delta, campaign.criterion.consecutive)
        all_technical = all(point.technical_status == "PASS" for point in evaluated)
        status = "COMPLETED" if all_technical else "FAILED"
        result_payload = {
            "schema_version": "1.0", "campaign_id": campaign.campaign_id, "campaign_fingerprint": campaign.fingerprint,
            "algorithm": ALGORITHM, "execution_state": status, "technical_validation": "PASS" if all_technical else "FAIL",
            "scientific_decision": decision, "selected_point": selected, "criterion": asdict(campaign.criterion),
            "points": [asdict(point) for point in evaluated], "render_manifest": rendered["manifest"],
        }
        _atomic_json(root / "campaign-result.json", result_payload)
        rows = tuple((str(point.value), point.energy_ev, point.energy_per_atom_ev, point.delta, point.technical_status, point.attempt_id, point.reused) for point in evaluated)
        writer.append("CONVERGENCE", OutputModel(
            nodes=tuple(NodeEntry(f"point_{point.index:03d}", "convergence_point", point.technical_status, point.attempt_id, input_path=point.fdf, stdout_path=point.stdout, stderr_path=point.stderr) for point in evaluated),
            tables=(OutputTable("convergence", ("value", "energy_eV", "energy_per_atom_eV", "delta", "technical_status", "attempt_id", "reused"), rows, unit=campaign.criterion.unit),) if rows else (),
            decisions={"criterion": campaign.criterion.delta, "metric": campaign.criterion.metric, "consecutive": campaign.criterion.consecutive, "scientific decision": decision, "selected point": str(selected) if selected is not None else None},
            paths={"render manifest": rendered["manifest"], "campaign result": str(root / "campaign-result.json")},
        ))
        writer.finish_session(result=status, finished=_utc_now(), elapsed_seconds=time.monotonic() - started)
        writer.finish({"Campaign status": status, "Technical validation": result_payload["technical_validation"], "Scientific decision": decision, "Selected": str(selected) if selected is not None else None, "QRAFT output": str(root / "qraft.out"), "Evidence": str(root / "campaign-result.json")})
        return {"status": status, "technical_validation": result_payload["technical_validation"], "scientific_decision": decision, "selected_point": selected, "points": result_payload["points"], "result_manifest": str(root / "campaign-result.json"), "qraft_output": str(root / "qraft.out")}

    def _variants(self, campaign: CampaignSpec) -> tuple[MaterializedFDF, ...]:
        scan_name, scan = campaign.scanned_parameter
        fixed = {name: (parameter.resolved_values()[0], parameter.unit) for name, parameter in campaign.parameters.items() if parameter.mode in {ParameterMode.FIXED, ParameterMode.INHERIT}}
        variants = []
        for value in scan.resolved_values():
            variants.append(self.adapter.materialize(campaign.system.fdf, scanned_name=scan_name, scanned_value=value, resolved={**fixed, scan_name: (value, scan.unit)}, engine_options=campaign.engine_options))
        return tuple(variants)

    @staticmethod
    def _workflow_definition(
        campaign: CampaignSpec,
        points: Sequence[Mapping[str, Any]],
        execution: Any,
    ) -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        for point in points:
            fdf = Path(str(point["fdf"])).resolve()
            point_root = fdf.parent
            inputs = [{
                "name": "fdf",
                "source": fdf.relative_to(point_root.parent).as_posix(),
                "destination": "input.fdf",
                "media_type": "application/x-siesta-fdf",
            }]
            for index, path in enumerate(sorted(point_root.rglob("*")), 1):
                if not path.is_file() or path.resolve() == fdf:
                    continue
                inputs.append({
                    "name": f"scientific_input_{index:03d}",
                    "source": path.relative_to(point_root.parent).as_posix(),
                    "destination": path.relative_to(point_root).as_posix(),
                    "media_type": "application/octet-stream",
                })
            tasks.append({
                "task_id": str(point["node_id"]),
                "kind": "calculation",
                "capability": SIESTA_ENGINE_CAPABILITY,
                "inputs": inputs,
                "outputs": [],
                "resources": {
                    "nodes": execution.nodes,
                    "mpi_processes": execution.mpi_ranks,
                    "processes_per_node": execution.ranks_per_node,
                    "cpus_per_process": execution.cpus_per_rank,
                    "walltime_seconds": execution.walltime_seconds,
                },
                "settings": {"primary_input": "fdf"},
            })
        return {
            "schema_version": "1.0",
            "workflow_id": f"{campaign.campaign_id}-convergence",
            "project_id": campaign.campaign_id,
            "description": "Canonical convergence point execution DAG",
            "metadata": {"protocol": "convergence", "scientific_policy": "external"},
            "tasks": tasks,
        }

    @staticmethod
    def _copy_dependencies(campaign: CampaignSpec, target: Path) -> Path | None:
        source_root = campaign.system.fdf.parent
        for path in source_root.iterdir():
            if path.is_file() and path.suffix.casefold() in {".psf", ".psml"}:
                destination = target / path.name
                if destination.exists() and _sha(destination) != _sha(path):
                    raise ValueError(f"render dependency collision: {destination}")
                if not destination.exists():
                    shutil.copy2(path, destination)
        if campaign.system.pseudo_manifest is None:
            return None
        data = _load_structured(campaign.system.pseudo_manifest)
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("pseudopotential manifest requires entries")
        generated: list[dict[str, str]] = []
        for entry in entries:
            source_value = entry.get("path") or entry.get("filename")
            if not source_value:
                raise ValueError("pseudopotential manifest entry lacks path")
            source = Path(str(source_value))
            if not source.is_absolute():
                source = (campaign.system.pseudo_manifest.parent / source).resolve()
            destination = target / source.name
            if destination.exists() and _sha(destination) != _sha(source):
                raise ValueError(f"render pseudopotential collision: {destination}")
            if not destination.exists():
                shutil.copy2(source, destination)
            generated.append({"species": str(entry["species"]), "filename": source.name})
        manifest = target / "pseudo-manifest.json"
        _atomic_json(manifest, {"schema_version": "1.0", "entries": generated})
        return manifest


def extract_total_energy(stdout: Path) -> float | None:
    if not stdout.is_file():
        return None
    patterns = (
        re.compile(r"(?i)siesta:\s*E_KS\(eV\)\s*=\s*([-+0-9.Ee]+)"),
        re.compile(r"(?i)(?:final\s+energy|total\s+energy|Etot)[^=:\n]*[=:]\s*([-+0-9.Ee]+)"),
    )
    values: list[float] = []
    text = stdout.read_text(encoding="utf-8", errors="replace")
    for pattern in patterns:
        values.extend(float(match.group(1)) for match in pattern.finditer(text))
        if values:
            break
    return values[-1] if values else None


def evaluate_convergence(points: Sequence[ConvergencePoint], metric: str, tolerance: float, consecutive: int) -> tuple[tuple[ConvergencePoint, ...], str, ScientificValue | None]:
    output: list[ConvergencePoint] = []
    previous: float | None = None
    streak = 0
    selected: ScientificValue | None = None
    for point in points:
        current = point.energy_ev if metric == "energy" else point.energy_per_atom_ev
        delta = abs(current - previous) if current is not None and previous is not None else None
        output.append(ConvergencePoint(**{**asdict(point), "delta": delta}))
        if current is None or point.technical_status != "PASS":
            streak = 0
            continue
        if delta is not None and delta <= tolerance:
            streak += 1
            if streak >= consecutive and selected is None:
                selected = point.value
        else:
            streak = 0
        previous = current
    return tuple(output), "CONVERGED" if selected is not None else "SCIENTIFIC_NOT_CONVERGED", selected


def _dag(points: int) -> list[dict[str, Any]]:
    dag = [{"node_id": "validate_campaign", "kind": "validate_campaign", "depends_on": []}, {"node_id": "render_variants", "kind": "render_variants", "depends_on": ["validate_campaign"]}]
    ids = []
    for index in range(1, points + 1):
        node = f"point_{index:03d}"; ids.append(node); dag.append({"node_id": node, "kind": "single_fdf", "depends_on": ["render_variants"]})
    dag.extend([{"node_id": "extract_metrics", "kind": "extract_metrics", "depends_on": ids}, {"node_id": "evaluate_convergence", "kind": "evaluate_convergence", "depends_on": ["extract_metrics"]}, {"node_id": "scientific_decision", "kind": "scientific_decision", "depends_on": ["evaluate_convergence"]}])
    return dag


def _atom_count(fdf: Path) -> int | None:
    match = re.search(r"(?im)^\s*NumberOfAtoms\s+(\d+)", fdf.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.casefold() == ".json" else __import__("yaml").safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"structured file must be a mapping: {path}")
    return value


def _evidence_identities(path: Path) -> set[str]:
    try:
        value: Any = _load_structured(path)
    except (OSError, ValueError):
        return set()
    found: set[str] = set()
    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"scientific_identity_sha256", "scientific_fingerprint", "fingerprint"} and isinstance(child, str):
                    found.add(child)
                visit(child)
        elif isinstance(item, list):
            for child in item: visit(child)
    visit(value)
    return found


def _write_if_equal_or_new(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise ValueError(f"idempotent render collision: {path}")
    if not path.exists():
        path.write_text(text, encoding="utf-8", newline="\n")


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _next_epoch(root: Path) -> int:
    path = root / "campaign-session-epoch"
    try: value = int(path.read_text(encoding="utf-8")) + 1
    except (OSError, ValueError): value = 1
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(str(value) + "\n", encoding="utf-8")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
