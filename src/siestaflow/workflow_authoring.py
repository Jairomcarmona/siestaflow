"""Application-facing scientific intent, capability, and recipe authoring.

The CLI is an adapter over this module.  Recipes build ordinary
WorkflowDefinition documents and never bypass the compiler or ``run prepare``.
"""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from .contracts import (
    CORE_CONTRACT_VERSION,
    SCIENTIFIC_INTENT,
    WORKFLOW_DEFINITION,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRegistry,
    PluginDescriptor,
    canonical_primitive,
)
from .project_packages import load_structured
from .scientific_convergence import MeshConvergenceRule, MeshObservation
from .scientific_kgrid import KGridConvergenceRule, KGridObservation
from .scientific_approvals import ApprovedNumericalProfile, load_approved_profile, load_decision
from .workflow_composition import (
    ArtifactPortContract,
    RecipePolicy,
    WorkflowComposer,
    WorkflowFragment,
)
from .contracts.workflow import require_local_id
from .engines.siesta.fdf_parser import FDFParser
from .workflows import WorkflowCompiler


MESH_EVALUATOR_CAPABILITY = "siestaflow.siesta.mesh-evidence-evaluator"
MESH_EVALUATION_RECIPE = "siestaflow.recipe.siesta.mesh-evidence-evaluation"
KGRID_EVALUATOR_CAPABILITY = "siestaflow.siesta.kgrid-evidence-evaluator"
KGRID_EVALUATION_RECIPE = "siestaflow.recipe.siesta.kgrid-evidence-evaluation"
OBSERVATION_PRODUCER_CAPABILITY = "siestaflow.siesta.observation-producer"
OBSERVATION_PRODUCTION_RECIPE = "siestaflow.recipe.siesta.observation-production"
SCIENTIFIC_COMPOSITION_RECIPE = "siestaflow.recipe.scientific.manual-composition"
STRUCTURAL_RELAXATION_CAPABILITY = "siestaflow.siesta.structural-relaxation"
STRUCTURAL_RELAXATION_RECIPE = "siestaflow.recipe.siesta.structural-relaxation"
CONVERGE_THEN_RELAX_CAPABILITY = "siestaflow.siesta.converge-then-relax"
CONVERGE_THEN_RELAX_RECIPE = "siestaflow.recipe.siesta.converge-then-relax"
DOS_PDOS_CAPABILITY = "siestaflow.siesta.dos-pdos"
DOS_PDOS_RECIPE = "siestaflow.recipe.siesta.dos-pdos"
GROUND_STATE_TO_DOS_PDOS_CAPABILITY = "siestaflow.siesta.ground-state-to-dos-pdos"
GROUND_STATE_TO_DOS_PDOS_RECIPE = "siestaflow.recipe.siesta.ground-state-to-dos-pdos"


def _relative(raw: object, *, field: str) -> str:
    text = str(raw)
    path = PurePosixPath(text.replace("\\", "/"))
    if not text or path.is_absolute() or ".." in path.parts or path.parts[0].endswith(":"):
        raise ValueError(f"{field} must be a safe relative path")
    return path.as_posix()


def _json_mapping(path: Path, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must be a portable JSON mapping: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a portable JSON mapping")
    return value


@dataclass(frozen=True)
class ScientificIntent:
    source: Path
    intent_id: str
    project_id: str
    recipe_id: str
    parameters: Mapping[str, Any]
    resources: Mapping[str, Any]
    metadata: Mapping[str, Any]
    sha256: str

    @classmethod
    def load(cls, path: Path) -> "ScientificIntent":
        source = path.resolve()
        raw = load_structured(source)
        expected = {
            "schema_version", "intent_id", "project_id", "recipe",
            "parameters", "resources", "metadata",
        }
        if set(raw) != expected or raw["schema_version"] != "1.0":
            raise ValueError("scientific intent schema mismatch")
        for field in ("parameters", "resources", "metadata"):
            if not isinstance(raw[field], Mapping):
                raise ValueError(f"scientific intent {field} must be a mapping")
            canonical_primitive(raw[field])
        identifiers = [str(raw[field]).strip() for field in ("intent_id", "project_id", "recipe")]
        if any(not item for item in identifiers):
            raise ValueError("scientific intent identifiers are required")
        return cls(
            source=source,
            intent_id=identifiers[0],
            project_id=identifiers[1],
            recipe_id=identifiers[2],
            parameters=dict(raw["parameters"]),
            resources=dict(raw["resources"]),
            metadata=dict(raw["metadata"]),
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )


class WorkflowTaskBuilder(Protocol):
    def build_task(self, intent: ScientificIntent) -> dict[str, Any]: ...


class WorkflowRecipe(Protocol):
    def build_workflow(
        self, intent: ScientificIntent, registry: CapabilityRegistry
    ) -> dict[str, Any]: ...


def _compose_single(
    intent: ScientificIntent,
    registry: CapabilityRegistry,
    *,
    capability_id: str,
    policy: RecipePolicy,
) -> dict[str, Any]:
    registered = registry.resolve(
        capability_id,
        required_inputs=(SCIENTIFIC_INTENT,),
        required_outputs=(WORKFLOW_DEFINITION,),
    )
    builder = registered.implementation
    build_fragment = getattr(builder, "build_fragment", None)
    if not callable(build_fragment):
        raise TypeError(f"composable workflow capability cannot build a fragment: {capability_id}")
    fragment = build_fragment(intent)
    if not isinstance(fragment, WorkflowFragment):
        raise TypeError(f"workflow capability returned an invalid fragment: {capability_id}")
    return WorkflowComposer().compose(intent, policy, (fragment,))


def _resources(value: Mapping[str, Any]) -> dict[str, int]:
    expected = {
        "nodes", "mpi_processes", "processes_per_node",
        "cpus_per_process", "walltime_seconds",
    }
    if set(value) != expected:
        raise ValueError("scientific intent resource fields mismatch")
    result: dict[str, int] = {}
    for field in sorted(expected):
        raw = value[field]
        if type(raw) is not int or raw <= 0:
            raise ValueError(f"resource {field} must be a positive integer")
        result[field] = raw
    if result["mpi_processes"] != result["nodes"] * result["processes_per_node"]:
        raise ValueError("resource rank placement mismatch")
    return result


class MeshEvidenceTaskBuilder:
    """Build the hash-bound evaluator task; it does not run SIESTA."""

    def build_task(self, intent: ScientificIntent) -> dict[str, Any]:
        if set(intent.parameters) != {"rule", "observations"}:
            raise ValueError("mesh evidence intent requires rule and observations")
        rule_relative = _relative(intent.parameters["rule"], field="parameters.rule")
        observations_raw = intent.parameters["observations"]
        if not isinstance(observations_raw, list) or not observations_raw:
            raise ValueError("parameters.observations must be a non-empty list")
        observation_paths = tuple(
            _relative(item, field="parameters.observations") for item in observations_raw
        )
        if len(set(observation_paths)) != len(observation_paths):
            raise ValueError("observation paths must be unique")
        root = intent.source.parent
        rule_data = _json_mapping(
            root / Path(*PurePosixPath(rule_relative).parts), field="parameters.rule"
        )
        rule = MeshConvergenceRule.from_mapping(rule_data)
        for relative in observation_paths:
            data = _json_mapping(
                root / Path(*PurePosixPath(relative).parts),
                field="parameters.observations",
            )
            MeshObservation.from_mapping(data)
        inputs: list[dict[str, Any]] = [{
            "name": "rule", "source": rule_relative, "destination": "rule.json",
            "media_type": "application/json",
        }]
        inputs.extend({
            "name": f"observation_{index:03d}", "source": relative,
            "destination": f"observations/{index:03d}.json",
            "media_type": "application/json",
        } for index, relative in enumerate(observation_paths, 1))
        return {
            "task_id": "evaluate_mesh_evidence",
            "kind": "validation",
            "capability": MESH_EVALUATOR_CAPABILITY,
            "inputs": inputs,
            "outputs": [{
                "name": "report", "path": "mesh-convergence-report.json",
                "artifact_type": "siestaflow.mesh-convergence-report",
                "media_type": "application/json", "required": True,
            }],
            "resources": _resources(intent.resources),
            "settings": {"rule_id": rule.rule_id},
        }

    def build_fragment(self, intent: ScientificIntent) -> WorkflowFragment:
        task = self.build_task(intent)
        observations = intent.parameters["observations"]
        return WorkflowFragment.single(
            "mesh-evidence-evaluation", task,
            input_contracts={
                "rule": ArtifactPortContract("siestaflow.mesh-convergence-rule", "application/json"),
                **{
                    f"observation_{index:03d}": ArtifactPortContract("siestaflow.mesh-observation", "application/json")
                    for index, _ in enumerate(observations, 1)
                },
            },
        )


class MeshEvidenceRecipe:
    def build_workflow(
        self, intent: ScientificIntent, registry: CapabilityRegistry
    ) -> dict[str, Any]:
        return _compose_single(
            intent, registry, capability_id=MESH_EVALUATOR_CAPABILITY,
            policy=RecipePolicy(
                MESH_EVALUATION_RECIPE, "1.0.0",
                "Evaluate hash-bound Mesh.Cutoff convergence evidence",
                "EVIDENCE_EVALUATION_ONLY",
            ),
        )


class KGridEvidenceTaskBuilder:
    """Build the hash-bound k-grid evaluator task; it does not run SIESTA."""

    def build_task(self, intent: ScientificIntent) -> dict[str, Any]:
        if set(intent.parameters) != {"rule", "observations"}:
            raise ValueError("k-grid evidence intent requires rule and observations")
        rule_relative = _relative(intent.parameters["rule"], field="parameters.rule")
        observations_raw = intent.parameters["observations"]
        if not isinstance(observations_raw, list) or not observations_raw:
            raise ValueError("parameters.observations must be a non-empty list")
        observation_paths = tuple(
            _relative(item, field="parameters.observations") for item in observations_raw
        )
        if len(set(observation_paths)) != len(observation_paths):
            raise ValueError("observation paths must be unique")
        root = intent.source.parent
        rule_data = _json_mapping(
            root / Path(*PurePosixPath(rule_relative).parts), field="parameters.rule"
        )
        rule = KGridConvergenceRule.from_mapping(rule_data)
        for relative in observation_paths:
            data = _json_mapping(
                root / Path(*PurePosixPath(relative).parts), field="parameters.observations"
            )
            KGridObservation.from_mapping(data)
        inputs: list[dict[str, Any]] = [{
            "name": "rule", "source": rule_relative, "destination": "rule.json",
            "media_type": "application/json",
        }]
        inputs.extend({
            "name": f"observation_{index:03d}", "source": relative,
            "destination": f"observations/{index:03d}.json",
            "media_type": "application/json",
        } for index, relative in enumerate(observation_paths, 1))
        return {
            "task_id": "evaluate_kgrid_evidence",
            "kind": "validation",
            "capability": KGRID_EVALUATOR_CAPABILITY,
            "inputs": inputs,
            "outputs": [{
                "name": "report", "path": "kgrid-convergence-report.json",
                "artifact_type": "siestaflow.kgrid-convergence-report",
                "media_type": "application/json", "required": True,
            }],
            "resources": _resources(intent.resources),
            "settings": {"rule_id": rule.rule_id},
        }

    def build_fragment(self, intent: ScientificIntent) -> WorkflowFragment:
        task = self.build_task(intent)
        observations = intent.parameters["observations"]
        return WorkflowFragment.single(
            "kgrid-evidence-evaluation", task,
            input_contracts={
                "rule": ArtifactPortContract("siestaflow.kgrid-convergence-rule", "application/json"),
                **{
                    f"observation_{index:03d}": ArtifactPortContract("siestaflow.kgrid-observation", "application/json")
                    for index, _ in enumerate(observations, 1)
                },
            },
        )


class KGridEvidenceRecipe:
    def build_workflow(
        self, intent: ScientificIntent, registry: CapabilityRegistry
    ) -> dict[str, Any]:
        return _compose_single(
            intent, registry, capability_id=KGRID_EVALUATOR_CAPABILITY,
            policy=RecipePolicy(
                KGRID_EVALUATION_RECIPE, "1.0.0",
                "Evaluate hash-bound k-grid convergence evidence",
                "EVIDENCE_EVALUATION_ONLY",
            ),
        )


class ObservationProducerTaskBuilder:
    """Build a postprocessor task from completed immutable SIESTA artifacts."""

    def build_task(self, intent: ScientificIntent) -> dict[str, Any]:
        expected = {"axis", "observation_id", "fdf", "stdout", "force_stress", "pseudopotential_manifest"}
        if set(intent.parameters) != expected:
            raise ValueError("observation production intent fields mismatch")
        axis = str(intent.parameters["axis"])
        if axis not in {"mesh", "kgrid"}:
            raise ValueError("observation production axis must be mesh or kgrid")
        observation_id = self._id(intent.parameters["observation_id"], field="observation_id")
        inputs = []
        for name, media_type in (
            ("fdf", "application/x-siesta-fdf"), ("stdout", "text/plain"),
            ("force_stress", "text/plain"), ("pseudopotential_manifest", "application/json"),
        ):
            source = _relative(intent.parameters[name], field=f"parameters.{name}")
            if not (intent.source.parent / Path(*PurePosixPath(source).parts)).is_file():
                raise ValueError(f"observation source is missing: {source}")
            inputs.append({"name": name, "source": source, "destination": f"input/{name}", "media_type": media_type})
        return {
            "task_id": "produce_observation", "kind": "postprocess",
            "capability": OBSERVATION_PRODUCER_CAPABILITY, "inputs": inputs,
            "outputs": [{"name": "observation", "path": "observation.json",
                         "artifact_type": f"siestaflow.{axis}-observation",
                         "media_type": "application/json", "required": True}],
            "resources": _resources(intent.resources),
            "settings": {"axis": axis, "observation_id": observation_id},
        }

    def build_fragment(self, intent: ScientificIntent) -> WorkflowFragment:
        task = self.build_task(intent)
        return WorkflowFragment.single(
            "observation-production", task,
            input_contracts={
                "fdf": ArtifactPortContract("siestaflow.siesta-fdf", "application/x-siesta-fdf"),
                "stdout": ArtifactPortContract("siestaflow.siesta-stdout", "text/plain"),
                "force_stress": ArtifactPortContract("siestaflow.siesta-force-stress", "text/plain"),
                "pseudopotential_manifest": ArtifactPortContract("siestaflow.pseudopotential-manifest", "application/json"),
            },
        )

    @staticmethod
    def _id(value: object, *, field: str) -> str:
        return _relative(value, field=field).replace("/", "-")


class ObservationProductionRecipe:
    def build_workflow(self, intent: ScientificIntent, registry: CapabilityRegistry) -> dict[str, Any]:
        return _compose_single(
            intent, registry, capability_id=OBSERVATION_PRODUCER_CAPABILITY,
            policy=RecipePolicy(
                OBSERVATION_PRODUCTION_RECIPE, "1.0.0",
                "Produce a hash-bound observation from completed SIESTA artifacts",
                "POSTPROCESSING_ONLY",
            ),
        )


def _module_intent(
    parent: ScientificIntent,
    raw: object,
    *,
    position: int,
) -> tuple[str, str, ScientificIntent]:
    """Derive a deterministic, in-memory intent for one selected module."""
    if not isinstance(raw, Mapping):
        raise ValueError("composition modules must be mappings")
    expected = {"module_id", "capability", "parameters", "resources", "metadata"}
    if set(raw) != expected:
        raise ValueError("composition module fields mismatch")
    module_id = require_local_id(str(raw["module_id"]), field_name="composition module id")
    capability_id = str(raw["capability"]).strip()
    if not capability_id:
        raise ValueError("composition module capability is required")
    for field in ("parameters", "resources", "metadata"):
        if not isinstance(raw[field], Mapping):
            raise ValueError(f"composition module {field} must be a mapping")
        canonical_primitive(raw[field])
    module_record = {
        "parent_intent_sha256": parent.sha256,
        "position": position,
        "module_id": module_id,
        "capability": capability_id,
        "parameters": dict(raw["parameters"]),
        "resources": dict(raw["resources"]),
        "metadata": dict(raw["metadata"]),
    }
    digest = hashlib.sha256(
        json.dumps(module_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return module_id, capability_id, ScientificIntent(
        source=parent.source,
        intent_id=f"{parent.intent_id}-{module_id}",
        project_id=parent.project_id,
        recipe_id=capability_id,
        parameters=dict(raw["parameters"]),
        resources=dict(raw["resources"]),
        metadata={**dict(parent.metadata), **dict(raw["metadata"]), "composition_module_id": module_id},
        sha256=digest,
    )


class ManualCompositionRecipe:
    """Compose an explicit subset of registered builders without authorizing a run."""

    def build_workflow(self, intent: ScientificIntent, registry: CapabilityRegistry) -> dict[str, Any]:
        if set(intent.parameters) != {"modules"}:
            raise ValueError("manual composition intent requires modules")
        modules = intent.parameters["modules"]
        if not isinstance(modules, list) or not modules:
            raise ValueError("composition modules must be a non-empty list")
        selected_modules = [
            _module_intent(intent, raw, position=position)
            for position, raw in enumerate(modules, 1)
        ]
        selected = [module_id for module_id, _, _ in selected_modules]
        if len(set(selected)) != len(selected):
            raise ValueError("composition module ids must be unique")
        fragments: list[WorkflowFragment] = []
        for _, capability_id, module_intent in selected_modules:
            registered = registry.resolve(
                capability_id,
                required_inputs=(SCIENTIFIC_INTENT,),
                required_outputs=(WORKFLOW_DEFINITION,),
            )
            if registered.descriptor.kind is not CapabilityKind.WORKFLOW_BUILDER:
                raise ValueError(f"composition capability is not a workflow builder: {capability_id}")
            build_fragment = getattr(registered.implementation, "build_fragment", None)
            if not callable(build_fragment):
                raise TypeError(f"composable workflow capability cannot build a fragment: {capability_id}")
            fragment = build_fragment(module_intent)
            if not isinstance(fragment, WorkflowFragment):
                raise TypeError(f"workflow capability returned an invalid fragment: {capability_id}")
            fragments.append(fragment)
        return WorkflowComposer().compose(
            intent,
            RecipePolicy(
                SCIENTIFIC_COMPOSITION_RECIPE, "1.0.0",
                "Researcher-selected composition of registered scientific modules",
                "USER_SELECTED_MODULES",
            ),
            tuple(fragments),
        )


class StructuralRelaxationTaskBuilder:
    """Build a SIESTA CG relaxation from an already declared scientific FDF."""

    _PARAMETERS = {"fdf", "pseudopotentials"}

    def build_task(self, intent: ScientificIntent) -> dict[str, Any]:
        if set(intent.parameters) != self._PARAMETERS:
            raise ValueError("structural relaxation intent requires fdf and pseudopotentials")
        fdf = _relative(intent.parameters["fdf"], field="parameters.fdf")
        root = intent.source.parent
        fdf_path = root / Path(*PurePosixPath(fdf).parts)
        if not fdf_path.is_file():
            raise ValueError(f"structural relaxation FDF is missing: {fdf}")
        label, expected_pseudos = self._relaxation_spec(fdf_path)
        pseudos = intent.parameters["pseudopotentials"]
        if not isinstance(pseudos, list) or not pseudos:
            raise ValueError("structural relaxation pseudopotentials must be a non-empty list")
        inputs: list[dict[str, Any]] = [{
            "name": "fdf", "source": fdf, "destination": "relax.fdf",
            "media_type": "application/x-siesta-fdf",
        }]
        destinations: set[str] = {"relax.fdf"}
        for index, item in enumerate(pseudos, 1):
            if not isinstance(item, Mapping) or set(item) != {"source", "destination"}:
                raise ValueError("each structural relaxation pseudopotential requires source and destination")
            source = _relative(item["source"], field="parameters.pseudopotentials.source")
            destination = _relative(item["destination"], field="parameters.pseudopotentials.destination")
            if not source.casefold().endswith(".psml"):
                raise ValueError("structural relaxation pseudopotentials must be PSML files")
            if not (root / Path(*PurePosixPath(source).parts)).is_file():
                raise ValueError(f"structural relaxation pseudopotential is missing: {source}")
            if destination in destinations:
                raise ValueError(f"structural relaxation input destination is duplicated: {destination}")
            destinations.add(destination)
            inputs.append({
                "name": f"pseudo_{index:03d}", "source": source,
                "destination": destination, "media_type": "application/x-psml",
            })
        if destinations - {"relax.fdf"} != set(expected_pseudos):
            raise ValueError(
                "structural relaxation pseudopotential destinations must match ChemicalSpeciesLabel"
            )
        return {
            "task_id": "relax_structure", "kind": "calculation",
            "capability": "siestaflow.engine.siesta", "inputs": inputs,
            "outputs": [{
                "name": "relaxed_structure", "path": f"{label}.XV",
                "artifact_type": "siestaflow.relaxed-structure",
                "media_type": "text/x-siesta-xv", "required": True,
            }],
            "resources": _resources(intent.resources), "settings": {},
        }

    def build_fragment(self, intent: ScientificIntent) -> WorkflowFragment:
        task = self.build_task(intent)
        return WorkflowFragment.single(
            "structural-relaxation", task,
            input_contracts={
                "fdf": ArtifactPortContract("siestaflow.siesta-relaxation-fdf", "application/x-siesta-fdf"),
                **{
                    f"pseudo_{index:03d}": ArtifactPortContract("siestaflow.pseudopotential", "application/x-psml")
                    for index, _ in enumerate(intent.parameters["pseudopotentials"], 1)
                },
            },
        )

    @staticmethod
    def _relaxation_spec(path: Path) -> tuple[str, tuple[str, ...]]:
        document = FDFParser().parse_path(path)
        run_type = document.scalars("MD.TypeOfRun")
        steps = document.scalars("MD.NumCGSteps")
        labels = document.scalars("SystemLabel")
        if len(run_type) != 1 or run_type[0].value.casefold() != "cg":
            raise ValueError("structural relaxation requires explicit MD.TypeOfRun CG")
        if len(steps) != 1:
            raise ValueError("structural relaxation requires explicit positive MD.NumCGSteps")
        try:
            if int(steps[0].value) <= 0:
                raise ValueError
        except ValueError as exc:
            raise ValueError("structural relaxation requires explicit positive MD.NumCGSteps") from exc
        if len(labels) != 1:
            raise ValueError("structural relaxation requires exactly one SystemLabel")
        species_blocks = document.blocks("ChemicalSpeciesLabel")
        if len(species_blocks) != 1:
            raise ValueError("structural relaxation requires exactly one ChemicalSpeciesLabel block")
        species_labels: set[str] = set()
        for raw in species_blocks[0].body_lines:
            row = raw.split("#", 1)[0].strip()
            if not row or row.startswith(("!", ";")):
                continue
            fields = row.split()
            if len(fields) < 3:
                raise ValueError("structural relaxation has an invalid ChemicalSpeciesLabel row")
            species_labels.add(require_local_id(fields[2], field_name="SIESTA species label"))
        if not species_labels:
            raise ValueError("structural relaxation requires ChemicalSpeciesLabel rows")
        return (
            require_local_id(labels[0].value, field_name="SIESTA SystemLabel"),
            tuple(f"{item}.psml" for item in sorted(species_labels)),
        )


class StructuralRelaxationRecipe:
    def build_workflow(self, intent: ScientificIntent, registry: CapabilityRegistry) -> dict[str, Any]:
        return _compose_single(
            intent, registry, capability_id=STRUCTURAL_RELAXATION_CAPABILITY,
            policy=RecipePolicy(
                STRUCTURAL_RELAXATION_RECIPE, "1.0.0",
                "Run a user-declared SIESTA structural relaxation",
                "STRUCTURAL_RELAXATION",
            ),
        )


class DOSPDOSTaskBuilder:
    """Build an explicit SIESTA DOS/PDOS analysis without choosing its physics.

    SIESTA computes total DOS as a side-product of ``ProjectedDensityOfStates``.
    The energy window, broadening, point count, k-point policy and FDF remain
    researcher-owned inputs.  This builder validates only the executable
    interface and declares the two produced artifacts for the canonical DAG.
    """

    _PARAMETERS = {"fdf", "pseudopotentials"}

    def build_task(self, intent: ScientificIntent) -> dict[str, Any]:
        if set(intent.parameters) != self._PARAMETERS:
            raise ValueError("dos_pdos intent requires fdf and pseudopotentials")
        fdf = _relative(intent.parameters["fdf"], field="parameters.fdf")
        root = intent.source.parent
        fdf_path = root / Path(*PurePosixPath(fdf).parts)
        if not fdf_path.is_file():
            raise ValueError(f"dos_pdos FDF is missing: {fdf}")
        label, expected_pseudos = self._analysis_spec(fdf_path)
        pseudos = intent.parameters["pseudopotentials"]
        if not isinstance(pseudos, list) or not pseudos:
            raise ValueError("dos_pdos pseudopotentials must be a non-empty list")
        inputs: list[dict[str, Any]] = [{
            "name": "fdf", "source": fdf, "destination": "dos-pdos.fdf",
            "media_type": "application/x-siesta-fdf",
        }]
        destinations: set[str] = {"dos-pdos.fdf"}
        for index, item in enumerate(pseudos, 1):
            if not isinstance(item, Mapping) or set(item) != {"source", "destination"}:
                raise ValueError("each dos_pdos pseudopotential requires source and destination")
            source = _relative(item["source"], field="parameters.pseudopotentials.source")
            destination = _relative(item["destination"], field="parameters.pseudopotentials.destination")
            if not source.casefold().endswith(".psml"):
                raise ValueError("dos_pdos pseudopotentials must be PSML files")
            if not (root / Path(*PurePosixPath(source).parts)).is_file():
                raise ValueError(f"dos_pdos pseudopotential is missing: {source}")
            if destination in destinations:
                raise ValueError(f"dos_pdos input destination is duplicated: {destination}")
            destinations.add(destination)
            inputs.append({
                "name": f"pseudo_{index:03d}", "source": source,
                "destination": destination, "media_type": "application/x-psml",
            })
        if destinations - {"dos-pdos.fdf"} != set(expected_pseudos):
            raise ValueError(
                "dos_pdos pseudopotential destinations must match ChemicalSpeciesLabel"
            )
        return {
            "task_id": "dos_pdos", "kind": "calculation",
            "capability": "siestaflow.engine.siesta", "inputs": inputs,
            "outputs": [
                {
                    "name": "total_dos", "path": f"{label}.DOS",
                    "artifact_type": "siestaflow.total-density-of-states",
                    "media_type": "text/plain", "required": True,
                },
                {
                    "name": "projected_dos", "path": f"{label}.PDOS",
                    "artifact_type": "siestaflow.projected-density-of-states",
                    "media_type": "text/plain", "required": True,
                },
            ],
            "resources": _resources(intent.resources), "settings": {},
        }

    def build_fragment(self, intent: ScientificIntent) -> WorkflowFragment:
        task = self.build_task(intent)
        return WorkflowFragment.single(
            "dos-pdos", task,
            input_contracts={
                "fdf": ArtifactPortContract("siestaflow.siesta-dos-pdos-fdf", "application/x-siesta-fdf"),
                **{
                    f"pseudo_{index:03d}": ArtifactPortContract("siestaflow.pseudopotential", "application/x-psml")
                    for index, _ in enumerate(intent.parameters["pseudopotentials"], 1)
                },
            },
        )

    @staticmethod
    def _analysis_spec(path: Path) -> tuple[str, tuple[str, ...]]:
        document = FDFParser().parse_path(path)
        labels = document.scalars("SystemLabel")
        run_type = document.scalars("MD.TypeOfRun")
        blocks = document.blocks("ProjectedDensityOfStates")
        if len(labels) != 1:
            raise ValueError("dos_pdos requires exactly one SystemLabel")
        steps = document.scalars("MD.NumCGSteps")
        if len(run_type) != 1 or run_type[0].value.casefold() != "cg":
            raise ValueError("dos_pdos requires explicit MD.TypeOfRun CG")
        if len(steps) != 1 or steps[0].value != "0":
            raise ValueError("dos_pdos requires explicit MD.NumCGSteps 0")
        if len(blocks) != 1 or not blocks[0].closed:
            raise ValueError("dos_pdos requires exactly one closed ProjectedDensityOfStates block")
        rows = [line.split("#", 1)[0].strip().split() for line in blocks[0].body_lines]
        rows = [row for row in rows if row and not row[0].startswith(("!", ";"))]
        if len(rows) != 1:
            raise ValueError("ProjectedDensityOfStates must contain exactly one data row")
        row = rows[0]
        offset = 1 if row and row[0].casefold() == "ef" else 0
        if len(row) != 5 + offset or row[-1].casefold() != "ev":
            raise ValueError("ProjectedDensityOfStates requires energies, broadening, points, and eV")
        try:
            lower = Decimal(row[offset])
            upper = Decimal(row[offset + 1])
            broadening = Decimal(row[offset + 2])
            points = int(row[offset + 3])
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("ProjectedDensityOfStates has invalid numeric values") from exc
        if lower >= upper or broadening <= 0 or points <= 1:
            raise ValueError("ProjectedDensityOfStates requires ordered energies, positive broadening, and points > 1")
        species_blocks = document.blocks("ChemicalSpeciesLabel")
        if len(species_blocks) != 1:
            raise ValueError("dos_pdos requires exactly one ChemicalSpeciesLabel block")
        species: set[str] = set()
        for raw in species_blocks[0].body_lines:
            fields = raw.split("#", 1)[0].strip().split()
            if not fields or fields[0].startswith(("!", ";")):
                continue
            if len(fields) < 3:
                raise ValueError("dos_pdos has an invalid ChemicalSpeciesLabel row")
            species.add(require_local_id(fields[2], field_name="SIESTA species label"))
        if not species:
            raise ValueError("dos_pdos requires ChemicalSpeciesLabel rows")
        return (
            require_local_id(labels[0].value, field_name="SIESTA SystemLabel"),
            tuple(f"{item}.psml" for item in sorted(species)),
        )


class DOSPDOSRecipe:
    def build_workflow(self, intent: ScientificIntent, registry: CapabilityRegistry) -> dict[str, Any]:
        return _compose_single(
            intent, registry, capability_id=DOS_PDOS_CAPABILITY,
            policy=RecipePolicy(
                DOS_PDOS_RECIPE, "1.0.0",
                "Run a user-declared SIESTA total and projected DOS analysis",
                "DENSITY_OF_STATES_ANALYSIS",
            ),
        )


def _restart_identity(path: Path) -> str:
    """Hash scientific input common to an SCF parent and a DOS/PDOS child.

    Restart control, file labels, ionic-motion controls and the PDOS request do
    not change the electronic state represented by the transferred DM.  Every
    other normalized FDF line remains bound, so a geometry, pseudo label, XC,
    basis, mesh or SCF change is rejected before a package is written.
    """
    excluded_scalars = {"systemname", "systemlabel", "dm.usesavedm"}
    excluded_prefixes = ("md.",)
    excluded_blocks = {
        "projecteddensityofstates", "pdos.kgrid.monkhorstpack",
        "dos.kgrid.monkhorstpack",
    }
    output: list[str] = []
    skipping_block: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("!", ";")):
            continue
        lowered = line.casefold()
        if skipping_block is not None:
            if lowered.startswith("%endblock") and skipping_block in lowered:
                skipping_block = None
            continue
        if lowered.startswith("%block"):
            parts = lowered.split()
            if len(parts) >= 2 and parts[1] in excluded_blocks:
                skipping_block = parts[1]
                continue
        label = lowered.split(None, 1)[0]
        if label in excluded_scalars or label.startswith(excluded_prefixes):
            continue
        output.append(" ".join(line.split()))
    if skipping_block is not None:
        raise ValueError("restart identity FDF has an unclosed excluded block")
    return hashlib.sha256(("\n".join(output) + "\n").encode("utf-8")).hexdigest()


class GroundStateToDOSPDOSTaskBuilder:
    """Build a parent SCF task and a dependent DOS/PDOS restart task."""

    _PARAMETERS = {"ground_state_fdf", "dos_pdos_fdf", "pseudopotentials"}

    def build_task(self, intent: ScientificIntent) -> dict[str, Any]:
        raise NotImplementedError("ground-state-to-dos-pdos is a two-task recipe")

    def build_fragment(self, intent: ScientificIntent) -> WorkflowFragment:
        workflow = self.build_workflow(intent, CapabilityRegistry())
        tasks = tuple(workflow["tasks"])
        contracts: dict[str, ArtifactPortContract] = {}
        for task in tasks:
            for item in task["inputs"]:
                key = f"{task['task_id']}.{item['name']}"
                if item["name"] == "ground_state_dm":
                    contracts[key] = ArtifactPortContract(
                        "siestaflow.siesta-density-matrix", "application/octet-stream"
                    )
                elif item["name"] == "fdf":
                    contracts[key] = ArtifactPortContract(
                        "siestaflow.siesta-ground-state-fdf"
                        if task["task_id"] == "ground_state"
                        else "siestaflow.siesta-dos-pdos-fdf",
                        "application/x-siesta-fdf",
                    )
                else:
                    contracts[key] = ArtifactPortContract(
                        "siestaflow.pseudopotential", "application/x-psml"
                    )
        return WorkflowFragment("ground-state-to-dos-pdos", tasks, contracts)

    def build_workflow(self, intent: ScientificIntent, registry: CapabilityRegistry) -> dict[str, Any]:
        if set(intent.parameters) != self._PARAMETERS:
            raise ValueError("ground_state_to_dos_pdos requires ground_state_fdf, dos_pdos_fdf, and pseudopotentials")
        root = intent.source.parent
        parent_relative = _relative(intent.parameters["ground_state_fdf"], field="parameters.ground_state_fdf")
        child_relative = _relative(intent.parameters["dos_pdos_fdf"], field="parameters.dos_pdos_fdf")
        parent_path = root / Path(*PurePosixPath(parent_relative).parts)
        child_path = root / Path(*PurePosixPath(child_relative).parts)
        if not parent_path.is_file() or not child_path.is_file():
            raise ValueError("ground_state_to_dos_pdos FDF input is missing")
        parent_label, expected_pseudos = self._ground_state_spec(parent_path)
        child_label, child_pseudos = DOSPDOSTaskBuilder._analysis_spec(child_path)
        restart = FDFParser().parse_path(child_path).scalars("DM.UseSaveDM")
        if len(restart) != 1 or restart[0].value.casefold() not in {"t", "true"}:
            raise ValueError("DOS/PDOS restart FDF requires explicit DM.UseSaveDM T")
        if expected_pseudos != child_pseudos or _restart_identity(parent_path) != _restart_identity(child_path):
            raise ValueError("ground-state and DOS/PDOS FDFs are not restart-compatible")
        pseudos = self._pseudopotentials(intent, expected_pseudos)
        parent_inputs, _ = self._inputs(
            root, parent_relative, "ground-state.fdf", pseudos,
        )
        child_inputs, _ = self._inputs(root, child_relative, "dos-pdos.fdf", pseudos)
        child_inputs.append({
            "name": "ground_state_dm", "from": {"task": "ground_state", "output": "density_matrix"},
            "destination": f"{child_label}.DM",
            "media_type": "application/octet-stream",
        })
        resources = _resources(intent.resources)
        parent = {
            "task_id": "ground_state", "kind": "calculation",
            "capability": "siestaflow.engine.siesta", "inputs": parent_inputs,
            "outputs": [{
                "name": "density_matrix", "path": f"{parent_label}.DM",
                "artifact_type": "siestaflow.siesta-density-matrix",
                "media_type": "application/octet-stream", "required": True,
            }],
            "resources": resources, "settings": {},
        }
        child = {
            "task_id": "dos_pdos", "kind": "calculation",
            "capability": "siestaflow.engine.siesta", "depends_on": ["ground_state"],
            "inputs": child_inputs,
            "outputs": [
                {
                    "name": "total_dos", "path": f"{child_label}.DOS",
                    "artifact_type": "siestaflow.total-density-of-states",
                    "media_type": "text/plain", "required": True,
                },
                {
                    "name": "projected_dos", "path": f"{child_label}.PDOS",
                    "artifact_type": "siestaflow.projected-density-of-states",
                    "media_type": "text/plain", "required": True,
                },
            ],
            "resources": resources, "settings": {},
        }
        return {
            "schema_version": "1.0", "workflow_id": intent.intent_id,
            "project_id": intent.project_id,
            "description": "Hash-bound SIESTA ground-state to DOS/PDOS continuation",
            "metadata": {
                **dict(intent.metadata), "recipe_id": GROUND_STATE_TO_DOS_PDOS_RECIPE,
                "execution_authorized": False,
                "restart_identity_sha256": _restart_identity(parent_path),
            },
            "tasks": [parent, child],
        }

    @staticmethod
    def _ground_state_spec(path: Path) -> tuple[str, tuple[str, ...]]:
        document = FDFParser().parse_path(path)
        labels = document.scalars("SystemLabel")
        run_type = document.scalars("MD.TypeOfRun")
        steps = document.scalars("MD.NumCGSteps")
        if len(labels) != 1:
            raise ValueError("ground state requires exactly one SystemLabel")
        if len(run_type) != 1 or run_type[0].value.casefold() != "cg":
            raise ValueError("ground state requires explicit MD.TypeOfRun CG")
        if len(steps) != 1 or steps[0].value != "0":
            raise ValueError("ground state requires explicit MD.NumCGSteps 0")
        if document.blocks("ProjectedDensityOfStates"):
            raise ValueError("ground state FDF must not request ProjectedDensityOfStates")
        species_blocks = document.blocks("ChemicalSpeciesLabel")
        if len(species_blocks) != 1:
            raise ValueError("ground state requires exactly one ChemicalSpeciesLabel block")
        species: set[str] = set()
        for raw in species_blocks[0].body_lines:
            fields = raw.split("#", 1)[0].strip().split()
            if not fields or fields[0].startswith(("!", ";")):
                continue
            if len(fields) < 3:
                raise ValueError("ground state has an invalid ChemicalSpeciesLabel row")
            species.add(require_local_id(fields[2], field_name="SIESTA species label"))
        if not species:
            raise ValueError("ground state requires ChemicalSpeciesLabel rows")
        return require_local_id(labels[0].value, field_name="SIESTA SystemLabel"), tuple(
            f"{item}.psml" for item in sorted(species)
        )

    @staticmethod
    def _pseudopotentials(intent: ScientificIntent, expected: tuple[str, ...]) -> list[dict[str, str]]:
        raw = intent.parameters["pseudopotentials"]
        if not isinstance(raw, list) or not raw:
            raise ValueError("ground_state_to_dos_pdos pseudopotentials must be a non-empty list")
        result: list[dict[str, str]] = []
        destinations: set[str] = set()
        root = intent.source.parent
        for item in raw:
            if not isinstance(item, Mapping) or set(item) != {"source", "destination"}:
                raise ValueError("each ground_state_to_dos_pdos pseudopotential requires source and destination")
            source = _relative(item["source"], field="parameters.pseudopotentials.source")
            destination = _relative(item["destination"], field="parameters.pseudopotentials.destination")
            if not source.casefold().endswith(".psml") or not (root / Path(*PurePosixPath(source).parts)).is_file():
                raise ValueError("ground_state_to_dos_pdos pseudopotential must be an existing PSML file")
            if destination in destinations:
                raise ValueError("ground_state_to_dos_pdos pseudopotential destination is duplicated")
            destinations.add(destination)
            result.append({"source": source, "destination": destination})
        if destinations != set(expected):
            raise ValueError("ground_state_to_dos_pdos pseudopotential destinations must match ChemicalSpeciesLabel")
        return result

    @staticmethod
    def _inputs(root: Path, fdf: str, destination: str, pseudos: list[dict[str, str]]) -> tuple[list[dict[str, str]], set[str]]:
        inputs: list[dict[str, str]] = [{
            "name": "fdf", "source": fdf, "destination": destination,
            "media_type": "application/x-siesta-fdf",
        }]
        destinations = {destination}
        for index, item in enumerate(pseudos, 1):
            inputs.append({
                "name": f"pseudo_{index:03d}", "source": item["source"],
                "destination": item["destination"], "media_type": "application/x-psml",
            })
            destinations.add(item["destination"])
        return inputs, destinations


class GroundStateToDOSPDOSRecipe:
    def build_workflow(self, intent: ScientificIntent, registry: CapabilityRegistry) -> dict[str, Any]:
        return _compose_single(
            intent, registry, capability_id=GROUND_STATE_TO_DOS_PDOS_CAPABILITY,
            policy=RecipePolicy(
                GROUND_STATE_TO_DOS_PDOS_RECIPE, "1.0.0",
                "Run a hash-bound SIESTA ground-state to DOS/PDOS continuation",
                "ELECTRONIC_STATE_CONTINUATION_DENSITY_OF_STATES",
            ),
        )


class ConvergeThenRelaxationTaskBuilder:
    """Build the post-approval relaxation stage without changing its FDF.

    The convergence stage has already completed in a prior immutable lock.  A
    profile, its decision, and the evaluated report are therefore staged as
    ordinary hash-bound inputs to this new lock.  This is deliberately not an
    implicit expansion of the previous workflow.
    """

    _PARAMETERS = {"fdf", "pseudopotentials", "numerical_profiles"}

    def build_task(self, intent: ScientificIntent) -> dict[str, Any]:
        if set(intent.parameters) != self._PARAMETERS:
            raise ValueError(
                "converge_then_relax intent requires fdf, pseudopotentials, and numerical_profiles"
            )
        profiles = self._profiles(intent)
        base_intent = ScientificIntent(
            source=intent.source, intent_id=intent.intent_id, project_id=intent.project_id,
            recipe_id=STRUCTURAL_RELAXATION_RECIPE,
            parameters={"fdf": intent.parameters["fdf"], "pseudopotentials": intent.parameters["pseudopotentials"]},
            resources=intent.resources, metadata=intent.metadata, sha256=intent.sha256,
        )
        task = StructuralRelaxationTaskBuilder().build_task(base_intent)
        self._fdf_matches_profiles(
            intent.source.parent / Path(*PurePosixPath(_relative(intent.parameters["fdf"], field="parameters.fdf")).parts),
            tuple(item["profile"] for item in profiles),
        )
        extra_inputs: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        for index, item in enumerate(profiles, 1):
            for kind in ("profile", "approval", "evidence"):
                extra_inputs.append({
                    "name": f"numerical_{index:03d}_{kind}", "source": item[kind + "_path"],
                    "destination": f"numerics/{index:03d}-{kind}.json",
                    "media_type": "application/json",
                })
            profile = item["profile"]
            records.append({
                "profile_id": profile.reference.profile_id, "profile_sha256": profile.reference.sha256,
                "parameter": profile.parameter, "selection": dict(profile.selection),
                "candidate_sha256": profile.candidate_sha256,
                "evidence_sha256": profile.evidence_sha256,
                "approval_id": profile.reference.approval_id,
                "approval_sha256": profile.reference.approval_sha256,
            })
        task["inputs"].extend(extra_inputs)
        task["settings"] = {"numerical_profiles": records}
        return task

    def build_fragment(self, intent: ScientificIntent) -> WorkflowFragment:
        task = self.build_task(intent)
        contracts = {
            "fdf": ArtifactPortContract("siestaflow.siesta-relaxation-fdf", "application/x-siesta-fdf"),
            **{
                f"pseudo_{index:03d}": ArtifactPortContract("siestaflow.pseudopotential", "application/x-psml")
                for index, _ in enumerate(intent.parameters["pseudopotentials"], 1)
            },
        }
        for index, _ in enumerate(intent.parameters["numerical_profiles"], 1):
            for kind, artifact_type in (
                ("profile", "siestaflow.numerical-profile"),
                ("approval", "siestaflow.scientific-approval"),
                ("evidence", "siestaflow.convergence-report"),
            ):
                contracts[f"numerical_{index:03d}_{kind}"] = ArtifactPortContract(
                    artifact_type, "application/json"
                )
        return WorkflowFragment.single("converge-then-relax", task, input_contracts=contracts)

    @staticmethod
    def _profiles(intent: ScientificIntent) -> list[dict[str, Any]]:
        raw_profiles = intent.parameters["numerical_profiles"]
        if not isinstance(raw_profiles, list) or not raw_profiles:
            raise ValueError("converge_then_relax numerical_profiles must be a non-empty list")
        root = intent.source.parent
        records: list[dict[str, Any]] = []
        parameters: set[str] = set()
        for raw in raw_profiles:
            if not isinstance(raw, Mapping) or set(raw) != {"profile", "approval", "evidence"}:
                raise ValueError("each numerical profile requires profile, approval, and evidence")
            paths = {kind: _relative(raw[kind], field=f"parameters.numerical_profiles.{kind}") for kind in raw}
            if any(not (root / Path(*PurePosixPath(path).parts)).is_file() for path in paths.values()):
                raise ValueError("converge_then_relax numerical profile input is missing")
            profile = load_approved_profile(root / Path(*PurePosixPath(paths["profile"]).parts))
            candidate, approval, approval_sha256 = load_decision(
                root / Path(*PurePosixPath(paths["approval"]).parts)
            )
            evidence_sha256 = hashlib.sha256(
                (root / Path(*PurePosixPath(paths["evidence"]).parts)).read_bytes()
            ).hexdigest()
            if (
                approval.decision.value != "APPROVE"
                or approval_sha256 != profile.reference.approval_sha256
                or approval.approval_id != profile.reference.approval_id
                or approval.subject_sha256 != profile.candidate_sha256
                or approval.evidence_sha256 != profile.evidence_sha256
                or evidence_sha256 != profile.evidence_sha256
                or candidate["parameter"] != profile.parameter
                or canonical_primitive(candidate["selection"]) != canonical_primitive(profile.selection)
            ):
                raise ValueError("numerical profile, approval, and evidence are not hash-bound together")
            if profile.parameter in parameters:
                raise ValueError("converge_then_relax accepts at most one approved profile per parameter")
            parameters.add(profile.parameter)
            records.append({
                "profile": profile, "profile_path": paths["profile"], "approval_path": paths["approval"],
                "evidence_path": paths["evidence"],
            })
        return records

    @staticmethod
    def _fdf_matches_profiles(fdf_path: Path, profiles: tuple[ApprovedNumericalProfile, ...]) -> None:
        document = FDFParser().parse_path(fdf_path)
        for profile in profiles:
            if profile.parameter == "Mesh.Cutoff":
                scalars = document.scalars("Mesh.Cutoff")
                if len(scalars) != 1 or scalars[0].unit != "Ry":
                    raise ValueError("converge_then_relax FDF must declare exactly one Mesh.Cutoff in Ry")
                try:
                    actual = Decimal(scalars[0].value.replace("D", "E").replace("d", "e"))
                    expected = Decimal(str(profile.selection["value"]).replace("D", "E").replace("d", "e"))
                except (InvalidOperation, KeyError) as exc:
                    raise ValueError("approved Mesh.Cutoff selection is invalid") from exc
                if actual != expected:
                    raise ValueError("FDF Mesh.Cutoff does not match the approved numerical profile")
            elif profile.parameter == "kgrid.MonkhorstPack":
                blocks = document.blocks("kgrid.MonkhorstPack")
                if len(blocks) != 1 or not blocks[0].closed:
                    raise ValueError("converge_then_relax FDF must declare exactly one kgrid.MonkhorstPack block")
                rows = [line.split("#", 1)[0].strip().split() for line in blocks[0].body_lines]
                rows = [row for row in rows if row]
                try:
                    dimensions = list(profile.selection["dimensions"])
                    shifts = [Decimal(str(item)) for item in profile.selection["shifts"]]
                    valid = len(rows) == 3 and all(len(row) == 4 for row in rows)
                    for row_index, row in enumerate(rows):
                        valid = valid and all(int(row[column]) == (dimensions[row_index] if column == row_index else 0) for column in range(3))
                        valid = valid and Decimal(row[3].replace("D", "E").replace("d", "e")) == shifts[row_index]
                except (InvalidOperation, ValueError, KeyError, TypeError) as exc:
                    raise ValueError("approved kgrid selection is invalid") from exc
                if not valid:
                    raise ValueError("FDF kgrid.MonkhorstPack does not match the approved numerical profile")
            else:  # Defensive: profile loader currently only admits these types.
                raise ValueError(f"unsupported approved numerical parameter: {profile.parameter}")


class ConvergeThenRelaxationRecipe:
    def build_workflow(self, intent: ScientificIntent, registry: CapabilityRegistry) -> dict[str, Any]:
        return _compose_single(
            intent, registry, capability_id=CONVERGE_THEN_RELAX_CAPABILITY,
            policy=RecipePolicy(
                CONVERGE_THEN_RELAX_RECIPE, "1.0.0",
                "Relax a structure using explicitly approved convergence evidence",
                "CONVERGENCE_APPROVED_STRUCTURAL_RELAXATION",
            ),
        )


def builtin_authoring_registry() -> CapabilityRegistry:
    evaluator = CapabilityDescriptor(
        capability_id=MESH_EVALUATOR_CAPABILITY,
        kind=CapabilityKind.WORKFLOW_BUILDER,
        implementation_version="1.0.0",
        input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,),
        engine="siesta",
        metadata={"scope": "mesh convergence evidence", "runs_engine": False},
    )
    recipe = CapabilityDescriptor(
        capability_id=MESH_EVALUATION_RECIPE,
        kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0",
        input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,),
        engine="siesta",
        metadata={"requires": [MESH_EVALUATOR_CAPABILITY], "runs_engine": False},
    )
    kgrid_evaluator = CapabilityDescriptor(
        capability_id=KGRID_EVALUATOR_CAPABILITY,
        kind=CapabilityKind.WORKFLOW_BUILDER,
        implementation_version="1.0.0",
        input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,),
        engine="siesta",
        metadata={"scope": "k-grid convergence evidence", "runs_engine": False},
    )
    kgrid_recipe = CapabilityDescriptor(
        capability_id=KGRID_EVALUATION_RECIPE,
        kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0",
        input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,),
        engine="siesta",
        metadata={"requires": [KGRID_EVALUATOR_CAPABILITY], "runs_engine": False},
    )
    producer = CapabilityDescriptor(
        capability_id=OBSERVATION_PRODUCER_CAPABILITY, kind=CapabilityKind.WORKFLOW_BUILDER,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"scope": "real SIESTA artifact observation production", "runs_engine": False},
    )
    producer_recipe = CapabilityDescriptor(
        capability_id=OBSERVATION_PRODUCTION_RECIPE, kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"requires": [OBSERVATION_PRODUCER_CAPABILITY], "runs_engine": False},
    )
    composition_recipe = CapabilityDescriptor(
        capability_id=SCIENTIFIC_COMPOSITION_RECIPE, kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine=None,
        metadata={"requires": "user-selected registered WORKFLOW_BUILDER capabilities", "runs_engine": False,
                  "execution_authorized": False},
    )
    relaxation = CapabilityDescriptor(
        capability_id=STRUCTURAL_RELAXATION_CAPABILITY, kind=CapabilityKind.WORKFLOW_BUILDER,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"scope": "structural relaxation from explicit FDF", "runs_engine": True},
    )
    relaxation_recipe = CapabilityDescriptor(
        capability_id=STRUCTURAL_RELAXATION_RECIPE, kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"requires": [STRUCTURAL_RELAXATION_CAPABILITY], "runs_engine": True,
                  "execution_authorized": False},
    )
    converge_then_relax = CapabilityDescriptor(
        capability_id=CONVERGE_THEN_RELAX_CAPABILITY, kind=CapabilityKind.WORKFLOW_BUILDER,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"scope": "hash-bound approved numerical profile propagation", "runs_engine": True,
                  "requires_human_approval": True},
    )
    converge_then_relax_recipe = CapabilityDescriptor(
        capability_id=CONVERGE_THEN_RELAX_RECIPE, kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"requires": [CONVERGE_THEN_RELAX_CAPABILITY], "runs_engine": True,
                  "execution_authorized": False, "requires_human_approval": True},
    )
    dos_pdos = CapabilityDescriptor(
        capability_id=DOS_PDOS_CAPABILITY, kind=CapabilityKind.WORKFLOW_BUILDER,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"scope": "explicit total and projected density of states", "runs_engine": True},
    )
    dos_pdos_recipe = CapabilityDescriptor(
        capability_id=DOS_PDOS_RECIPE, kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"requires": [DOS_PDOS_CAPABILITY], "runs_engine": True,
                  "execution_authorized": False},
    )
    ground_state_to_dos_pdos = CapabilityDescriptor(
        capability_id=GROUND_STATE_TO_DOS_PDOS_CAPABILITY, kind=CapabilityKind.WORKFLOW_BUILDER,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"scope": "hash-bound electronic restart into DOS/PDOS", "runs_engine": True},
    )
    ground_state_to_dos_pdos_recipe = CapabilityDescriptor(
        capability_id=GROUND_STATE_TO_DOS_PDOS_RECIPE, kind=CapabilityKind.RECIPE,
        implementation_version="1.0.0", input_contracts=(SCIENTIFIC_INTENT,),
        output_contracts=(WORKFLOW_DEFINITION,), engine="siesta",
        metadata={"requires": [GROUND_STATE_TO_DOS_PDOS_CAPABILITY], "runs_engine": True,
                  "execution_authorized": False},
    )
    plugin = PluginDescriptor(
        plugin_id="siestaflow.builtin.scientific-authoring",
        plugin_version="1.0.0",
        core_contract_version=CORE_CONTRACT_VERSION,
        capabilities=(evaluator, recipe, kgrid_evaluator, kgrid_recipe, producer, producer_recipe,
                      composition_recipe, relaxation, relaxation_recipe, converge_then_relax,
                      converge_then_relax_recipe, dos_pdos, dos_pdos_recipe,
                      ground_state_to_dos_pdos, ground_state_to_dos_pdos_recipe),
        provider="SIESTAFLOW",
        metadata={"registration": "explicit", "global_import_side_effects": False},
    )
    registry = CapabilityRegistry()
    registry.register(plugin, {
        MESH_EVALUATOR_CAPABILITY: MeshEvidenceTaskBuilder(),
        MESH_EVALUATION_RECIPE: MeshEvidenceRecipe(),
        KGRID_EVALUATOR_CAPABILITY: KGridEvidenceTaskBuilder(),
        KGRID_EVALUATION_RECIPE: KGridEvidenceRecipe(),
        OBSERVATION_PRODUCER_CAPABILITY: ObservationProducerTaskBuilder(),
        OBSERVATION_PRODUCTION_RECIPE: ObservationProductionRecipe(),
        SCIENTIFIC_COMPOSITION_RECIPE: ManualCompositionRecipe(),
        STRUCTURAL_RELAXATION_CAPABILITY: StructuralRelaxationTaskBuilder(),
        STRUCTURAL_RELAXATION_RECIPE: StructuralRelaxationRecipe(),
        CONVERGE_THEN_RELAX_CAPABILITY: ConvergeThenRelaxationTaskBuilder(),
        CONVERGE_THEN_RELAX_RECIPE: ConvergeThenRelaxationRecipe(),
        DOS_PDOS_CAPABILITY: DOSPDOSTaskBuilder(),
        DOS_PDOS_RECIPE: DOSPDOSRecipe(),
        GROUND_STATE_TO_DOS_PDOS_CAPABILITY: GroundStateToDOSPDOSTaskBuilder(),
        GROUND_STATE_TO_DOS_PDOS_RECIPE: GroundStateToDOSPDOSRecipe(),
    })
    registry.freeze()
    return registry


class WorkflowAuthoringService:
    """Canonical application API shared by CLI and future user interfaces."""

    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        self.registry = registry or builtin_authoring_registry()

    def recipes(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "recipe_id": item.capability_id,
                "version": item.implementation_version,
                "engine": item.engine,
                "metadata": dict(item.metadata),
            }
            for item in self.registry.descriptors(kind=CapabilityKind.RECIPE)
        )

    def recipe(self, recipe_id: str) -> dict[str, Any]:
        item = self.registry.resolve(recipe_id).descriptor
        if item.kind is not CapabilityKind.RECIPE:
            raise ValueError(f"capability is not a recipe: {recipe_id}")
        return {
            "recipe_id": item.capability_id,
            "version": item.implementation_version,
            "engine": item.engine,
            "input_contracts": [str(value) for value in item.input_contracts],
            "output_contracts": [str(value) for value in item.output_contracts],
            "metadata": dict(item.metadata),
        }

    def build(self, intent_path: Path) -> tuple[ScientificIntent, dict[str, Any]]:
        intent = ScientificIntent.load(intent_path)
        registered = self.registry.resolve(
            intent.recipe_id,
            required_inputs=(SCIENTIFIC_INTENT,),
            required_outputs=(WORKFLOW_DEFINITION,),
        )
        if registered.descriptor.kind is not CapabilityKind.RECIPE:
            raise ValueError(f"intent capability is not a recipe: {intent.recipe_id}")
        recipe = registered.implementation
        definition = recipe.build_workflow(intent, self.registry)
        canonical_primitive(definition)
        return intent, definition

    def create_definition(
        self, intent_path: Path, output: Path, *, dry_run: bool = False,
        expected_recipe_id: str | None = None,
    ) -> dict[str, Any]:
        intent, definition = self.build(intent_path)
        if expected_recipe_id is not None and intent.recipe_id != expected_recipe_id:
            raise ValueError(f"intent must use recipe: {expected_recipe_id}")
        destination = output.resolve()
        if destination.parent != intent.source.parent:
            raise ValueError("workflow definition must remain beside its scientific intent")
        encoded = json.dumps(definition, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        if dry_run:
            return {
                "status": "WORKFLOW_DEFINITION_PREVIEW",
                "intent_id": intent.intent_id,
                "recipe_id": intent.recipe_id,
                "output": str(destination),
                "definition": definition,
                "execution_authorized": False,
                "side_effects": 0,
            }
        if destination.exists():
            raise FileExistsError(f"workflow definition already exists: {destination}")
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            compilation = WorkflowCompiler().compile(temporary)
            if not compilation.valid:
                raise ValueError("recipe produced an invalid WorkflowDefinition")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        final = WorkflowCompiler().compile(destination)
        if not final.valid:
            raise RuntimeError("written WorkflowDefinition failed canonical compilation")
        return {
            "status": "WORKFLOW_DEFINITION_CREATED",
            "intent_id": intent.intent_id,
            "recipe_id": intent.recipe_id,
            "output": str(destination),
            "definition_sha256": final.compiled.definition_sha256 if final.compiled else None,
            "workflow_lock_sha256": final.lock_dict()["content_sha256"],
            "execution_authorized": False,
        }

    def compose_definition(
        self, intent_path: Path, output: Path, *, dry_run: bool = False
    ) -> dict[str, Any]:
        """Create or preview a manually selected composition through the normal gate."""
        if ScientificIntent.load(intent_path).recipe_id != SCIENTIFIC_COMPOSITION_RECIPE:
            raise ValueError(f"intent must use recipe: {SCIENTIFIC_COMPOSITION_RECIPE}")
        return self.create_definition(
            intent_path, output, dry_run=dry_run,
            expected_recipe_id=SCIENTIFIC_COMPOSITION_RECIPE,
        )
