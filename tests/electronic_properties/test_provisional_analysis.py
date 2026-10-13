"""A direct SCF remains a candidate and cannot impersonate M6."""
import json
from pathlib import Path
from dataclasses import FrozenInstanceError
import pytest
from qraft.api import scientific_policy_document
from qraft.protocols.provisional_scf import ProvisionalScfSource
from qraft.engines.siesta.electronic_analysis import POLICY
from test_electronic_property_fanout import BASE
from test_electronic_analysis_runtime import locked_protocol, fake_engine


def provisional(root):
    fdf = root / 'final.fdf'; fdf.write_text(BASE)
    dm = root / 'carbon.DM'; dm.write_bytes(b'verified-dm')
    (root / 'C.psf').write_bytes(b'pseudo')
    out = root / 'scf.out'; out.write_text('SCF cycle converged\nsiesta: FreeEng = -1.000000\nJob completed\n')
    return ProvisionalScfSource.load(final_fdf=fdf, density_matrix=dm, stdout=out)


def test_direct_scf_sample_preserves_candidate_without_m6(tmp_path):
    source = provisional(tmp_path)
    result = locked_protocol(tmp_path,provisional=True).run_sample(source, block_name='BandPoints',
        rows=[[0,0,0],[.01,0,0],[.02,0,0]], n_occupied=1,
        runs_root=tmp_path/'sample', profile=fake_engine(tmp_path))
    assert result['result']['authority'] == 'NUMERICAL_CANDIDATE'
    assert result['result']['parent_scf']['origin'] == 'SCF directo provisional'
    assert 'parent_electronic_state' not in result['result']
    assert not list(tmp_path.rglob('electronic-state.json'))
    assert result['result']['origin']=='PROVISIONAL_DIRECT_SCF'
    with pytest.raises(TypeError,match='M6'):
        locked_protocol(tmp_path).run_sample(source,block_name='BandPoints',rows=[],n_occupied=1,runs_root=tmp_path/'rejected')
    import qraft.api as api
    assert not hasattr(api,'ProvisionalScfSource')
    assert source.density_matrix.read_bytes() == b'verified-dm'
    with pytest.raises(TypeError):
        source.pseudopotentials['C'] = Path('other')
    with pytest.raises(FrozenInstanceError):
        source.stdout_sha256 = 'a'*64


@pytest.mark.parametrize('filename', ['final.fdf', 'carbon.DM', 'C.psf', 'scf.out'])
def test_each_source_tampering_stops_before_launch(tmp_path, filename):
    source = provisional(tmp_path)
    (tmp_path/filename).write_bytes((tmp_path/filename).read_bytes()+b'\n#changed\n')
    with pytest.raises(ValueError):
        source.verify()


@pytest.mark.parametrize('text', ['Job completed', 'SCF cycle converged'])
def test_missing_scf_proof_cannot_be_a_candidate(tmp_path, text):
    source = provisional(tmp_path)
    source.stdout.write_text(text+'\nsiesta: FreeEng = -1.000000\n')
    with pytest.raises(ValueError, match='SCF_NOT_PROVEN'):
        ProvisionalScfSource.load(final_fdf=source.final_fdf, density_matrix=source.density_matrix, stdout=source.stdout)


def test_policy_documents_are_approved_detached_and_unknown_rejected():
    assert scientific_policy_document('qraft.electronic.policy@1') == POLICY
    assert scientific_policy_document('qraft.presets.policy@1')['symprec_A'] == .01
    document = scientific_policy_document('qraft.eos.policy@1')
    document['volume_factors'][0] = -1
    assert scientific_policy_document('qraft.eos.policy@1')['volume_factors'][0] == .94
    with pytest.raises(ValueError, match='Unknown approved'):
        scientific_policy_document('qraft.unknown.policy@1')
