"""Native runtime delegation, restart ownership and longitudinal handoff."""
import hashlib
import json
from pathlib import Path
import sys
import pytest

from qraft.engines.siesta.electronic_properties import parse_bands, validate_property_branch
from qraft.engines.siesta.electronic_analysis import parse_bands as read_sample
from qraft.protocols.electronic_analysis import ElectronicAnalysisProtocol, _reciprocal_rows
from qraft.workflow_authoring import BandStructureTaskBuilder
from test_electronic_property_fanout import _source


def locked_protocol(root):
    binary = Path(sys.executable).resolve()
    entry = dict(path=str(binary), version=sys.version, sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                 version_evidence='synthetic fixture interpreter, not SIESTA/fat qualification')
    lock = root / 'worker-environment.json'
    lock.write_text(json.dumps(dict(siesta=entry, fat=entry)))
    return ElectronicAnalysisProtocol(worker_lock_path=lock)


def fake_engine(root, *, fail=False, missing=False, restart=True):
    script = root / 'siesta_fake.py'
    script.write_text(
        "from pathlib import Path\n"
        "text=Path('input.fdf').read_text()\n"
        "print('Siesta started')\nprint('SCF cycle 1')\n"
        + ("print('SCF converged')\n" if not fail else "print('SCF did not converge')\n")
        + ("print('attempting to read DM from file succeeded')\n" if restart else '')
        + ("Path('carbon.bands').write_text('0\\n-5 5\\n2 1 3\\n0 0 0 -1 1\\n0.01 0 0 -1 0.5\\n0.02 0 0 -1 1\\n')\n" if not missing else '')
        + "Path('carbon.DM').write_bytes(b'engine-updated-dm')\nprint('Job completed')\n", encoding='utf-8')
    return {'partition': 'local', 'launcher': 'direct', 'executable': str(Path(sys.executable).resolve()),
            'executable_arguments': [str(script.resolve())]}


def test_sample_delegates_reuses_and_preserves_parent(tmp_path):
    source = _source(tmp_path)
    protocol = locked_protocol(tmp_path)
    profile = fake_engine(tmp_path)
    kwargs = dict(block_name='BandPoints', rows=[[0, 0, 0], [.01, 0, 0], [.02, 0, 0]],
                  n_occupied=1, runs_root=tmp_path / 'sample', profile=profile)
    first = protocol.run_sample(source, **kwargs)
    assert first['result']['gap']['scope'] == 'POINTS'
    assert first['result']['gap']['gap_eV'] == 1.5
    assert source.density_matrix.read_bytes() == b'verified-dm'
    assert protocol.run_sample(source, **kwargs)['result'] == first['result']
    assert len(list((tmp_path / 'sample/runtime/work/bands').glob('attempt-*'))) == 1
    raw = first['attempt_root'] / 'carbon.bands'
    assert first['result']['bands_sha256'] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert parse_bands(raw)['kpoints'] == 3
    validate_property_branch(tmp_path / 'sample/source/bands/input.fdf', 'bands')


@pytest.mark.parametrize('mode', ['failed', 'missing', 'restart'])
def test_no_scientific_result_on_failed_or_missing_output_or_restart(tmp_path, mode):
    source = _source(tmp_path)
    profile = fake_engine(tmp_path, fail=mode=='failed', missing=mode=='missing', restart=mode!='restart')
    result = locked_protocol(tmp_path).run_sample(source, block_name='BandPoints',
        rows=[[0, 0, 0], [.01, 0, 0], [.02, 0, 0]], n_occupied=1, runs_root=tmp_path / 'sample', profile=profile)
    assert result['status'] == 'NOT_EVALUATED'
    assert not (tmp_path / 'sample/result.json').exists()


def test_tampered_parent_stops_before_runtime(tmp_path):
    source = _source(tmp_path)
    source.density_matrix.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='density-matrix SHA'):
        locked_protocol(tmp_path).run_sample(source, block_name='BandPoints', rows=[[0, 0, 0]],
            n_occupied=1, runs_root=tmp_path / 'sample', profile=fake_engine(tmp_path))
    assert not (tmp_path / 'sample/runtime').exists()


def test_transverse_center_uses_fitted_longitudinal_extremum(tmp_path, monkeypatch):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/scientific_protocols/electronic/electronic.cases.json').read_text(encoding='utf-8'))
    synthetic = read_sample(fixture['inputs']['synth-parabolas.bands'])
    calls = []
    source = _source(tmp_path)
    def sample(self, source, **kwargs):
        calls.append(kwargs['rows'])
        root = kwargs['runs_root']; root.mkdir(parents=True, exist_ok=True)
        (root / 'result.json').write_text('{}')
        if kwargs['block_name'] == 'BandLines':
            return {'bands': {'nk': 41, 'E': synthetic['E']}}
        return {'bands': synthetic}
    monkeypatch.setattr(ElectronicAnalysisProtocol, 'run_sample', sample)
    result = locked_protocol(tmp_path).run_masses(source, path_rows=[[1,0,0,0,'G'],[40,.5,.5,0,'X']],
        longitudinal=[1, 1, 0], transverse_directions=[[0, 0, 1]],
        band=2, carrier='electron', n_occupied=1, step_invA=.003,
        points_per_side=20, runs_root=tmp_path / 'mass')
    center = result['center_cartesian_invA']
    reciprocal = _reciprocal_rows(source)
    cart = [sum(calls[2][20][i]*reciprocal[i][j] for i in range(3)) for j in range(3)]
    assert cart == pytest.approx(center)
    assert result['longitudinal']['status'] == 'ESTABLISHED'
    assert (tmp_path / 'mass/path/extremum.json').exists()


def test_reciprocal_rows_are_derived_from_nonorthogonal_verified_geometry(tmp_path):
    from math import pi
    from types import SimpleNamespace
    from test_electronic_property_fanout import BASE
    cell = [[3., .4, .2], [.7, 4., .3], [.1, .8, 5.]]
    path = tmp_path / 'final.fdf'
    text = BASE.replace('10 0 0\n0 10 0\n0 0 10', '\n'.join(' '.join(str(x) for x in r) for r in cell))
    path.write_text(text)
    reciprocal = _reciprocal_rows(SimpleNamespace(final_fdf=path))
    for i in range(3):
        for j in range(3):
            assert sum(cell[i][k]*reciprocal[j][k] for k in range(3)) == pytest.approx(2*pi if i==j else 0, abs=1e-12)


def test_authoring_rejects_pi_a_before_preparation(tmp_path):
    path = tmp_path / 'bad.fdf'
    path.write_text('SystemLabel si\nMD.TypeOfRun CG\nMD.NumCGSteps 0\nBandLinesScale pi/a\n%block BandLines\n1 0 0 0 G\n2 .5 0 0 X\n%endblock BandLines\n')
    with pytest.raises(ValueError, match='ReciprocalLatticeVectors'):
        BandStructureTaskBuilder._band_spec(path)
