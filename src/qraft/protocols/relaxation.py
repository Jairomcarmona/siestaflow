"""M5 fixed-cell relaxation through the canonical executable workflow runtime."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from ..contracts import CapabilityRegistry, ContractEnvelope, SCIENTIFIC_ARTIFACT
from ..contracts.scientific import ScientificArtifactReference, ScientificAuthority
from ..execution.capability_plugins import SIESTA_RELAX_CAPABILITY, register_siesta_relax
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.runtime_composition import compose_runtime
from ..workflows import WorkflowCompiler
from .single_fdf import build_scientific_identity, resolve_execution_spec
from ..engines.siesta.input_closure import resolve_scientific_input_closure
from ..engines.siesta.effective_fdf import resolve_effective_fdf
from ..engines.siesta.relaxation import geometry_envelope, geometry_from_fdf, validate_relaxation


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class RelaxationProtocol:
    def run(self, fdf: Path, *, pseudo_manifest: Path | None = None, profile: Mapping[str, Any] | None = None, project_config: Path | None = None, recipe: Path | None = None, overrides: Mapping[str, Any] | None = None, runs_root: Path = Path(".qraft-relax"), force_new_attempt: bool = False) -> dict[str, Any]:
        fdf = fdf.resolve()
        geometry = geometry_from_fdf(fdf)
        tolerance = validate_relaxation(fdf)
        root = runs_root.resolve()
        initial = geometry_envelope(artifact_id="initial-geometry", geometry=geometry, provenance={"source_fdf_sha256": geometry["source_fdf_sha256"]})
        closure = resolve_scientific_input_closure(fdf, pseudo_manifest=pseudo_manifest, primary_destination="input.fdf", include_pseudo_manifest=True)
        inputs = root / "inputs"; inputs.mkdir(parents=True, exist_ok=True)
        for entry in closure.entries:
            destination = inputs / entry.destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry.source, destination)
        initial_path = inputs / "initial-geometry.json"; _atomic_json(initial_path, initial)
        execution, _ = resolve_execution_spec(profile=profile, project_config=project_config, recipe=recipe, overrides=overrides)
        definition = root / "relaxation-workflow.json"
        label_scalar = resolve_effective_fdf(fdf).scalar("SystemLabel")
        label = label_scalar.value.strip() if label_scalar is not None and label_scalar.value.strip() else "siesta"
        workflow_inputs = [{"name": entry.name, "source": f"inputs/{entry.destination}", "destination": entry.destination, "media_type": entry.media_type} for entry in closure.entries]
        workflow_inputs.append({"name": "geometry", "source": "inputs/initial-geometry.json", "destination": "initial-geometry.json", "media_type": "application/json"})
        _atomic_json(definition, {"schema_version": "1.0", "workflow_id": "fixed-cell-relaxation", "project_id": "fixed-cell-relaxation", "description": "Canonical fixed-cell SIESTA relaxation", "metadata": {"protocol": "relaxation"}, "tasks": [{"task_id": "relax", "kind": "calculation", "capability": SIESTA_RELAX_CAPABILITY, "inputs": workflow_inputs, "outputs": [{"name": "geometry", "path": "relaxed-geometry.json", "artifact_type": "qraft.geometry", "media_type": "application/json", "required": True}, {"name": "struct_out", "path": f"{label}.STRUCT_OUT", "artifact_type": "siesta.struct-out", "media_type": "text/plain", "required": True}], "resources": {"nodes": execution.nodes, "mpi_processes": execution.mpi_ranks, "processes_per_node": execution.ranks_per_node, "cpus_per_process": execution.cpus_per_rank, "walltime_seconds": execution.walltime_seconds}, "settings": {"primary_input": "fdf", "input_geometry": initial}}]})
        compilation = WorkflowCompiler().compile(definition)
        if not compilation.valid or compilation.compiled is None:
            raise ValueError("M5 workflow compilation failed")
        registry = CapabilityRegistry(); register_siesta_relax(registry); registry.freeze()
        composition = compose_runtime(execution, max_parallel_steps=1)
        runtime = CompiledWorkflowRuntime(workflow=compilation.compiled, registry=registry, root=root, source_root=root, scientific_identities={"relax": build_scientific_identity(fdf, pseudo_manifest=pseudo_manifest)}, execution_specs=execution, launcher=composition.launcher, allocation=composition.allocation, force_new_attempts=force_new_attempt).run()
        attempt = runtime.attempts.get("relax")
        if attempt is None:
            return {"status": runtime.status, "technical_validation": "FAIL", "scientific_decision": "NOT_EVALUATED"}
        technical = attempt.result.technical_validation.status
        attempt_root = root / "work" / "relax" / attempt.attempt_id
        result: dict[str, Any] = {"status": "COMPLETED" if technical == "PASS" else "FAILED", "technical_validation": technical, "attempt": attempt.to_dict(), "reused": "relax" in runtime.reused_nodes, "scientific_decision": "NOT_EVALUATED"}
        geometry_path = attempt_root / "relaxed-geometry.json"
        if technical != "PASS" or not geometry_path.is_file():
            return result
        envelope = ContractEnvelope.from_dict(json.loads(geometry_path.read_text(encoding="utf-8")), required_contract=SCIENTIFIC_ARTIFACT)
        payload = envelope.payload
        if any(abs(payload["cell"][row][col] - geometry["cell"][row][col]) > 1e-6 for row in range(3) for col in range(3)):
            result.update({"status": "BLOCKED", "scientific_decision": "NOT_CONVERGED", "reason": "fixed-cell output drift"}); return result
        force = float(payload["provenance"]["force_ev_per_ang"])
        if force > tolerance:
            result.update({"scientific_decision": "NOT_CONVERGED", "max_force_ev_per_ang": force, "force_tolerance_ev_per_ang": tolerance}); return result
        digest = hashlib.sha256(geometry_path.read_bytes()).hexdigest()
        result.update({"scientific_decision": "CONVERGED", "max_force_ev_per_ang": force, "force_tolerance_ev_per_ang": tolerance, "geometry_reference": ScientificArtifactReference("relaxed-geometry", "qraft.geometry", digest, envelope.content_sha256, ScientificAuthority.PROVISIONAL)})
        return result
