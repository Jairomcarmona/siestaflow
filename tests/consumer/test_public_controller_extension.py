"""Verified frozen bindings select specialized capability, not generic command."""
import importlib.util
import sys
from pathlib import Path

import pytest

from qraft.api import CanonicalController
from qraft.contracts import (
    CapabilityDescriptor, CapabilityKind, PluginDescriptor, ContractVersion,
    EXECUTION_REQUEST, EXECUTION_EVIDENCE,
)


def load_fixture(relative):
    path = Path(__file__).parents[1] / relative
    name = 'consumer_' + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def setup(tmp_path, monkeypatch, **kwargs):
    fixture = load_fixture('runs/test_adaptive_prepared_run.py')
    _, _, root = fixture.prepared(tmp_path)
    controller = CanonicalController.from_file(
        root / 'campaign.yaml', environment=fixture.environment(root), **kwargs,
    )
    # Scheduler placement/runtime probes are external; never claim HPC acceptance.
    monkeypatch.setattr(controller, '_validate_runtime_compatibility', lambda: None)
    monkeypatch.setattr(controller, '_validate_runtime_placement',
                        lambda: setattr(controller, '_validated_hosts', ('fixture-host',)))
    return controller, root


@pytest.mark.parametrize('bindings,exception', [
    ({'sweep_alpha': 'consumer.reassigned'}, ValueError),
    ({'unknown': 'siestaflow.gate.deterministic-metric'}, ValueError),
    ({'sweep_alpha': 'siestaflow.gate.deterministic-metric'}, KeyError),
])
def test_unknown_mismatched_or_missing_plugin_never_launches(tmp_path, monkeypatch, bindings, exception):
    controller, root = setup(tmp_path, monkeypatch, capability_bindings=bindings)
    with pytest.raises(exception):
        controller.run(install_signal_handlers=False)
    assert controller.runtime is None
    assert not (root / 'state/workflow_runtime.json').exists()
    assert not list((root / 'work').glob('**/attempt-*')) if (root / 'work').exists() else True


def test_explicit_plugin_reaches_canonical_runtime_and_freezes(tmp_path, monkeypatch):
    fixture = load_fixture('execution/test_capability_runtime.py')
    capability = fixture.SyntheticCapability()
    monkeypatch.setattr('qraft.execution.canonical_controller.DirectLauncher', fixture.RecordingLauncher)
    capability_id = 'siestaflow.gate.deterministic-metric'
    seen = []
    def register(registry):
        seen.append(registry)
        descriptor = CapabilityDescriptor(capability_id, CapabilityKind.ENGINE, '1.0.0',
                                          (EXECUTION_REQUEST,), (EXECUTION_EVIDENCE,))
        registry.register(PluginDescriptor('consumer.plugin', '1.0.0', ContractVersion(1, 0),
                                           (descriptor,), 'consumer'), {capability_id: capability})
    controller, root = setup(tmp_path, monkeypatch, register_capabilities=register,
                             capability_bindings={'sweep_alpha': capability_id},
                             launcher=fixture.RecordingLauncher())
    controller.run(install_signal_handlers=False)
    assert seen[0].frozen
    assert controller.runtime.registry.resolve(capability_id).implementation is capability
    assert capability.classifications == 1
    alpha = next(task for task in controller.plan.workflow.tasks if task.task_id == 'sweep_alpha')
    assert alpha.capability_id == capability_id
    # Fixture intentionally lacks adaptive metric output: no scientific pass is asserted.
    assert controller.runtime.runtime_fingerprint
