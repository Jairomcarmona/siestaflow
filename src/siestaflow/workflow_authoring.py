"""Application-facing scientific intent, capability, and recipe authoring.

The CLI is an adapter over this module.  Recipes build ordinary
WorkflowDefinition documents and never bypass the compiler or ``run prepare``.
"""

from __future__ import annotations

import hashlib
import json
import os
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
    plugin = PluginDescriptor(
        plugin_id="siestaflow.builtin.scientific-authoring",
        plugin_version="1.0.0",
        core_contract_version=CORE_CONTRACT_VERSION,
        capabilities=(evaluator, recipe, kgrid_evaluator, kgrid_recipe, producer, producer_recipe,
                      composition_recipe, relaxation, relaxation_recipe),
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
