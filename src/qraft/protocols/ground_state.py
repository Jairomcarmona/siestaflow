"""Stage-wise M6 scientific orchestration; execution remains capability-runtime owned."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from ..campaign_spec import CampaignSpec
from ..contracts import CapabilityRegistry, ContractEnvelope, SCIENTIFIC_ARTIFACT
from ..contracts.scientific import ScientificArtifactReference, ScientificAuthority
from ..engines.siesta.campaign_adapter import SiestaCampaignAdapter
from ..engines.siesta.ground_state import geometry_updates, system_label, validate_final_scf
from ..engines.siesta.magnetism import (
    magnetic_spin_from_fdf,
    magnetic_artifact_envelope,
    magnetic_evidence_scalar_updates,
    parse_magnetic_output,
    soc_pseudopotential_evidence,
)
from ..engines.siesta.output_parser import parse_final_scf_energy_evidence
from ..engines.siesta.input_closure import resolve_scientific_input_closure
from ..engines.siesta.relaxation import geometry_from_fdf
from ..execution.capability_plugins import SIESTA_ENGINE_CAPABILITY, register_siesta_engine
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.runtime_composition import compose_runtime
from ..workflows import WorkflowCompiler
from .chained_convergence import ChainedConvergenceProtocol
from .relaxation import RelaxationProtocol
from .single_fdf import build_scientific_identity, resolve_execution_spec


_PROFILE_TYPE = "siestaflow.numerical-profile"
_GEOMETRY_TYPE = "qraft.geometry"
_STATE_TYPE = "qraft.electronic-state"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, payload: Mapping[str, Any], *, immutable: bool = False) -> None:
    encoded = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"immutable handoff content mismatch: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8", newline="\n")


def _artifact(path: Path, reference: Any, *, artifact_type: str) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise ValueError(f"producer artifact is missing: {path}")
    file_sha = _sha(path)
    if file_sha != str(reference.sha256):
        raise ValueError("producer artifact file SHA-256 mismatch")
    raw = json.loads(path.read_text(encoding="utf-8"))
    envelope = ContractEnvelope.from_dict(raw, required_contract=SCIENTIFIC_ARTIFACT)
    payload = dict(envelope.payload)
    if payload.get("artifact_type") != artifact_type:
        raise ValueError("producer artifact type mismatch")
    if str(payload.get("authority")) != reference.authority.value:
        raise ValueError("producer artifact authority mismatch")
    if envelope.content_sha256 != str(reference.provenance_sha256):
        raise ValueError("producer artifact content SHA-256 mismatch")
    return raw, file_sha


def _profile(path: Path, result: Mapping[str, Any]) -> tuple[dict[str, Any], str, dict[str, tuple[Any, str | None]]]:
    reference = result.get("profile_reference")
    if result.get("status") != "COMPLETED" or reference is None:
        raise ValueError("numerical convergence did not publish a profile reference")
    if _sha(path) != str(result.get("numerical_profile_sha256", "")):
        raise ValueError("numerical profile producer file SHA-256 mismatch")
    raw = json.loads(path.read_text(encoding="utf-8"))
    envelope = ContractEnvelope.from_dict(raw, required_contract=SCIENTIFIC_ARTIFACT)
    payload = dict(envelope.payload)
    if payload.get("artifact_type") != _PROFILE_TYPE or envelope.content_sha256 != str(reference.sha256):
        raise ValueError("numerical profile reference mismatch")
    if payload.get("authority") not in {"PROVISIONAL", "APPROVED"}:
        raise ValueError("numerical profile authority is invalid")
    selections = payload.get("selections")
    if not isinstance(selections, Mapping):
        raise ValueError("numerical profile selections are invalid")
    resolved: dict[str, tuple[Any, str | None]] = {}
    for name, selection in selections.items():
        if not isinstance(selection, Mapping) or set(selection) != {"value", "unit", "selection_artifact_sha256", "selection_contract_sha256"}:
            raise ValueError("numerical profile selection schema is invalid")
        value = selection["value"]
        resolved[str(name)] = (tuple(value) if isinstance(value, list) else value, selection["unit"])
    basis = [name for name in resolved if name in {"basis_size", "basis_energy_shift"}]
    if len(basis) != 1 or "mesh_cutoff" not in resolved or "kpoints" not in resolved:
        raise ValueError("numerical profile must contain basis, mesh_cutoff, and kpoints")
    return raw, _sha(path), resolved


def _same_system(left: Path, right: Path, *, pseudo_manifest: Path | None, geometry: bool) -> None:
    first = build_scientific_identity(left, pseudo_manifest=pseudo_manifest)
    second = build_scientific_identity(right, pseudo_manifest=pseudo_manifest)
    fields = ("species_mapping_sha256", "pseudopotentials") + (("geometry_sha256",) if geometry else ())
    if any(getattr(first, field) != getattr(second, field) for field in fields):
        raise ValueError("M6 templates do not share the required scientific system")


def _same_magnetic_intent(*templates: Path) -> None:
    """Require one immutable supported M8 intent across all M6 templates."""

    specs = [magnetic_spin_from_fdf(path) for path in templates]
    if all(spec is None for spec in specs):
        return
    if any(spec is None for spec in specs):
        raise ValueError("M6 templates must either all declare the same M8 magnetic spin or all remain non-magnetic")
    reference = specs[0]
    assert reference is not None
    if any(spec is None or spec.canonical() != reference.canonical() for spec in specs[1:]):
        raise ValueError("M6 templates do not share the same M8 magnetic spin configuration")


class GroundStateProtocol:
    """Decides scientific stage progression but delegates every calculation."""

    def __init__(self, *, convergence: ChainedConvergenceProtocol | None = None, relaxation: RelaxationProtocol | None = None, adapter: SiestaCampaignAdapter | None = None) -> None:
        self.convergence = convergence or ChainedConvergenceProtocol()
        self.relaxation = relaxation or RelaxationProtocol()
        self.adapter = adapter or SiestaCampaignAdapter()

    def run(self, basis_campaign: CampaignSpec, mesh_campaign: CampaignSpec, kpoint_campaign: CampaignSpec, *, relaxation_fdf: Path, final_scf_fdf: Path, profile: Mapping[str, Any] | None = None, project_config: Path | None = None, recipe: Path | None = None, overrides: Mapping[str, Any] | None = None, runs_root: Path = Path(".qraft-ground-state"), force_new_attempt: bool = False) -> dict[str, Any]:
        root = runs_root.resolve()
        authoritative_manifest = basis_campaign.system.pseudo_manifest
        _same_magnetic_intent(basis_campaign.system.fdf, relaxation_fdf, final_scf_fdf)
        # SOC is accepted only after each scientific template independently
        # proves fully-relativistic PSML compatibility.  This stays protocol/
        # engine local and creates no execution authority.
        if getattr(magnetic_spin_from_fdf(basis_campaign.system.fdf), "spin_mode", None) == "spin-orbit":
            for template in (basis_campaign.system.fdf, relaxation_fdf, final_scf_fdf):
                soc_pseudopotential_evidence(template, pseudo_manifest=authoritative_manifest)
        _same_system(basis_campaign.system.fdf, relaxation_fdf, pseudo_manifest=authoritative_manifest, geometry=True)
        _same_system(basis_campaign.system.fdf, final_scf_fdf, pseudo_manifest=authoritative_manifest, geometry=False)
        source_atoms = geometry_from_fdf(basis_campaign.system.fdf)["atoms"]
        final_atoms = geometry_from_fdf(final_scf_fdf)["atoms"]
        if len(source_atoms) != len(final_atoms) or [item["species_index"] for item in source_atoms] != [item["species_index"] for item in final_atoms]:
            raise ValueError("final-SCF template atom/species ordering is incompatible")
        convergence = self.convergence.run(basis_campaign, mesh_campaign, kpoint_campaign, profile=profile, project_config=project_config, recipe=recipe, overrides=overrides, runs_root=root / "stages" / "numerical", force_new_attempt=force_new_attempt)
        if convergence.get("status") != "COMPLETED":
            return self._blocked("numerical-convergence", convergence=convergence)
        try:
            profile_raw, profile_sha, resolved = _profile(Path(str(convergence["numerical_profile"])), convergence)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._blocked("handoff-validation", convergence=convergence, reason=str(exc))
        relaxation_template_sha = _sha(relaxation_fdf)
        relaxation_input = root / "handoff" / "relaxation" / "input.fdf"
        relaxation_render = self.adapter.materialize_effective(relaxation_fdf, relaxation_input.parent, resolved=resolved, primary_destination="input.fdf")
        _stage_template_pseudos(relaxation_fdf, relaxation_input, authoritative_manifest)
        _json(root / "handoff" / "relaxation" / "input-evidence.json", {"template_sha256": relaxation_template_sha, "numerical_profile_file_sha256": profile_sha, "numerical_profile_content_sha256": profile_raw["content_sha256"], "rendered_fdf_sha256": _sha(relaxation_input), "rendered_closure_sha256": relaxation_render.closure_sha256, "rendered_closure_files": relaxation_render.file_sha256}, immutable=True)
        relaxation = self.relaxation.run(relaxation_input, pseudo_manifest=authoritative_manifest, profile=profile, project_config=project_config, recipe=recipe, overrides=overrides, runs_root=root / "stages" / "relaxation", force_new_attempt=force_new_attempt)
        if relaxation.get("technical_validation") != "PASS" or relaxation.get("scientific_decision") != "CONVERGED" or relaxation.get("geometry_reference") is None:
            return self._blocked("relaxation", convergence=convergence, relaxation=relaxation)
        try:
            attempt = relaxation["attempt"]
            geometry_path = root / "stages" / "relaxation" / "work" / "relax" / str(attempt["attempt_id"]) / "relaxed-geometry.json"
            geometry_raw, geometry_sha = _artifact(geometry_path, relaxation["geometry_reference"], artifact_type=_GEOMETRY_TYPE)
            geometry = geometry_raw["payload"]
            if geometry.get("representation") != "cartesian" or geometry.get("length_unit") != "Ang":
                raise ValueError("relaxed geometry representation is invalid")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._blocked("handoff-validation", convergence=convergence, relaxation=relaxation, reason=str(exc))
        final_template_sha = _sha(final_scf_fdf)
        final_input = root / "handoff" / "final-scf" / "input.fdf"
        geometry_render = geometry_updates(geometry)
        final_scalars = {**geometry_render["scalars"], **magnetic_evidence_scalar_updates(final_scf_fdf)}
        final_render = self.adapter.materialize_effective(final_scf_fdf, final_input.parent, resolved=resolved, scalar_updates=final_scalars, block_updates=geometry_render["blocks"], primary_destination="input.fdf")
        _stage_template_pseudos(final_scf_fdf, final_input, authoritative_manifest)
        try:
            validate_final_scf(final_input, pseudo_manifest=authoritative_manifest)
        except ValueError as exc:
            return self._blocked("final-scf", convergence=convergence, relaxation=relaxation, reason=str(exc))
        _json(root / "handoff" / "final-scf" / "input-evidence.json", {"template_sha256": final_template_sha, "numerical_profile_file_sha256": profile_sha, "numerical_profile_content_sha256": profile_raw["content_sha256"], "geometry_file_sha256": geometry_sha, "geometry_content_sha256": geometry_raw["content_sha256"], "rendered_fdf_sha256": _sha(final_input), "rendered_closure_sha256": final_render.closure_sha256, "rendered_closure_files": final_render.file_sha256}, immutable=True)
        final = self._run_final_scf(final_input, pseudo_manifest=authoritative_manifest, profile=profile, project_config=project_config, recipe=recipe, overrides=overrides, root=root / "stages" / "final-scf", state_root=root, force_new_attempt=force_new_attempt)
        if final.get("technical_validation") != "PASS" or not final.get("scf_started") or not final.get("scf_converged") or not final.get("density_matrix"):
            return self._blocked("final-scf", convergence=convergence, relaxation=relaxation, final_scf=final)
        state_path = root / "electronic-state.json"
        final_state = {"scientific_identity_sha256": final["scientific_identity_sha256"], "input_fdf_sha256": _sha(final_input), "system_label": final["system_label"], "scf_converged": True, "scf_iterations": final["scf_iterations"], "density_matrix": final["density_matrix"]}
        if final.get("final_energy") is not None:
            final_state["final_energy"] = final["final_energy"]
        if final.get("magnetic") is not None:
            final_state["spin_mode"] = final["magnetic"]["spin_mode"]
            final_state["magnetic"] = final["magnetic"]
        state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="qraft.ground-state", payload={"schema_version": "1.0", "artifact_id": "ground-state", "artifact_type": _STATE_TYPE, "authority": "PROVISIONAL", "engine": "siesta", "numerical_profile": {"artifact_id": profile_raw["payload"]["artifact_id"], "artifact_type": _PROFILE_TYPE, "file_sha256": profile_sha, "content_sha256": profile_raw["content_sha256"]}, "geometry": {"artifact_id": geometry_raw["payload"]["artifact_id"], "artifact_type": _GEOMETRY_TYPE, "file_sha256": geometry_sha, "content_sha256": geometry_raw["content_sha256"]}, "final_scf": final_state, "provenance": {"final_scf_task_id": "final-scf", "final_scf_attempt_id": final["attempt_id"]}}).to_dict()
        _json(state_path, state, immutable=True)
        state_ref = ScientificArtifactReference("ground-state", _STATE_TYPE, _sha(state_path), state["content_sha256"], ScientificAuthority.PROVISIONAL)
        return {"schema_version": "1.0", "status": "COMPLETED", "numerical_convergence": convergence, "relaxation": relaxation, "final_scf": final, "electronic_state": str(state_path), "electronic_state_reference": state_ref}

    def _run_final_scf(self, fdf: Path, *, pseudo_manifest: Path | None, profile: Mapping[str, Any] | None, project_config: Path | None, recipe: Path | None, overrides: Mapping[str, Any] | None, root: Path, state_root: Path, force_new_attempt: bool) -> dict[str, Any]:
        closure = resolve_scientific_input_closure(fdf, pseudo_manifest=pseudo_manifest, primary_destination="input.fdf", include_pseudo_manifest=True)
        inputs = root / "inputs"; inputs.mkdir(parents=True, exist_ok=True)
        for entry in closure.entries:
            target = inputs / entry.destination; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(entry.source, target)
        execution, _ = resolve_execution_spec(profile=profile, project_config=project_config, recipe=recipe, overrides=overrides)
        label = system_label(fdf)
        definition = root / "workflow.json"
        bindings = [{"name": entry.name, "source": f"inputs/{entry.destination}", "destination": entry.destination, "media_type": entry.media_type} for entry in closure.entries]
        _json(definition, {"schema_version": "1.0", "workflow_id": "ground-state-final-scf", "project_id": "ground-state", "tasks": [{"task_id": "final-scf", "kind": "calculation", "capability": SIESTA_ENGINE_CAPABILITY, "inputs": bindings, "outputs": [{"name": "density-matrix", "path": f"{label}.DM", "artifact_type": "siesta.dm", "media_type": "application/octet-stream", "required": True}], "resources": {"nodes": execution.nodes, "mpi_processes": execution.mpi_ranks, "processes_per_node": execution.ranks_per_node, "cpus_per_process": execution.cpus_per_rank, "walltime_seconds": execution.walltime_seconds}, "settings": {"primary_input": "fdf"}}]})
        compiled = WorkflowCompiler().compile(definition)
        if not compiled.valid or compiled.compiled is None:
            raise ValueError("M6 final-SCF workflow compilation failed")
        registry = CapabilityRegistry(); register_siesta_engine(registry); registry.freeze()
        composition = compose_runtime(
            execution,
            max_parallel_steps=1,
            placement_probe_root=root,
        )
        identity = build_scientific_identity(fdf, pseudo_manifest=pseudo_manifest)
        requested_spin = magnetic_spin_from_fdf(fdf)
        soc_evidence = (
            soc_pseudopotential_evidence(fdf, pseudo_manifest=pseudo_manifest)
            if getattr(requested_spin, "spin_mode", None) == "spin-orbit"
            else None
        )
        runtime = CompiledWorkflowRuntime(workflow=compiled.compiled, registry=registry, root=root, source_root=root, scientific_identities={"final-scf": identity}, execution_specs=execution, launcher=composition.launcher, allocation=composition.allocation, force_new_attempts=force_new_attempt).run()
        attempt = runtime.attempts.get("final-scf")
        if attempt is None:
            return {"status": runtime.status, "technical_validation": "FAIL"}
        parsed = attempt.result.technical_validation.parser_summary
        dm_name = f"{label}.DM"; dm_sha = attempt.artifacts.get(dm_name)
        magnetic = None
        final_energy = None
        if attempt.result.technical_validation.status == "PASS" and bool(parsed.get("scf_converged")):
            try:
                attempt_root = root / "work" / "final-scf" / attempt.attempt_id
                stdout = attempt_root / attempt.stdout
                final_energy = parse_final_scf_energy_evidence(stdout).to_dict()
                final_energy["source_final_fdf_sha256"] = _sha(fdf)
            except (OSError, ValueError):
                # Final-energy evidence is additive.  Historic and synthetic M6
                # states remain valid even when their output lacks this native
                # SIESTA-specific final-energy dialect.
                final_energy = None
        if requested_spin is not None and attempt.result.technical_validation.status == "PASS" and bool(parsed.get("scf_converged")):
            try:
                attempt_root = root / "work" / "final-scf" / attempt.attempt_id
                stdout = attempt_root / attempt.stdout
                observed = parse_magnetic_output(
                    stdout.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True),
                    requested=requested_spin,
                    scf_converged=True,
                    required_atom_count=len(geometry_from_fdf(fdf)["atoms"]),
                )
                magnetic_raw = magnetic_artifact_envelope(
                    parent_scientific_identity_sha256=identity.fingerprint,
                    requested=requested_spin,
                    observed=observed,
                    final_fdf=fdf,
                    stdout=stdout,
                    scf_converged=True,
                    siesta_version=(str(parsed["version"]) if parsed.get("version") else None),
                    stdout_relative_path=stdout.resolve().relative_to(state_root.resolve()).as_posix(),
                    soc_pseudo_evidence=soc_evidence,
                )
                magnetic_path = attempt_root / "magnetic-state.json"
                _json(magnetic_path, magnetic_raw, immutable=True)
                magnetic = {
                    "spin_mode": requested_spin.spin_mode,
                    "requested": requested_spin.canonical(),
                    "observed": observed.canonical(),
                    "artifact": {
                        "artifact_type": "qraft.magnetic-state",
                        "relative_path": magnetic_path.resolve().relative_to(state_root.resolve()).as_posix(),
                        "sha256": _sha(magnetic_path),
                        "content_sha256": magnetic_raw["content_sha256"],
                    },
                }
            except (OSError, ValueError) as exc:
                return {"status": "FAILED", "technical_validation": "FAIL", "attempt_id": attempt.attempt_id, "reused": "final-scf" in runtime.reused_nodes, "scientific_identity_sha256": identity.fingerprint, "system_label": label, "scf_started": bool(parsed.get("scf_started")), "scf_converged": bool(parsed.get("scf_converged")), "scf_iterations": int(parsed.get("scf_iterations") or 0), "density_matrix": {"filename": dm_name, "sha256": dm_sha} if dm_sha else None, "magnetic": None, "magnetic_error": str(exc)}
        return {"status": "COMPLETED" if attempt.result.technical_validation.status == "PASS" else "FAILED", "technical_validation": attempt.result.technical_validation.status, "attempt_id": attempt.attempt_id, "reused": "final-scf" in runtime.reused_nodes, "scientific_identity_sha256": identity.fingerprint, "system_label": label, "scf_started": bool(parsed.get("scf_started")), "scf_converged": bool(parsed.get("scf_converged")), "scf_iterations": int(parsed.get("scf_iterations") or 0), "density_matrix": {"filename": dm_name, "sha256": dm_sha} if dm_sha else None, "magnetic": magnetic, "final_energy": final_energy}

    @staticmethod
    def _blocked(stage: str, **stages: Any) -> dict[str, Any]:
        return {"schema_version": "1.0", "status": "BLOCKED", "blocking_stage": stage, **stages}


def _write_text_immutable(path: Path, text: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError(f"immutable rendered input mismatch: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _stage_template_closure(template: Path, rendered: Path, pseudo_manifest: Path | None) -> None:
    """Keep rendered templates self-contained without creating an execution path."""

    closure = resolve_scientific_input_closure(template, pseudo_manifest=pseudo_manifest)
    for entry in closure.entries:
        if entry.name == "fdf":
            continue
        target = rendered.parent / entry.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _sha(target) != _sha(entry.source):
            raise ValueError(f"rendered input closure collision: {target}")
        if not target.exists():
            shutil.copy2(entry.source, target)


def _stage_template_pseudos(template: Path, rendered: Path, pseudo_manifest: Path | None) -> None:
    """Keep pseudo bytes with a rendered closure without re-copying FDF files."""

    closure = resolve_scientific_input_closure(template, pseudo_manifest=pseudo_manifest, include_pseudo_manifest=True)
    for entry in closure.entries:
        if not (entry.name.startswith("pseudo-")):
            continue
        target = rendered.parent / entry.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _sha(target) != _sha(entry.source):
            raise ValueError(f"rendered input closure collision: {target}")
        if not target.exists():
            shutil.copy2(entry.source, target)
