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
from .workflows import WorkflowCompiler


MESH_EVALUATOR_CAPABILITY = "siestaflow.siesta.mesh-evidence-evaluator"
MESH_EVALUATION_RECIPE = "siestaflow.recipe.siesta.mesh-evidence-evaluation"


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


class MeshEvidenceRecipe:
    def build_workflow(
        self, intent: ScientificIntent, registry: CapabilityRegistry
    ) -> dict[str, Any]:
        registered = registry.resolve(
            MESH_EVALUATOR_CAPABILITY,
            required_inputs=(SCIENTIFIC_INTENT,),
            required_outputs=(WORKFLOW_DEFINITION,),
        )
        builder = registered.implementation
        if not callable(getattr(builder, "build_task", None)):
            raise TypeError("mesh evaluator capability cannot build tasks")
        task = builder.build_task(intent)
        return {
            "schema_version": "1.0",
            "workflow_id": intent.intent_id,
            "project_id": intent.project_id,
            "description": "Evaluate hash-bound Mesh.Cutoff convergence evidence",
            "metadata": {
                **dict(intent.metadata),
                "intent_sha256": intent.sha256,
                "recipe_id": MESH_EVALUATION_RECIPE,
                "recipe_version": "1.0.0",
                "scientific_scope": "EVIDENCE_EVALUATION_ONLY",
                "execution_authorized": False,
                "final_authority": "HUMAN_REVIEW",
            },
            "tasks": [task],
        }


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
    plugin = PluginDescriptor(
        plugin_id="siestaflow.builtin.scientific-authoring",
        plugin_version="1.0.0",
        core_contract_version=CORE_CONTRACT_VERSION,
        capabilities=(evaluator, recipe),
        provider="SIESTAFLOW",
        metadata={"registration": "explicit", "global_import_side_effects": False},
    )
    registry = CapabilityRegistry()
    registry.register(plugin, {
        MESH_EVALUATOR_CAPABILITY: MeshEvidenceTaskBuilder(),
        MESH_EVALUATION_RECIPE: MeshEvidenceRecipe(),
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
        self, intent_path: Path, output: Path, *, dry_run: bool = False
    ) -> dict[str, Any]:
        intent, definition = self.build(intent_path)
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
