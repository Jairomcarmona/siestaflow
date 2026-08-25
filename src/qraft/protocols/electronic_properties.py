"""M7 electronic-property fan-out protocol.

The protocol verifies an immutable M6 electronic state, prepares three
independent source closures, and delegates their execution to the already
accepted generic DAG runtime.  It intentionally owns no execution state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from ..contracts import CapabilityRegistry, ContractEnvelope, SCIENTIFIC_ARTIFACT
from ..contracts.scientific import ScientificAuthority
from ..core import ExecutionSpec, ScientificIdentity
from ..band_paths import BandPathPlanner, BandPathRequest, BandPathResolution, SymmetryPathProvider, SymmetryProviderUnavailable
from ..engines.siesta.band_paths import compile_band_path_proposal, structure_from_final_fdf, time_reversal_evidence_from_final_fdf
from ..symmetry import SeekPathProvider
from ..engines.siesta.electronic_properties import (
    BandPathSpec, DosSpec, PdosSpec, PropertySpec, PROPERTY_CAPABILITIES,
    PROPERTY_SUFFIXES, property_artifact_envelope, render_property_fdf,
    sha256_path, validate_property_neutral_parent, validate_property_output,
)
from ..engines.siesta.ground_state import system_label
from ..engines.siesta.input_closure import effective_species, resolve_pseudopotentials, resolve_scientific_input_closure
from ..engines.siesta.effective_fdf import resolve_effective_fdf
from ..execution.capability_plugins import register_siesta_electronic_properties
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.runtime_composition import compose_runtime
from ..protocols.single_fdf import build_scientific_identity, resolve_execution_spec
from ..workflows import WorkflowCompiler


_STATE_TYPE = "qraft.electronic-state"


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _immutable_copy(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError(f"immutable M7 source collision: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def _immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"immutable M7 source collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8", newline="\n")


def _state_relative_file(state_path: Path, value: object, *, field: str) -> Path:
    relative = Path(str(value))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"M7 magnetic {field} path must be relative to electronic-state")
    candidate = (state_path.parent / relative).resolve()
    try:
        candidate.relative_to(state_path.parent)
    except ValueError as exc:
        raise ValueError(f"M7 magnetic {field} path escapes electronic-state root") from exc
    if not candidate.is_file():
        raise ValueError(f"M7 magnetic {field} is missing")
    return candidate


def _sha256_hex(value: object, *, field: str) -> str:
    result = str(value).strip().lower()
    if len(result) != 64:
        raise ValueError(f"M7 magnetic {field} must be a SHA-256")
    try:
        int(result, 16)
    except ValueError as exc:
        raise ValueError(f"M7 magnetic {field} must be a SHA-256") from exc
    return result


@dataclass(frozen=True)
class ElectronicStateSource:
    """Verified protocol-local view of the M6 handoff and its immutable bytes."""

    state_path: Path
    final_fdf: Path
    density_matrix: Path
    pseudo_manifest: Path | None
    state_file_sha256: str
    state_content_sha256: str
    final_fdf_sha256: str
    density_matrix_sha256: str
    parent_scientific_identity_sha256: str
    label: str
    authority: ScientificAuthority
    pseudopotentials: Mapping[str, Path]
    spin_mode: str
    magnetic_state_content_sha256: str | None
    magnetic_state_file_sha256: str | None
    magnetic_stdout_sha256: str | None

    @classmethod
    def load(
        cls,
        state_path: Path,
        *,
        final_fdf: Path,
        density_matrix: Path,
        pseudo_manifest: Path | None = None,
    ) -> "ElectronicStateSource":
        state_path, final_fdf, density_matrix = state_path.resolve(), final_fdf.resolve(), density_matrix.resolve()
        if not state_path.is_file() or not final_fdf.is_file() or not density_matrix.is_file():
            raise ValueError("M7 electronic-state handoff files are required")
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        envelope = ContractEnvelope.from_dict(raw, required_contract=SCIENTIFIC_ARTIFACT)
        payload = dict(envelope.payload)
        if payload.get("artifact_type") != _STATE_TYPE:
            raise ValueError("M7 requires a qraft.electronic-state artifact")
        try:
            authority = ScientificAuthority(str(payload.get("authority")))
        except ValueError as exc:
            raise ValueError("M7 parent electronic-state authority is invalid") from exc
        final = payload.get("final_scf")
        if not isinstance(final, Mapping):
            raise ValueError("M7 electronic-state final_scf payload is invalid")
        final_sha = sha256_path(final_fdf)
        if final_sha != str(final.get("input_fdf_sha256", "")):
            raise ValueError("M7 final FDF SHA-256 does not match electronic-state evidence")
        label = system_label(final_fdf)
        if label != str(final.get("system_label", "")):
            raise ValueError("M7 SystemLabel does not match electronic-state evidence")
        dm = final.get("density_matrix")
        if not isinstance(dm, Mapping) or str(dm.get("filename", "")) != density_matrix.name:
            raise ValueError("M7 density-matrix filename does not match electronic-state evidence")
        dm_sha = sha256_path(density_matrix)
        if dm_sha != str(dm.get("sha256", "")):
            raise ValueError("M7 density-matrix SHA-256 does not match electronic-state evidence")
        parent_identity = str(final.get("scientific_identity_sha256", "")).strip().lower()
        if len(parent_identity) != 64:
            raise ValueError("M7 electronic-state lacks final-SCF scientific identity evidence")
        try:
            int(parent_identity, 16)
        except ValueError as exc:
            raise ValueError("M7 final-SCF scientific identity is invalid") from exc
        spin_mode = str(final.get("spin_mode", "non-polarized")).strip().casefold()
        if spin_mode not in {"non-polarized", "polarized", "non-collinear", "spin-orbit"}:
            raise ValueError("M7 parent electronic-state spin_mode is invalid")
        magnetic_content_sha = None
        magnetic_file_sha = None
        magnetic_stdout_sha = None
        soc_pseudos: Mapping[str, object] | None = None
        if spin_mode in {"polarized", "non-collinear", "spin-orbit"}:
            magnetic = final.get("magnetic")
            if not isinstance(magnetic, Mapping) or magnetic.get("spin_mode") != spin_mode:
                raise ValueError("M7 magnetic parent lacks evidence agreeing with its spin_mode")
            artifact = magnetic.get("artifact")
            if not isinstance(artifact, Mapping) or artifact.get("artifact_type") != "qraft.magnetic-state":
                raise ValueError("M7 magnetic parent artifact is invalid")
            magnetic_path = _state_relative_file(state_path, artifact.get("relative_path"), field="artifact")
            magnetic_file_sha = _sha256_hex(artifact.get("sha256"), field="artifact file hash")
            if sha256_path(magnetic_path) != magnetic_file_sha:
                raise ValueError("M7 magnetic parent artifact file SHA-256 mismatch")
            magnetic_content_sha = _sha256_hex(artifact.get("content_sha256"), field="artifact content hash")
            magnetic_raw = json.loads(magnetic_path.read_text(encoding="utf-8"))
            magnetic_envelope = ContractEnvelope.from_dict(magnetic_raw, required_contract=SCIENTIFIC_ARTIFACT)
            magnetic_payload = dict(magnetic_envelope.payload)
            if magnetic_envelope.content_sha256 != magnetic_content_sha:
                raise ValueError("M7 magnetic parent artifact content SHA-256 mismatch")
            if magnetic_payload.get("artifact_type") != "qraft.magnetic-state" or magnetic_payload.get("converged") is not True:
                raise ValueError("M7 magnetic parent artifact is not converged evidence")
            if str(magnetic_payload.get("parent_scientific_identity_sha256", "")).strip().lower() != parent_identity:
                raise ValueError("M7 magnetic parent artifact identity mismatch")
            source = magnetic_payload.get("source")
            if not isinstance(source, Mapping) or str(source.get("final_fdf_sha256", "")) != final_sha:
                raise ValueError("M7 magnetic parent artifact final-FDF evidence mismatch")
            stdout_path = _state_relative_file(state_path, source.get("stdout_relative_path"), field="stdout evidence")
            if sha256_path(stdout_path) != _sha256_hex(source.get("stdout_sha256"), field="stdout hash"):
                raise ValueError("M7 magnetic parent artifact stdout SHA-256 mismatch")
            magnetic_stdout_sha = _sha256_hex(source.get("stdout_sha256"), field="stdout hash")
            observed = magnetic_payload.get("observed")
            if not isinstance(observed, Mapping) or observed.get("spin_mode") != spin_mode:
                raise ValueError("M7 magnetic parent artifact observed state is invalid")
            if magnetic.get("requested") != magnetic_payload.get("requested") or magnetic.get("observed") != observed:
                raise ValueError("M7 magnetic parent summary disagrees with artifact")
            if spin_mode == "spin-orbit":
                soc = magnetic_payload.get("soc")
                if not isinstance(soc, Mapping) or soc.get("enabled") is not True or soc.get("implementation") != "full":
                    raise ValueError("M7 spin-orbit parent lacks full-SOC evidence")
                soc_pseudos = soc.get("pseudopotentials") if isinstance(soc.get("pseudopotentials"), Mapping) else None
                if not soc_pseudos:
                    raise ValueError("M7 spin-orbit parent lacks pseudopotential provenance")
        # Resolving the closure and pseudos here rejects include escapes,
        # incomplete closure bytes, and pseudo mismatches before compilation.
        effective = resolve_effective_fdf(final_fdf)
        pseudos = resolve_pseudopotentials(effective.source_root, effective_species(effective), pseudo_manifest)
        if spin_mode == "spin-orbit":
            assert soc_pseudos is not None
            if set(soc_pseudos) != set(pseudos):
                raise ValueError("M7 spin-orbit pseudopotential provenance does not match final-SCF inputs")
            for species, pseudo in pseudos.items():
                entry = soc_pseudos[species]
                if not isinstance(entry, Mapping) or entry.get("compatibility") != "FULLY_RELATIVISTIC":
                    raise ValueError("M7 spin-orbit pseudopotential provenance is not fully relativistic")
                if sha256_path(pseudo) != _sha256_hex(entry.get("sha256"), field="SOC pseudopotential hash"):
                    raise ValueError("M7 spin-orbit pseudopotential SHA-256 mismatch")
        recomputed = build_scientific_identity(final_fdf, pseudo_manifest=pseudo_manifest)
        if recomputed.fingerprint != parent_identity:
            raise ValueError("M7 final-SCF scientific identity does not match M6 evidence")
        validate_property_neutral_parent(final_fdf)
        return cls(
            state_path=state_path, final_fdf=final_fdf, density_matrix=density_matrix,
            pseudo_manifest=pseudo_manifest.resolve() if pseudo_manifest else None,
            state_file_sha256=sha256_path(state_path), state_content_sha256=envelope.content_sha256,
            final_fdf_sha256=final_sha, density_matrix_sha256=dm_sha,
            parent_scientific_identity_sha256=parent_identity, label=label,
            authority=authority, pseudopotentials=dict(pseudos), spin_mode=spin_mode,
            magnetic_state_content_sha256=magnetic_content_sha,
            magnetic_state_file_sha256=magnetic_file_sha,
            magnetic_stdout_sha256=magnetic_stdout_sha,
        )

    def identity_component(self) -> str:
        return _canonical_sha({
            "artifact_type": _STATE_TYPE,
            "state_file_sha256": self.state_file_sha256,
            "state_content_sha256": self.state_content_sha256,
            "density_matrix_sha256": self.density_matrix_sha256,
            "parent_scientific_identity_sha256": self.parent_scientific_identity_sha256,
            "spin_mode": self.spin_mode,
            "magnetic_state_content_sha256": self.magnetic_state_content_sha256,
            "magnetic_state_file_sha256": self.magnetic_state_file_sha256,
            "magnetic_stdout_sha256": self.magnetic_stdout_sha256,
        })

    def verify(self) -> "ElectronicStateSource":
        """Re-read all M6 evidence before source-package preparation."""

        current = ElectronicStateSource.load(
            self.state_path, final_fdf=self.final_fdf,
            density_matrix=self.density_matrix, pseudo_manifest=self.pseudo_manifest,
        )
        if current.identity_component() != self.identity_component() or current.final_fdf_sha256 != self.final_fdf_sha256:
            raise ValueError("M7 electronic-state handoff changed after verification")
        return current

    def provenance(self) -> dict[str, str]:
        return {
            "artifact_type": _STATE_TYPE, "authority": self.authority.value,
            "state_file_sha256": self.state_file_sha256,
            "state_content_sha256": self.state_content_sha256,
            "final_fdf_sha256": self.final_fdf_sha256,
            "density_matrix_filename": self.density_matrix.name,
            "density_matrix_sha256": self.density_matrix_sha256,
            "scientific_identity_sha256": self.parent_scientific_identity_sha256,
            "spin_mode": self.spin_mode,
            "magnetic_state_content_sha256": self.magnetic_state_content_sha256,
            "magnetic_state_file_sha256": self.magnetic_state_file_sha256,
            "magnetic_stdout_sha256": self.magnetic_stdout_sha256,
        }


@dataclass(frozen=True)
class PreparedElectronicProperties:
    source_root: Path
    workflow_path: Path
    compiled: Any
    identities: Mapping[str, ScientificIdentity]
    source: ElectronicStateSource
    specs: Mapping[str, PropertySpec]
    band_path_resolution: BandPathResolution | None = None


class ElectronicPropertiesProtocol:
    """Compile and run independent BANDS, DOS, and PDOS siblings from M6."""

    def prepare(
        self,
        source: ElectronicStateSource,
        *,
        bands: BandPathSpec | BandPathRequest,
        dos: DosSpec,
        pdos: PdosSpec,
        runs_root: Path = Path(".qraft-electronic-properties"),
        band_path_provider: SymmetryPathProvider | None = None,
    ) -> PreparedElectronicProperties:
        source = source.verify()
        resolved_bands, path_resolution = self._resolve_bands(source, bands, band_path_provider)
        specs: dict[str, PropertySpec] = {"bands": resolved_bands, "dos": dos, "pdos": pdos}
        root = runs_root.resolve()
        source_root = root / "source"
        identities: dict[str, ScientificIdentity] = {}
        for property_name, spec in specs.items():
            branch = source_root / property_name
            rendered = render_property_fdf(source.final_fdf, branch, property_name=property_name, spec=spec)
            # Pseudos and parent DM are declared independent external inputs.
            for pseudo in source.pseudopotentials.values():
                _immutable_copy(pseudo, branch / pseudo.name)
            _immutable_copy(source.density_matrix, branch / source.density_matrix.name)
            _immutable_copy(source.state_path, branch / "electronic-state.json")
            identity = build_scientific_identity(rendered.root_fdf)
            components = dict(identity.components)
            components["m7.parent_electronic_state"] = source.identity_component()
            components["m7.property_kind"] = _canonical_sha(property_name)
            components["m7.property_spec"] = spec.sha256
            identities[property_name] = ScientificIdentity(
                engine=identity.engine, effective_fdf_sha256=identity.effective_fdf_sha256,
                geometry_sha256=identity.geometry_sha256, species_mapping_sha256=identity.species_mapping_sha256,
                pseudopotentials=identity.pseudopotentials, components=components,
                included_scientific_files=identity.included_scientific_files,
            )
        if path_resolution is not None:
            _immutable_json(source_root / "bands" / "band-path-proposal.json", {
                **path_resolution.proposal.canonical(),
                "proposal_sha256": path_resolution.proposal.sha256,
                "band_path_spec": resolved_bands.canonical(),
                "band_path_spec_sha256": resolved_bands.sha256,
            })
        workflow_path = source_root / "workflow.json"
        _immutable_json(workflow_path, self._workflow_definition(source_root, source, specs))
        compiled_result = WorkflowCompiler().compile(workflow_path)
        if not compiled_result.valid or compiled_result.compiled is None:
            raise ValueError("M7 electronic-property workflow compilation failed: " + "; ".join(item.message for item in compiled_result.findings))
        return PreparedElectronicProperties(source_root, workflow_path, compiled_result.compiled, identities, source, specs, path_resolution)

    @staticmethod
    def _resolve_bands(
        source: ElectronicStateSource,
        bands: BandPathSpec | BandPathRequest,
        provider: SymmetryPathProvider | None,
    ) -> tuple[BandPathSpec, BandPathResolution | None]:
        if isinstance(bands, BandPathSpec):
            return bands, None
        authoritative_structure = structure_from_final_fdf(source.final_fdf)
        if bands.structure is not None and bands.structure.sha256 != authoritative_structure.sha256:
            raise ValueError("M7.1 requested geometry does not match the verified M6 final geometry")
        request = replace(bands, structure=authoritative_structure)
        if request.time_reversal == "auto":
            request = replace(request, time_reversal_evidence=time_reversal_evidence_from_final_fdf(source.final_fdf))
        resolved_provider = provider
        if request.mode.value != "manual" and resolved_provider is None:
            try:
                resolved_provider = SeekPathProvider()
            except SymmetryProviderUnavailable:
                # The planner turns absent optional dependencies into a stable,
                # explicit BLOCKED proposal rather than a raw ImportError.
                resolved_provider = None
        resolution = BandPathPlanner(resolved_provider).resolve(request, compile_band_path_proposal)
        if resolution.band_path_spec is None:
            raise ValueError(
                f"M7.1 {request.mode.value} band path is {resolution.proposal.status.value}: "
                f"{resolution.proposal.reason or 'scientific review is required'}"
            )
        if not isinstance(resolution.band_path_spec, BandPathSpec):
            raise ValueError("M7.1 band-path compiler returned an invalid SIESTA spec")
        return resolution.band_path_spec, resolution

    @staticmethod
    def _workflow_definition(source_root: Path, source: ElectronicStateSource, specs: Mapping[str, PropertySpec]) -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        for property_name in ("bands", "dos", "pdos"):
            branch = source_root / property_name
            fdf = branch / "input.fdf"
            closure = resolve_scientific_input_closure(fdf)
            inputs = [
                {"name": entry.name, "source": f"{property_name}/{entry.destination}", "destination": entry.destination,
                 "media_type": entry.media_type, "sha256": sha256_path(branch / entry.destination)}
                for entry in closure.entries
            ]
            inputs.extend((
                {"name": "parent-state", "source": f"{property_name}/electronic-state.json", "destination": ".qraft/electronic-state.json", "media_type": "application/json", "sha256": sha256_path(branch / "electronic-state.json")},
                {"name": "parent-dm", "source": f"{property_name}/{source.density_matrix.name}", "destination": source.density_matrix.name, "media_type": "application/octet-stream", "sha256": sha256_path(branch / source.density_matrix.name)},
            ))
            # The closure must not accidentally provide a duplicate DM input.
            if len({item["destination"] for item in inputs}) != len(inputs):
                raise ValueError("M7 external input destinations collide")
            spec = specs[property_name]
            output_name = f"{source.label}{PROPERTY_SUFFIXES[property_name]}"
            tasks.append({
                "task_id": property_name, "kind": "calculation", "capability": PROPERTY_CAPABILITIES[property_name],
                "depends_on": [], "inputs": inputs,
                "outputs": [{"name": "property-output", "path": output_name, "artifact_type": {"bands": "qraft.bands.raw", "dos": "qraft.dos.raw", "pdos": "qraft.pdos.raw"}[property_name], "media_type": "text/plain", "required": True}],
                "resources": {},
                "settings": {"primary_input": "fdf", "property": property_name, "expected_points": getattr(spec, "energy_points", None)},
            })
        return {
            "schema_version": "1.0", "workflow_id": "m7-electronic-properties", "project_id": "m7-electronic-properties",
            "metadata": {"protocol": "m7-electronic-property-fanout", "parent_electronic_state": source.identity_component()},
            "tasks": tasks,
        }

    def run(
        self,
        source: ElectronicStateSource,
        *,
        bands: BandPathSpec | BandPathRequest,
        dos: DosSpec,
        pdos: PdosSpec,
        profile: Mapping[str, Any] | Path | None = None,
        project_config: Path | None = None,
        recipe: Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        runs_root: Path = Path(".qraft-electronic-properties"),
        force_new_attempt: bool = False,
        band_path_provider: SymmetryPathProvider | None = None,
    ) -> dict[str, Any]:
        prepared = self.prepare(
            source, bands=bands, dos=dos, pdos=pdos, runs_root=runs_root,
            band_path_provider=band_path_provider,
        )
        execution, _ = resolve_execution_spec(profile=profile, project_config=project_config, recipe=recipe, overrides=overrides)
        registry = CapabilityRegistry()
        register_siesta_electronic_properties(registry)
        registry.freeze()
        composition = compose_runtime(execution, max_parallel_steps=3)
        root = Path(runs_root).resolve()
        runtime = CompiledWorkflowRuntime(
            workflow=prepared.compiled, registry=registry, root=root / "runtime", source_root=prepared.source_root,
            scientific_identities=prepared.identities, execution_specs=execution,
            launcher=composition.launcher, allocation=composition.allocation,
            force_new_attempts=force_new_attempt,
        ).run()
        branches: dict[str, dict[str, Any]] = {}
        for property_name in ("bands", "dos", "pdos"):
            attempt = runtime.attempts.get(property_name)
            branch: dict[str, Any] = {"status": "NOT_STARTED", "reused": property_name in runtime.reused_nodes}
            if attempt is not None:
                branch.update({"status": attempt.result.execution_state, "attempt_id": attempt.attempt_id,
                               "technical_validation": attempt.result.technical_validation.status,
                               "scientific_identity_sha256": prepared.identities[property_name].fingerprint})
                if attempt.result.execution_state == "COMPLETED" and attempt.result.technical_validation.status == "PASS":
                    raw = root / "runtime" / "work" / property_name / attempt.attempt_id / f"{source.label}{PROPERTY_SUFFIXES[property_name]}"
                    try:
                        validation = validate_property_output(raw, property_name, expected_points=getattr(prepared.specs[property_name], "energy_points", None))
                        artifact = property_artifact_envelope(
                            property_name=property_name, artifact_id=f"m7-{property_name}", parent=source.provenance(),
                            spec=prepared.specs[property_name], scientific_identity_sha256=prepared.identities[property_name].fingerprint,
                            rendered_fdf_sha256=sha256_path(prepared.source_root / property_name / "input.fdf"), raw_output=raw,
                            task_id=property_name, attempt_id=attempt.attempt_id, validation=validation,
                        )
                        artifact_path = root / "artifacts" / f"{property_name}.json"
                        _immutable_json(artifact_path, artifact)
                        branch["artifact"] = str(artifact_path)
                        branch["artifact_sha256"] = sha256_path(artifact_path)
                    except (OSError, ValueError) as exc:
                        branch.update({"status": "FAILED", "scientific_validation": "FAIL", "reason": str(exc)})
            branches[property_name] = branch
        completed = all(branch.get("status") == "COMPLETED" and "artifact" in branch for branch in branches.values())
        return {"schema_version": "1.0", "status": "COMPLETED" if completed else "FAILED", "workflow": str(prepared.workflow_path), "runtime_status": runtime.status, "branches": branches}
