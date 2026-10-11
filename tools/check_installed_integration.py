"""Black-box fixture against a wheel, isolated Python, outside the checkout."""
import json
import sys
import tempfile
from pathlib import Path

from qraft.api import API_VERSION, WorkflowCompiler, RunInspector, write_workflow_lock, load_workflow_lock
from qraft.api import ControllerReservation, RuntimeAllocation


assert API_VERSION == '1.0'
import qraft.api
assert Path(qraft.api.__file__).is_relative_to(Path(sys.prefix))

# Value transport only: this does not enable a controller or qualify HF-1.
reservation = ControllerReservation(1, 8, 'openmpi', 4, 1, 1)
assert ControllerReservation.from_mapping(reservation.to_mapping()) == reservation
request = reservation.resource_request('fixture-hf1', RuntimeAllocation(8, 1, hosts=('fixture-host',)))
assert request.cpus == 8 and request.nodes == 1 and request.exclusive_hosts
try:
    ControllerReservation(1, 4, 'openmpi', 4, 1, 1).resource_request(
        'fixture-hf1', RuntimeAllocation(8, 1, hosts=('fixture-host',)))
except ValueError:
    pass
else:
    raise AssertionError('partial allocation node accepted')
definition = {
    'schema_version': '1.0', 'workflow_id': 'installed-consumer', 'project_id': 'fixture',
    'tasks': [{'task_id': 'read', 'kind': 'postprocess', 'capability': 'consumer.reader',
               'inputs': [], 'outputs': [], 'resources': {}}],
}
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    raw = json.dumps(definition, indent=2).encode()
    file = root / 'workflow.json'
    file.write_bytes(raw)
    compiler = WorkflowCompiler()
    compiled = compiler.compile_mapping(definition, source_root=root, source_bytes=raw)
    assert compiled.valid and compiler.compile(file).lock_dict() == compiled.lock_dict()
    lock = root / 'workflow.lock.json'
    write_workflow_lock(compiled, lock)
    assert load_workflow_lock(lock)[0].content_sha256 == compiled.lock_dict()['content_sha256']
    try:
        compiler.compile_mapping(definition, source_root=root, source_bytes=b'{}')
    except ValueError:
        pass
    else:
        raise AssertionError('forged source bytes accepted')
    try:
        RunInspector().inspect(root)
    except ValueError:
        pass
    else:
        raise AssertionError('incomplete package accepted')
print('Installed public integration fixtures passed without a checkout or PYTHONPATH')
