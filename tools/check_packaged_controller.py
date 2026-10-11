"""Prepare from a distribution, then consume only its isolated vendored runtime."""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from zipfile import ZipFile


ISOLATED_CONTROLLER = r'''
import json, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'runtime'))
from qraft.execution.canonical_controller import CanonicalController
from qraft.execution.command_capability import GenericCommandCapability
from qraft.execution.authority import AuthorityLost
from qraft.contracts import (CapabilityDescriptor, CapabilityKind, PluginDescriptor,
                            ContractVersion, EXECUTION_REQUEST, EXECUTION_EVIDENCE)
from qraft.run_inspection import RunInspector
from qraft.workflows import load_workflow_lock, load_run_lock
import qraft.execution.canonical_controller as module
assert Path(module.__file__).is_relative_to(root / 'runtime')
assert not any('site-packages' in path for path in sys.path)
assert RunInspector().inspect(root).status == 'PREPARED_RUN_VERIFIED'
capability_id = 'siestaflow.gate.deterministic-metric'
def register(registry):
    descriptor = CapabilityDescriptor(capability_id, CapabilityKind.EXECUTABLE,
                                     '1.0.0', (EXECUTION_REQUEST,), (EXECUTION_EVIDENCE,))
    registry.register(PluginDescriptor('consumer.packaged', '1.0.0', ContractVersion(1, 0),
                                       (descriptor,), 'fixture'),
                      {capability_id: GenericCommandCapability()})
class ForbiddenLauncher:
    def launch(self, *args, **kwargs):
        raise AssertionError('denied authority must never launch')
    def terminate_all(self, **kwargs):
        pass
environment = {'SLURM_JOB_ID': 'fixture-only', 'SLURM_SUBMIT_DIR': str(root),
               'SLURM_JOB_END_TIME': str(time.time() + 300), 'SLURM_NNODES': '1',
               'SLURM_NTASKS': '1', 'SLURM_CPUS_PER_TASK': '1'}
boundaries = []
def deny(boundary):
    boundaries.append(boundary)
    return False
controller = CanonicalController.from_file(
    root / 'campaign.yaml', environment=environment, launcher=ForbiddenLauncher(),
    register_capabilities=register, capability_bindings={'sweep_alpha': capability_id},
    authority_check=deny, authority_generation='1')
# External placement/probes are fixture seams, never synthetic HPC acceptance.
controller._validate_runtime_compatibility = lambda: None
controller._validate_runtime_placement = lambda: setattr(controller, '_validated_hosts', ('fixture-host',))
try:
    controller.run(install_signal_handlers=False)
except AuthorityLost:
    pass
else:
    raise AssertionError('authority denial was ignored')
assert boundaries and boundaries[0].action == 'initialize'
assert controller.runtime.runtime_fingerprint == boundaries[0].runtime_fingerprint
assert controller.runtime.registry.frozen
assert controller.plan.workflow.tasks[0].capability_id == capability_id
assert controller.plan.workflow.metadata['qraft.native_contract_bindings'] == {
    'workflow_lock_sha256': load_workflow_lock(root / 'workflow.lock.json')[0].content_sha256,
    'run_lock_sha256': load_run_lock(root / 'run.lock.json')[0].content_sha256,
}
assert not list(root.glob('work/**/attempt-*'))
assert not (root / 'state/workflow_runtime.json').exists()
print('Vendored controller binding verified; authority denied before execution')
'''


def check_packaged_controller(*, require_installed=True):
    import qraft.api
    from qraft.api import WorkflowCompiler, write_workflow_lock, RunPreparer, RunPreparationRequest, RunInspector
    if require_installed:
        assert Path(qraft.api.__file__).is_relative_to(Path(sys.prefix))
    with tempfile.TemporaryDirectory(prefix='qraft-installed-controller-') as temporary:
        root = Path(temporary)
        source = root / 'source'
        source.mkdir()
        definition = {
            'schema_version': '1.0', 'workflow_id': 'installed-sweep', 'project_id': 'fixture',
            'tasks': [{'task_id': 'sweep_alpha', 'kind': 'sweep',
                       'capability': 'siestaflow.gate.deterministic-metric', 'inputs': [],
                       'outputs': [{'name': 'metric', 'path': 'metric.json',
                                    'artifact_type': 'siestaflow.adaptive-metric', 'media_type': 'application/json'}],
                       'resources': {'nodes': 1, 'mpi_processes': 1, 'processes_per_node': 1,
                                     'cpus_per_process': 1, 'walltime_seconds': 30},
                       'settings': {'variant_id': 'alpha', 'metric_name': 'score', 'metric_value': 2.0}}],
        }
        compiled = WorkflowCompiler().compile_mapping(definition, source_root=source)
        assert compiled.valid
        lock = root / 'workflow.lock.json'
        write_workflow_lock(compiled, lock)
        profile = root / 'profile.json'
        profile.write_text(json.dumps({
            'schema_version': '1.0', 'profile_id': 'installed-fixture', 'target': 'slurm',
            'slurm': {'partition': 'local', 'account': 'test', 'qos': 'normal'},
            'allocation': {'nodes': 1, 'total_cpus': 1, 'memory': '1G', 'walltime': '00:05:00',
                           'max_parallel_steps': 1, 'shutdown_margin_seconds': 30, 'termination_grace_seconds': 10},
            'runtime': {'module_commands': [], 'siesta_executable': 'siesta', 'executable_arguments': [],
                        'launcher': {'kind': 'srun', 'command': ['srun'], 'arguments': [],
                                     'bootstrap': 'ssh', 'processes_per_node': 1},
                        'exclusive': True, 'environment': {}},
            'task_policy': {'max_attempts': 1, 'require_scf_converged': True},
        }), encoding='utf-8')
        result = RunPreparer().prepare(RunPreparationRequest(lock, source, profile, root / 'packages', 'installed-fixture'))
        package = Path(result.package_path)
        assert not result.execution_authorized and not result.submission_performed
        assert RunInspector().inspect(package).status == 'PREPARED_RUN_VERIFIED'
        with ZipFile(result.zip_path) as archive:
            for name in archive.namelist():
                assert archive.read(name) == (package.parent / name).read_bytes()
        subprocess.run([sys.executable, '-I', '-S', '-c', ISOLATED_CONTROLLER, str(package)],
                       cwd=temporary, check=True)
        # Integrity recheck after isolated imports and rejected initialization.
        assert RunInspector().inspect(package).status == 'PREPARED_RUN_VERIFIED'
    print('Installed preparation and isolated generated controller fixtures passed')


if __name__ == '__main__':
    check_packaged_controller()
