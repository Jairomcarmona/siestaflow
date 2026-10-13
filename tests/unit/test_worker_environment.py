"""Private lock prevents replacement or a different executable at launch."""
import hashlib
import json
from types import SimpleNamespace
import pytest
from qraft.protocols._worker_environment import _WorkerEnvironment


def lock(root):
    binary = root/'binary'; binary.write_bytes(b'fixture')
    entry = dict(path=str(binary.resolve()), version='fixture', sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                 version_evidence='synthetic build')
    path = root/'lock.json'; path.write_text(json.dumps(dict(siesta=entry, fat=entry)))
    return _WorkerEnvironment.load(path), binary


def test_replacement_and_lock_rewrite_stop_before_delegate(tmp_path):
    environment, binary = lock(tmp_path)
    calls = []
    delegate = SimpleNamespace(launch=lambda spec: calls.append(spec), terminate_all=lambda **kw: ())
    wrapped = environment.launcher(delegate)
    with pytest.raises(ValueError, match='differs'):
        wrapped.launch(SimpleNamespace(executable='other'))
    binary.write_bytes(b'changed')
    with pytest.raises(ValueError, match='SHA-256'):
        wrapped.launch(SimpleNamespace(executable=str(binary)))
    binary.write_bytes(b'fixture')
    environment.lock_path.write_bytes(environment.lock_path.read_bytes()+b' ')
    with pytest.raises(ValueError, match='lock changed'):
        wrapped.launch(SimpleNamespace(executable=str(binary)))
    assert not calls


def test_verification_repeats_for_every_launch(tmp_path):
    environment, binary = lock(tmp_path)
    calls = []
    wrapped = environment.launcher(SimpleNamespace(launch=lambda spec: calls.append(spec), terminate_all=lambda **kw: ()))
    wrapped.launch(SimpleNamespace(executable=str(binary)))
    binary.write_bytes(b'changed')
    with pytest.raises(ValueError):
        wrapped.launch(SimpleNamespace(executable=str(binary)))
    assert len(calls) == 1
