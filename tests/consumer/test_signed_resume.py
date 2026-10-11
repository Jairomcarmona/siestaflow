"""Consumer verifies a real HMAC in a synthetic fixture, not HPC evidence."""
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from qraft.api import (
    RunInspector, SchedulerJobIdentity, TerminalSchedulerEvidence,
    load_run_lock, load_workflow_lock,
)
from tests.runs.test_prepared_run import _prepared


NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
KEY = b'synthetic consumer test key; never used for deployment'


def verify(receipt):
    return receipt.signer_id == 'consumer.test-key' and hmac.compare_digest(
        receipt.signature, hmac.new(KEY, receipt.signed_bytes(), hashlib.sha256).hexdigest(),
    )


def fixture(tmp_path):
    _, root = _prepared(tmp_path)
    config = json.loads((root / 'campaign.yaml').read_text(encoding='utf-8'))
    payload = {
        'schema_version': '1.0', 'campaign_id': config['campaign_id'], 'status': 'INTERRUPTED',
        'current_job_id': 'old-job', 'revision': 1,
        'tasks': {task['task_id']: {'status': 'INTERRUPTED', 'attempts': 1,
                                  'reason': 'synthetic interrupted', 'depends_on': task.get('depends_on', [])}
                  for task in config['tasks']},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    (root / 'state').mkdir(exist_ok=True)
    (root / 'state/campaign_state.json').write_text(json.dumps({
        'schema_version': '1.0', 'payload': payload, 'sha256': hashlib.sha256(encoded).hexdigest(),
    }), encoding='utf-8')
    inspector = RunInspector()
    receipt = TerminalSchedulerEvidence(
        inspector.inspect(root).run_id,
        load_workflow_lock(root / 'workflow.lock.json')[0].content_sha256,
        load_run_lock(root / 'run.lock.json')[0].content_sha256,
        SchedulerJobIdentity('old-job', 'synthetic-cluster', 'synthetic-user'),
        'CANCELLED', '2026-10-11T11:59:00Z', '2026-10-11T12:05:00Z',
        'consumer.test-key', 'unsigned', True,
    )
    receipt = replace(receipt, signature=hmac.new(KEY, receipt.signed_bytes(), hashlib.sha256).hexdigest())
    return root, receipt


def resume(root, receipt, **kwargs):
    return RunInspector().resume(root, terminal_evidence=receipt,
                                 verify_terminal_evidence=verify,
                                 expected_job=SchedulerJobIdentity('old-job', 'synthetic-cluster', 'synthetic-user'),
                                 now=NOW, **kwargs)


def test_signed_terminal_receipt_allows_read_only_resume(tmp_path):
    root, receipt = fixture(tmp_path)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert RunInspector().resume(root).command is None
    planned = resume(root, receipt)
    assert planned.terminal_confirmation_received and not planned.submission_performed
    assert planned.resubmission_required
    assert before == {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize('changes', [
    {'signature': '0' * 64}, {'run_id': 'wrong-run'}, {'workflow_lock_sha256': '0' * 64},
    {'run_lock_sha256': '0' * 64}, {'job': SchedulerJobIdentity('different', 'synthetic-cluster', 'synthetic-user')},
    {'job': SchedulerJobIdentity('old-job', 'different-cluster', 'synthetic-user')},
    {'observed_at': '2026-10-11T12:01:00Z'}, {'expires_at': '2026-10-11T11:59:30Z'},
])
def test_wrong_signed_scope_future_expiry_or_forgery_blocks(tmp_path, changes):
    root, receipt = fixture(tmp_path)
    with pytest.raises(ValueError):
        resume(root, replace(receipt, **changes))


def test_running_requeued_or_unsigned_evidence_cannot_confirm(tmp_path):
    root, receipt = fixture(tmp_path)
    with pytest.raises(ValueError, match='terminal'):
        replace(receipt, state='RUNNING')
    with pytest.raises(ValueError, match='requeued'):
        replace(receipt, active_allocation_absent=False)
    with pytest.raises(ValueError, match='trusted verifier'):
        RunInspector().resume(root, terminal_evidence=receipt)
    with pytest.raises(ValueError, match='do not mix'):
        resume(root, receipt, previous_job_terminal=True)


def test_latest_native_allocation_outranks_stale_summary(tmp_path):
    root, receipt = fixture(tmp_path)
    payload = json.loads((root / 'state/campaign_state.json').read_text(encoding='utf-8'))['payload']
    payload['allocation_history'] = [{'allocation_id': 'old-job'}, {'allocation_id': 'new-live-job'}]
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    (root / 'state/workflow_runtime.json').write_text(json.dumps({
        'schema_version': '1.0', 'payload': payload, 'sha256': hashlib.sha256(encoded).hexdigest(),
    }), encoding='utf-8')
    (root / 'results').mkdir(exist_ok=True)
    (root / 'results/campaign_summary.json').write_text('{"job_id":"old-job"}', encoding='utf-8')
    with pytest.raises(ValueError, match='observed allocation'):
        resume(root, receipt)
