import json
from pathlib import Path

import pytest

from qraft.api import AuthorityLost, NativeEventStream, NativeCursorError, CompiledWorkflowRuntime
from tests.execution.test_capability_runtime import (
    SyntheticCapability, RecordingLauncher, workflow, node, registry_for, identity, execution,
)


def make_runtime(tmp_path, check, launcher=None):
    compiled = workflow(tmp_path, (node('A'),))
    selected = launcher or RecordingLauncher()
    runtime = CompiledWorkflowRuntime(
        workflow=compiled, registry=registry_for(SyntheticCapability()),
        root=tmp_path / 'run', source_root=tmp_path,
        scientific_identities={'A': identity()}, execution_specs=execution(),
        launcher=selected, authority_check=check, authority_generation='9007199254740993',
    )
    return runtime, selected


@pytest.mark.parametrize('action', ['initialize', 'reserve_attempt', 'launch_attempt', 'finalize_attempt', 'publish_attempt'])
def test_stale_generation_never_launches_or_publishes_attempt(tmp_path, action):
    boundaries = []
    def check(boundary):
        boundaries.append(boundary)
        assert boundary.generation == '9007199254740993'
        assert len(boundary.runtime_fingerprint) == 64
        return boundary.action != action
    current, launcher = make_runtime(tmp_path, check)
    with pytest.raises(AuthorityLost):
        current.run()
    assert not list(current.root.glob('work/**/attempt.json'))
    if action in {'initialize', 'reserve_attempt', 'launch_attempt'}:
        assert launcher.launches == []
    if action == 'initialize':
        assert not current.root.exists()
    # Denial remains latched even if a subsequent verifier response would allow.
    with pytest.raises(AuthorityLost):
        current.check_authority('recovered_generation')


@pytest.mark.parametrize('action', ['publish_state', 'publish_journal', 'publish_event'])
def test_denied_publication_preserves_exact_existing_bytes(tmp_path, action):
    current, _ = make_runtime(tmp_path, lambda boundary: True)
    assert current.run().status == 'COMPLETED'
    before = {path.relative_to(current.root): path.read_bytes() for path in current.root.rglob('*') if path.is_file()}
    current.authority_check = lambda boundary: boundary.action != action
    operation = {'publish_state': current._save_state,
                 'publish_journal': lambda: current._append_state_mutation({'kind': 'state', 'changes': {'status': 'FAILED'}}),
                 'publish_event': lambda: current._event('STALE_PUBLICATION')}[action]
    with pytest.raises(AuthorityLost):
        operation()
    after = {path.relative_to(current.root): path.read_bytes() for path in current.root.rglob('*') if path.is_file()}
    assert before == after


def test_callback_failure_is_fail_closed_without_effects(tmp_path):
    def fail(boundary):
        raise OSError('authority service unavailable')
    current, launcher = make_runtime(tmp_path, fail)
    with pytest.raises(AuthorityLost):
        current.run()
    assert not current.root.exists() and not launcher.launches


def test_event_replay_restart_legacy_and_rotation_policy(tmp_path):
    path = tmp_path / 'events.jsonl'
    legacy = b'{"event":"LEGACY","at":"fixture"}\n'
    path.write_bytes(legacy)
    first = NativeEventStream(path, 'a' * 64)
    second_event = first.append({'event': 'CURRENT', 'at': 'fixture'})
    page1 = first.read(limit=1)
    assert page1.events[0]['sequence'] == 1
    resumed = NativeEventStream(path, 'a' * 64)
    page2 = resumed.read(after=page1.cursor)
    assert page2.events == (second_event,)
    assert resumed.read(after=page2.cursor).events == ()
    third = resumed.append({'event': 'AFTER_RESTART', 'at': 'fixture'})
    assert third['sequence'] == 3 and len({item['event_id'] for item in resumed.read().events}) == 3
    assert path.read_bytes().startswith(legacy)
    wrong = NativeEventStream(tmp_path / 'other.jsonl', 'b' * 64)
    wrong.append({'event': 'OTHER'})
    with pytest.raises(NativeCursorError):
        wrong.read(after=page1.cursor)
    path.write_bytes(legacy)
    with pytest.raises(NativeCursorError):
        NativeEventStream(path, 'a' * 64).read()


def test_partial_tail_and_identity_tamper_are_rejected(tmp_path):
    path = tmp_path / 'events.jsonl'
    stream = NativeEventStream(path, 'a' * 64)
    stream.append({'event': 'FIRST'})
    good = path.read_bytes()
    path.write_bytes(good + b'{')
    with pytest.raises(NativeCursorError):
        stream.read()
    corrupted = json.loads(good)
    corrupted['sequence'] = 2
    path.write_text(json.dumps(corrupted) + '\n', encoding='utf-8')
    with pytest.raises(NativeCursorError):
        stream.read()


@pytest.mark.parametrize('line', [b'{"payload":NaN}\n', b'{"payload":Infinity}\n', b'{bad}\n',
                                b'{"sequence":true,"event_id":"bad","stream_id":"bad"}\n'])
def test_nonfinite_malformed_or_boolean_identity_rejected(tmp_path, line):
    path = tmp_path / 'events.jsonl'
    stream = NativeEventStream(path, 'a' * 64)
    stream.append({'event': 'FIRST'})
    path.write_bytes(line)
    with pytest.raises(NativeCursorError):
        NativeEventStream(path, 'a' * 64).read()


def test_initialized_run_losing_both_stream_files_never_rewinds(tmp_path):
    current, _ = make_runtime(tmp_path, lambda boundary: True)
    assert current.run().status == 'COMPLETED'
    old_stream = current._event_stream.read().stream_id
    current.events_path.unlink()
    current._event_stream.metadata_path.unlink()
    # Preserve immutable workflow/inputs and native state, simulate a process restart.
    restored, launcher = make_runtime(tmp_path, lambda boundary: True)
    with pytest.raises(NativeCursorError):
        restored.run()
    assert not restored._event_stream.metadata_path.exists()
    assert not launcher.launches
    assert restored._state['native_event_stream_id'] == old_stream


def test_adopted_legacy_high_water_prevents_preappend_rewind(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_bytes(b'{"event":"LEGACY_ONE"}\n{"event":"LEGACY_TWO"}\n')
    first = NativeEventStream(path, 'a' * 64)
    stream_id = first.ensure_identity()
    assert first.read().events[-1]['sequence'] == 2
    assert json.loads(first.metadata_path.read_bytes())['high_water'] == 2
    path.write_bytes(b'{"event":"LEGACY_ONE"}\n')
    restored = NativeEventStream(path, 'a' * 64, expected_stream_id=stream_id)
    with pytest.raises(NativeCursorError):
        restored.ensure_identity()
    with pytest.raises(NativeCursorError):
        restored.append({'event': 'REWIND_ATTEMPT'})
