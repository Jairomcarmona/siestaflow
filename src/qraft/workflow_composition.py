"""Deterministic composition of typed scientific workflow fragments.

The compiler remains the authority for the final DAG.  This layer only joins
registered authoring fragments, validates their scientific artifact ports, and
persists the composition facts in ordinary WorkflowDefinition metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .contracts import canonical_primitive, require_namespaced_identifier
from .contracts.workflow import require_local_id


class IntentIdentity(Protocol):
    intent_id: str
    project_id: str
    sha256: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ArtifactPortContract:
    artifact_type: str
    media_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_type", require_namespaced_identifier(self.artifact_type, field="artifact port type"))
        if not str(self.media_type).strip():
            raise ValueError("artifact port media_type is required")

    def as_dict(self) -> dict[str, str]:
        return {"artifact_type": self.artifact_type, "media_type": self.media_type}


@dataclass(frozen=True)
class WorkflowFragment:
    """One independently authored group of tasks with typed input ports."""

    fragment_id: str
    tasks: tuple[Mapping[str, Any], ...]
    input_contracts: Mapping[str, ArtifactPortContract]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fragment_id", require_local_id(self.fragment_id, field_name="workflow fragment id"))
        if not self.tasks:
            raise ValueError("workflow fragment requires at least one task")
        task_ids = [str(task.get("task_id", "")) for task in self.tasks]
        if any(not value for value in task_ids) or len(set(task_ids)) != len(task_ids):
            raise ValueError("workflow fragment task ids must be non-empty and unique")
        for task_id in task_ids:
            require_local_id(task_id, field_name="workflow fragment task id")
        expected_inputs = {
            f"{task['task_id']}.{item.get('name', '')}"
            for task in self.tasks
            for item in task.get("inputs", [])
        }
        if set(self.input_contracts) != expected_inputs:
            difference = sorted(set(self.input_contracts) ^ expected_inputs)
            raise ValueError(f"workflow fragment input contract mismatch: {difference}")
        if any(not isinstance(item, ArtifactPortContract) for item in self.input_contracts.values()):
            raise TypeError("workflow fragment input contracts must be ArtifactPortContract values")
        canonical_primitive([dict(task) for task in self.tasks])

    @classmethod
    def single(
        cls,
        fragment_id: str,
        task: Mapping[str, Any],
        *,
        input_contracts: Mapping[str, ArtifactPortContract],
    ) -> "WorkflowFragment":
        task_id = str(task.get("task_id", ""))
        return cls(
            fragment_id,
            (dict(task),),
            {f"{task_id}.{name}": contract for name, contract in input_contracts.items()},
        )


@dataclass(frozen=True)
class RecipePolicy:
    recipe_id: str
    recipe_version: str
    description: str
    scientific_scope: str
    final_authority: str = "HUMAN_REVIEW"
    execution_authorized: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe_id", require_namespaced_identifier(self.recipe_id, field="recipe id"))
        if not self.recipe_version or not self.description or not self.scientific_scope:
            raise ValueError("recipe policy fields must be non-empty")
        if type(self.execution_authorized) is not bool:
            raise TypeError("execution_authorized must be boolean")


class WorkflowComposer:
    """Compose any selected subset of compatible scientific modules."""

    def compose(
        self,
        intent: IntentIdentity,
        policy: RecipePolicy,
        fragments: Sequence[WorkflowFragment],
    ) -> dict[str, Any]:
        if not fragments:
            raise ValueError("workflow composition requires at least one fragment")
        fragment_ids = [item.fragment_id for item in fragments]
        if len(set(fragment_ids)) != len(fragment_ids):
            raise ValueError("workflow fragment ids must be unique")
        tasks = [dict(task) for fragment in fragments for task in fragment.tasks]
        task_ids = [str(task["task_id"]) for task in tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("composed workflow task ids must be unique")

        outputs: dict[tuple[str, str], ArtifactPortContract] = {}
        port_records: list[dict[str, str]] = []
        for task in tasks:
            task_id = str(task["task_id"])
            for output in task.get("outputs", []):
                key = (task_id, str(output["name"]))
                if key in outputs:
                    raise ValueError(f"duplicate composed output port: {task_id}.{key[1]}")
                contract = ArtifactPortContract(str(output["artifact_type"]), str(output["media_type"]))
                outputs[key] = contract
                port_records.append({"task": task_id, "port": key[1], "direction": "output", **contract.as_dict()})

        declared_inputs = {
            key: contract
            for fragment in fragments
            for key, contract in fragment.input_contracts.items()
        }
        connections: list[dict[str, str]] = []
        external_sources: dict[str, ArtifactPortContract] = {}
        for task in tasks:
            task_id = str(task["task_id"])
            for item in task.get("inputs", []):
                name = str(item["name"])
                contract = declared_inputs[f"{task_id}.{name}"]
                if str(item["media_type"]) != contract.media_type:
                    raise ValueError(f"input media type disagrees with its contract: {task_id}.{name}")
                port_records.append({"task": task_id, "port": name, "direction": "input", **contract.as_dict()})
                produced = item.get("from")
                if produced is None:
                    source = str(item.get("source", ""))
                    existing = external_sources.get(source)
                    if existing is not None and existing != contract:
                        raise ValueError(
                            f"external source has conflicting scientific contracts: {source}"
                        )
                    external_sources[source] = contract
                    continue
                source = (str(produced.get("task", "")), str(produced.get("output", "")))
                source_contract = outputs.get(source)
                if source_contract is None:
                    raise ValueError(f"composed input references unknown output: {task_id}.{name}")
                if source_contract != contract:
                    raise ValueError(
                        "scientific artifact contract mismatch: "
                        f"{source[0]}.{source[1]} -> {task_id}.{name}"
                    )
                connections.append({
                    "source_task": source[0], "source_port": source[1],
                    "target_task": task_id, "target_port": name,
                    "artifact_type": contract.artifact_type,
                })

        definition = {
            "schema_version": "1.0",
            "workflow_id": intent.intent_id,
            "project_id": intent.project_id,
            "description": policy.description,
            "metadata": {
                **dict(intent.metadata),
                "intent_sha256": intent.sha256,
                "recipe_id": policy.recipe_id,
                "recipe_version": policy.recipe_version,
                "scientific_scope": policy.scientific_scope,
                "execution_authorized": policy.execution_authorized,
                "final_authority": policy.final_authority,
                "composition": {
                    "schema_version": "1.0",
                    "fragments": fragment_ids,
                    "ports": sorted(port_records, key=lambda item: (item["task"], item["direction"], item["port"])),
                    "connections": sorted(connections, key=lambda item: (item["target_task"], item["target_port"])),
                },
            },
            "tasks": tasks,
        }
        canonical_primitive(definition)
        return definition
