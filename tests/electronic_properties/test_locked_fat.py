"""Projection preserves source artifacts and detects wavefunction tampering."""
import hashlib
from types import SimpleNamespace
import pytest
from qraft.engines.siesta.electronic_analysis import parse_bands
from test_electronic_analysis_runtime import locked_protocol


def sample(root, protocol):
    attempt = root/'attempt'; attempt.mkdir()
    text = '0\n-1 2\n2 1 1\n0 0 0 0 0.003\n'
    (attempt/'carbon.bands').write_text(text)
    for name in ('carbon.bands.WFSX', 'carbon.HSX'):
        (attempt/name).write_bytes(b'fixture')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(attempt_root=attempt, bands=parse_bands(text), result=dict(
        parent_scf={'origin':'SCF directo provisional', 'authority':'NUMERICAL_CANDIDATE'},
        bands_sha256=sha(attempt/'carbon.bands'), worker_environment_sha256=protocol._worker_environment.sha256,
        fat_input_sha256={name:sha(attempt/name) for name in ('carbon.bands.WFSX','carbon.HSX')}))


def test_fat_uses_locked_binary_preserves_mpr_and_returns_only_group_weights(tmp_path, monkeypatch):
    protocol = locked_protocol(tmp_path,provisional=True); data = sample(tmp_path, protocol)
    mpr = tmp_path/'source.mpr'; mpr.write_text('carbon\nDOS\na\nC_2s\nb\nC_2p\n')
    def run(command, *, cwd, **kwargs):
        assert command == [protocol._worker_environment.fat.path, '-b','1','-B','2','projection']
        for name, weight in (('a',-.25),('b',1.25)):
            (cwd/f'projection.{name}.EIGFAT').write_text(f'# carbon min_band, max_band: 1 2\n2 1 1\n1 0 0 0 0 {weight} 0.003 {weight}\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('qraft.protocols.electronic_analysis.subprocess.run', run)
    result = protocol.run_fat(data, mpr=mpr, projections=('a','b'), min_band=1, max_band=2, runs_root=tmp_path/'fat')
    assert result['partition']['status'] == 'PASS'
    assert result['authority'] == 'NUMERICAL_CANDIDATE'
    assert result['parent_scf'] == data['result']['parent_scf']
    assert result['policy_id'] == 'qraft.electronic.policy@1'
    assert result['groups'][0]['weights'] == {'a':-.5,'b':2.5}
    assert (tmp_path/'fat/projection.mpr').read_bytes()==mpr.read_bytes()
    assert not list(data['attempt_root'].glob('*.EIGFAT'))


def test_tampered_wavefunctions_prevent_fat_launch(tmp_path, monkeypatch):
    protocol = locked_protocol(tmp_path,provisional=True); data = sample(tmp_path, protocol)
    (data['attempt_root']/'carbon.bands.WFSX').write_bytes(b'changed')
    mpr = tmp_path/'source.mpr'; mpr.write_text('carbon\nDOS\na\nC\n')
    monkeypatch.setattr('qraft.protocols.electronic_analysis.subprocess.run', lambda *a, **k: pytest.fail('must not launch'))
    with pytest.raises(ValueError, match='input changed'):
        protocol.run_fat(data, mpr=mpr, projections=('a',), min_band=1, max_band=2, runs_root=tmp_path/'fat')


def test_integration_fat_rejects_provisional_sample_before_launch(tmp_path,monkeypatch):
    protocol=locked_protocol(tmp_path);data=sample(tmp_path,protocol)
    monkeypatch.setattr('qraft.protocols.electronic_analysis.subprocess.run',lambda *a,**k:pytest.fail('must not launch'))
    with pytest.raises(TypeError,match='M6'):
        protocol.run_fat(data,mpr=tmp_path/'missing',projections=('a',),min_band=1,max_band=2,runs_root=tmp_path/'fat')
    assert not (tmp_path/'fat').exists()
