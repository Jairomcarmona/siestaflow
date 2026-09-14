"""Explicit plugin descriptors and capability registry.

Plugins are registered by composition.  Importing a module never mutates the
global process and dynamic discovery remains an outer-layer responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from .serialization import canonical_primitive
from .versioning import (
    ContractCompatibilityError,
    ContractRef,
    ContractVersion,
    require_namespaced_identifier,
)


class CapabilityKind(str, Enum):
    ENGINE = "ENGINE"
    EXECUTABLE = "EXECUTABLE"
    VALIDATION_RULE = "VALIDATION_RULE"
    RULE_PROVIDER = "RULE_PROVIDER"
    LAUNCHER = "LAUNCHER"
    ARTIFACT_PROCESSOR = "ARTIFACT_PROCESSOR"
    POSTPROCESSOR = "POSTPROCESSOR"
    SCHEDULER = "SCHEDULER"
    WORKFLOW_BUILDER = "WORKFLOW_BUILDER"
    RECIPE = "RECIPE"


_REQUIRED_METHODS = {
    CapabilityKind.ENGINE: (
        "inspect_input",
        "validate_input",
        "prepare_task",
        "build_command",
        "parse_output",
        "discover_artifacts",
        "classify_result",
    ),
    CapabilityKind.EXECUTABLE: (
        "inspect_input",
        "validate_input",
        "prepare_task",
        "build_command",
        "parse_output",
        "discover_artifacts",
        "classify_result",
    ),
    CapabilityKind.VALIDATION_RULE: ("evaluate",),
    CapabilityKind.RULE_PROVIDER: ("rules",),
    CapabilityKind.LAUNCHER: ("launch", "terminate_all"),
    CapabilityKind.ARTIFACT_PROCESSOR: ("process",),
    CapabilityKind.POSTPROCESSOR: ("process",),
    CapabilityKind.SCHEDULER: ("submit", "status"),
    CapabilityKind.WORKFLOW_BUILDER: ("build_task",),
    CapabilityKind.RECIPE: ("build_workflow",),
}


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    kind: CapabilityKind
    implementation_version: str
    input_contracts: tuple[ContractRef, ...]
    output_contracts: tuple[ContractRef, ...]
    engine: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_namespaced_identifier(
            self.capability_id, field="capability_id"
        )
        if not self.implementation_version.strip():
            raise ValueError("implementation_version must be non-empty")
        if not self.input_contracts and not self.output_contracts:
            raise ValueError("capabilities must declare at least one contract")
        canonical_primitive(self.metadata)


@dataclass(frozen=True)
class PluginDescriptor:
    plugin_id: str
    plugin_version: str
    core_contract_version: ContractVersion
    capabilities: tuple[CapabilityDescriptor, ...]
    provider: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_namespaced_identifier(self.plugin_id, field="plugin_id")
        object.__setattr__(
            self,
            "core_contract_version",
            ContractVersion.parse(self.core_contract_version),
        )
        if not self.plugin_version.strip() or not self.provider.strip():
            raise ValueError("plugins require version and provider")
        identifiers = [item.capability_id for item in self.capabilities]
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("plugin capability identifiers must be non-empty and unique")
        canonical_primitive(self.metadata)


@runtime_checkable
class Plugin(Protocol):
    descriptor: PluginDescriptor

    def capabilities(self) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class RegisteredCapability:
    plugin: PluginDescriptor
    descriptor: CapabilityDescriptor
    implementation: object


class CapabilityRegistry:
    """Mutable during composition, immutable after application bootstrap."""

    def __init__(
        self, *, core_contract_version: ContractVersion = ContractVersion(1, 0)
    ) -> None:
        self.core_contract_version = ContractVersion.parse(core_contract_version)
        self._capabilities: dict[str, RegisteredCapability] = {}
        self._plugins: dict[str, PluginDescriptor] = {}
        self._frozen = False

    def register(
        self,
        plugin: PluginDescriptor,
        implementations: Mapping[str, object],
    ) -> None:
        if self._frozen:
            raise RuntimeError("capability registry is frozen")
        self.core_contract_version.require_supports(plugin.core_contract_version)
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"plugin already registered: {plugin.plugin_id}")
        expected = {item.capability_id for item in plugin.capabilities}
        if set(implementations) != expected:
            difference = sorted(set(implementations) ^ expected)
            raise ValueError(f"plugin implementation mismatch: {difference}")
        for descriptor in plugin.capabilities:
            if descriptor.capability_id in self._capabilities:
                raise ValueError(
                    f"capability already registered: {descriptor.capability_id}"
                )
            implementation = implementations[descriptor.capability_id]
            missing = [
                name
                for name in _REQUIRED_METHODS[descriptor.kind]
                if not callable(getattr(implementation, name, None))
            ]
            if missing:
                raise TypeError(
                    f"{descriptor.capability_id} lacks required methods: {missing}"
                )
        self._plugins[plugin.plugin_id] = plugin
        for descriptor in plugin.capabilities:
            self._capabilities[descriptor.capability_id] = RegisteredCapability(
                plugin, descriptor, implementations[descriptor.capability_id]
            )

    def resolve(
        self,
        capability_id: str,
        *,
        required_inputs: Iterable[ContractRef] = (),
        required_outputs: Iterable[ContractRef] = (),
    ) -> RegisteredCapability:
        try:
            registered = self._capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {capability_id}") from exc
        self._require_contracts(
            registered.descriptor.input_contracts,
            tuple(required_inputs),
            label="input",
        )
        self._require_contracts(
            registered.descriptor.output_contracts,
            tuple(required_outputs),
            label="output",
        )
        return registered

    @staticmethod
    def _require_contracts(
        provided: tuple[ContractRef, ...],
        required: tuple[ContractRef, ...],
        *,
        label: str,
    ) -> None:
        for requirement in required:
            if not any(item.satisfies(requirement) for item in provided):
                raise ContractCompatibilityError(
                    f"capability does not provide required {label} contract {requirement}"
                )

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def descriptors(
        self, *, kind: CapabilityKind | None = None
    ) -> tuple[CapabilityDescriptor, ...]:
        values = (
            item.descriptor
            for item in self._capabilities.values()
            if kind is None or item.descriptor.kind is kind
        )
        return tuple(sorted(values, key=lambda item: item.capability_id))
