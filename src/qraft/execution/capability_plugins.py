"""Explicit capability composition helpers for executable workflow runtimes."""

from __future__ import annotations

from ..contracts import (
    EXECUTION_EVIDENCE,
    EXECUTION_REQUEST,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRegistry,
    ContractVersion,
    PluginDescriptor,
)
from ..engines.siesta.adapter import SiestaEngineAdapter
from ..engines.siesta.relaxation import SiestaRelaxationCapability
from .command_capability import GenericCommandCapability


SIESTA_ENGINE_CAPABILITY = "siestaflow.engine.siesta"
SIESTA_RELAX_CAPABILITY = "qraft.siesta.relax"
GENERIC_COMMAND_CAPABILITY = "qraft.runtime.command"


def register_siesta_engine(
    registry: CapabilityRegistry,
    *,
    adapter: SiestaEngineAdapter | None = None,
) -> SiestaEngineAdapter:
    """Register SIESTA explicitly; importing this module changes no registry."""

    implementation = adapter or SiestaEngineAdapter()
    descriptor = CapabilityDescriptor(
        capability_id=SIESTA_ENGINE_CAPABILITY,
        kind=CapabilityKind.ENGINE,
        implementation_version="1.0.0",
        input_contracts=(EXECUTION_REQUEST,),
        output_contracts=(EXECUTION_EVIDENCE,),
        engine="siesta",
    )
    plugin = PluginDescriptor(
        plugin_id="siestaflow.plugin.siesta-engine",
        plugin_version="1.0.0",
        core_contract_version=ContractVersion(1, 0),
        capabilities=(descriptor,),
        provider="QRAFT",
    )
    registry.register(plugin, {descriptor.capability_id: implementation})
    return implementation


def register_siesta_relax(
    registry: CapabilityRegistry,
    *,
    capability: SiestaRelaxationCapability | None = None,
) -> SiestaRelaxationCapability:
    implementation = capability or SiestaRelaxationCapability()
    descriptor = CapabilityDescriptor(
        capability_id=SIESTA_RELAX_CAPABILITY,
        kind=CapabilityKind.ENGINE,
        implementation_version="1.0.0",
        input_contracts=(EXECUTION_REQUEST,), output_contracts=(EXECUTION_EVIDENCE,),
        engine="siesta", metadata={"scientific_operation": "relaxation", "geometry_artifact_type": "qraft.geometry", "fixed_cell": True},
    )
    plugin = PluginDescriptor(
        plugin_id="qraft.plugin.siesta-relax", plugin_version="1.0.0",
        core_contract_version=ContractVersion(1, 0), capabilities=(descriptor,), provider="QRAFT",
    )
    registry.register(plugin, {descriptor.capability_id: implementation})
    return implementation


def register_generic_command(
    registry: CapabilityRegistry,
    *,
    capability: GenericCommandCapability | None = None,
) -> GenericCommandCapability:
    """Register the contract-driven command adapter used by legacy translation."""

    implementation = capability or GenericCommandCapability()
    descriptor = CapabilityDescriptor(
        capability_id=GENERIC_COMMAND_CAPABILITY,
        kind=CapabilityKind.EXECUTABLE,
        implementation_version="1.0.0",
        input_contracts=(EXECUTION_REQUEST,),
        output_contracts=(EXECUTION_EVIDENCE,),
        metadata={"scientific_semantics": False},
    )
    plugin = PluginDescriptor(
        plugin_id="qraft.plugin.generic-command",
        plugin_version="1.0.0",
        core_contract_version=ContractVersion(1, 0),
        capabilities=(descriptor,),
        provider="QRAFT",
    )
    registry.register(plugin, {descriptor.capability_id: implementation})
    return implementation
