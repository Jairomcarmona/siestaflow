"""A new valid native policy must not reuse the old translated runtime identity."""
import hashlib
import json
from dataclasses import replace

from qraft.api import CanonicalController, RunInspector, load_run_lock, load_workflow_lock
from qraft.contracts import (
    CapabilityDescriptor, CapabilityKind, PluginDescriptor, ContractVersion,
    EXECUTION_REQUEST, EXECUTION_EVIDENCE,
)
from tests.runs.test_adaptive_prepared_run import prepared, environment
from tests.execution.test_capability_runtime import SyntheticCapability, RecordingLauncher


def controller(root, monkeypatch, *, bound):
    capability_id = 'siestaflow.gate.deterministic-metric'
    def register(registry):
        descriptor = CapabilityDescriptor(capability_id, CapabilityKind.ENGINE, '1.0.0',
                                          (EXECUTION_REQUEST,), (EXECUTION_EVIDENCE,))
        registry.register(PluginDescriptor('consumer.policy-fixture', '1.0.0', ContractVersion(1, 0),
                                           (descriptor,), 'fixture'), {capability_id: SyntheticCapability()})
    current = CanonicalController.from_file(root / 'campaign.yaml', environment=environment(root),
        launcher=RecordingLauncher(), register_capabilities=register,
        capability_bindings={'sweep_alpha': capability_id} if bound else None)
    monkeypatch.setattr(current, '_validate_runtime_compatibility', lambda: None)
    monkeypatch.setattr(current, '_validate_runtime_placement',
                        lambda: setattr(current, '_validated_hosts', ('fixture',)))
    def capture():
        raise RuntimeError('fixture stops after runtime identity construction')
    # No process or attempt needed: inspect the runtime constructed before run.
    monkeypatch.setattr('qraft.execution.canonical_controller.CompiledWorkflowRuntime.run', lambda self: capture())
    try:
        current.run(install_signal_handlers=False)
    except RuntimeError as exc:
        assert str(exc) == 'fixture stops after runtime identity construction'
    return current


def change_native_policy_as_new_package(root):
    _, workflow = load_workflow_lock(root / 'workflow.lock.json')
    _, run = load_run_lock(root / 'run.lock.json')
    new_tasks = tuple(replace(task, settings={**task.settings, 'consumer_policy_revision': '2'})
                      if task.task_id == 'sweep_alpha' else task for task in workflow.tasks)
    envelope = replace(workflow, tasks=new_tasks).envelope()
    (root / 'workflow.lock.json').write_text(json.dumps(envelope.to_dict()), encoding='utf-8')
    updated = replace(run, workflow_lock_sha256=envelope.content_sha256).envelope()
    (root / 'run.lock.json').write_text(json.dumps(updated.to_dict()), encoding='utf-8')
    # This fixture authors a new consistent package; it is not a migration tool.
    manifest_file = root / 'manifest.json'
    manifest = json.loads(manifest_file.read_bytes())
    for name in ('workflow.lock.json', 'run.lock.json'):
        manifest['immutable_files'][name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    checksums = {**manifest['immutable_files'], 'manifest.json': hashlib.sha256(manifest_file.read_bytes()).hexdigest()}
    (root / 'checksums.sha256').write_text(''.join(f'{digest}  {name}\n' for name, digest in sorted(checksums.items())), encoding='utf-8')


def test_changed_native_settings_same_capability_changes_bound_fingerprint_only(tmp_path, monkeypatch):
    _, _, root = prepared(tmp_path)
    original = controller(root, monkeypatch, bound=True)
    legacy_original = controller(root, monkeypatch, bound=False)
    original_source = (root / 'campaign.yaml').read_bytes()
    change_native_policy_as_new_package(root)
    assert RunInspector().inspect(root).status == 'PREPARED_RUN_VERIFIED'
    assert (root / 'campaign.yaml').read_bytes() == original_source
    changed = controller(root, monkeypatch, bound=True)
    legacy_changed = controller(root, monkeypatch, bound=False)
    assert original.runtime.runtime_fingerprint != changed.runtime.runtime_fingerprint
    assert legacy_original.runtime.runtime_fingerprint == legacy_changed.runtime.runtime_fingerprint
    refs = changed.plan.workflow.metadata['qraft.native_contract_bindings']
    assert refs['workflow_lock_sha256'] == load_workflow_lock(root / 'workflow.lock.json')[0].content_sha256
    assert refs['run_lock_sha256'] == load_run_lock(root / 'run.lock.json')[0].content_sha256
