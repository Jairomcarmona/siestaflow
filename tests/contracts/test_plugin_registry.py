from __future__ import annotations

import pytest

from qraft.contracts import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRegistry,
    ContractCompatibilityError,
    ContractRef,
    ContractVersion,
    PluginDescriptor,
)


INPUT = ContractRef.parse("siestaflow.execution-request@1.0")
OUTPUT = ContractRef.parse("siestaflow.execution-evidence@1.0")


class Launcher:
    def launch(self, spec):
        return spec

    def terminate_all(self, *, kill=False):
        return ()


def _plugin(
    *,
    plugin_id: str = "org.example.hydra",
    capability_id: str = "org.example.launcher.hydra",
    core: ContractVersion = ContractVersion(1, 0),
) -> tuple[PluginDescriptor, CapabilityDescriptor]:
    capability = CapabilityDescriptor(
        capability_id=capability_id,
        kind=CapabilityKind.LAUNCHER,
        implementation_version="0.1.0",
        input_contracts=(INPUT,),
        output_contracts=(OUTPUT,),
    )
    plugin = PluginDescriptor(
        plugin_id=plugin_id,
        plugin_version="0.1.0",
        core_contract_version=core,
        capabilities=(capability,),
        provider="Example",
    )
    return plugin, capability


def test_registry_is_explicit_resolvable_and_freezable() -> None:
    registry = CapabilityRegistry()
    plugin, capability = _plugin()
    launcher = Launcher()
    registry.register(plugin, {capability.capability_id: launcher})
    resolved = registry.resolve(
        capability.capability_id,
        required_inputs=(INPUT,),
        required_outputs=(OUTPUT,),
    )
    assert resolved.implementation is launcher
    registry.freeze()
    with pytest.raises(RuntimeError):
        other, other_capability = _plugin(
            plugin_id="org.example.other",
            capability_id="org.example.launcher.other",
        )
        registry.register(other, {other_capability.capability_id: Launcher()})


def test_registry_rejects_duplicate_missing_methods_and_newer_core() -> None:
    registry = CapabilityRegistry()
    plugin, capability = _plugin()
    with pytest.raises(TypeError):
        registry.register(plugin, {capability.capability_id: object()})

    newer, newer_capability = _plugin(core=ContractVersion(1, 1))
    with pytest.raises(ContractCompatibilityError):
        registry.register(newer, {newer_capability.capability_id: Launcher()})


def test_registry_fails_closed_on_contract_mismatch() -> None:
    registry = CapabilityRegistry()
    plugin, capability = _plugin()
    registry.register(plugin, {capability.capability_id: Launcher()})
    with pytest.raises(ContractCompatibilityError):
        registry.resolve(
            capability.capability_id,
            required_inputs=(
                ContractRef.parse("siestaflow.validation-report@1.0"),
            ),
        )

