"""Preset wrappers exercise the canonical runtime with synthetic engine output."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from qraft.protocols.presets import MoleculeProtocol, MolecularVibrationProtocol, _attempt_directory

VECTORS = json.loads((Path(__file__).parents[1] / 'fixtures/scientific_protocols/presets/presets.cases.json').read_text(encoding='utf-8'))


def input_file(root, cart, *, fc=False):
    root.mkdir(parents=True, exist_ok=True)
    text = "SystemLabel mol\nNumberOfSpecies 1\nNetCharge 0\nXC.functional GGA\nXC.authors PBE\nPAO.BasisSize DZP\nMeshCutoff 200 Ry\nLatticeConstant 1 Ang\nAtomicCoordinatesFormat Ang\n"
    text += f"NumberOfAtoms {len(cart)}\n"
    text += "%block ChemicalSpeciesLabel\n1 1 H\n%endblock ChemicalSpeciesLabel\n"
    text += "%block LatticeVectors\n10 0 0\n0 10 0\n0 0 10\n%endblock LatticeVectors\n"
    text += "%block AtomicCoordinatesAndAtomicSpecies\n" + ''.join(' '.join(map(str, row)) + ' 1\n' for row in cart) + "%endblock AtomicCoordinatesAndAtomicSpecies\n"
    if fc:
        text += f"MD.TypeOfRun FC\nFC.Displacement 0.02 Ang\nFC.First 1\nFC.Last {len(cart)}\n"
    path = root / ('fc.fdf' if fc else 'reference.fdf')
    path.write_text(text, encoding='utf-8')
    (root / 'H.psf').write_text('synthetic pseudo\n', encoding='utf-8')
    return path


def executable(root, stdout, fc=None):
    script = root / 'engine.py'
    text = 'from pathlib import Path\n'
    text += "Path('launch-count').write_text('one')\n"
    if fc is not None:
        text += "Path('mol.FC').write_bytes(" + repr(fc.encode('utf-8')) + " )\n"
    text += 'print(' + repr('Siesta started\n' + stdout + '\nsiesta: FreeEng = -10.000000\n') + ')\n'
    script.write_text(text, encoding='utf-8')
    return {'launcher': 'direct', 'partition': 'local', 'executable': sys.executable, 'executable_arguments': [str(script)]}


def test_molecule_canonical_attempt_and_reuse(tmp_path):
    case = next(c for c in VECTORS['cases'] if c['id'] == 'pre-mol-01')
    fdf = input_file(tmp_path, [[0, 0, 0]])
    overrides = executable(tmp_path, case['stdout'])
    root = tmp_path / 'runs'
    result = MoleculeProtocol().run(fdf, intent=case['intent'], overrides=overrides, runs_root=root)
    assert result['assessment'] == case['expect']
    attempt = _attempt_directory(result['execution'], root)
    assert result['source_stdout_sha256'] == hashlib.sha256((attempt / result['execution']['attempt']['stdout']).read_bytes()).hexdigest()
    second = MoleculeProtocol().run(fdf, intent=case['intent'], overrides=overrides, runs_root=root)
    assert second['execution']['status'] == 'REUSED_VALIDATED_ATTEMPT'
    assert second['assessment'] == result['assessment']
    assert not (attempt.parent / 'attempt-0002').exists()


@pytest.mark.parametrize('change', ['charge', 'kgrid'])
def test_molecule_rejects_inconsistent_input_before_launch(tmp_path, change):
    fdf = input_file(tmp_path, [[0, 0, 0]])
    if change == 'charge':
        fdf.write_text(fdf.read_text().replace('NetCharge 0', 'NetCharge 1'))
    else:
        with fdf.open('a') as handle:
            handle.write('%block kgrid.MonkhorstPack\n2 0 0 0\n0 2 0 0\n0 0 2 0\n%endblock kgrid.MonkhorstPack\n')
    root = tmp_path / 'runs'
    with pytest.raises(ValueError):
        MoleculeProtocol().run(fdf, intent={'net_charge': 0}, runs_root=root, overrides=executable(tmp_path, 'Job completed'))
    assert not root.exists()


def test_molecule_observed_charge_mismatch_cannot_be_accepted(tmp_path):
    case = next(c for c in VECTORS['cases'] if c['id'] == 'pre-mol-01')
    fdf = input_file(tmp_path, [[0, 0, 0]])
    stdout = case['stdout'].replace('redata: Net charge of the system', 'redata: Missing charge')
    with pytest.raises(ValueError, match='observed molecular charge'):
        MoleculeProtocol().run(fdf, intent={'net_charge': 0}, runs_root=tmp_path / 'runs', overrides=executable(tmp_path, stdout))


@pytest.mark.parametrize('case', [c for c in VECTORS['cases'] if c['kind'] == 'vibrations'], ids=lambda c: c['id'])
def test_fc_uses_canonical_protocol_and_same_model_reference(tmp_path, case):
    reference = input_file(tmp_path, case['cart'])
    fdf = input_file(tmp_path, case['cart'], fc=True)
    policy = {**case['policy'], 'fc_displacement_A': 0.02}
    result = MolecularVibrationProtocol().run(fdf, reference_fdf=reference, cart=case['cart'], masses=case['masses'], policy=policy, overrides=executable(tmp_path, case['stdout'], case['fc']), runs_root=tmp_path / 'runs')
    assert result['assessment']['status'] == case['expect']['status']
    assert result['assessment']['reasons'] == case['expect']['reasons']
    assert result['assessment']['vibrational_cm1'] == pytest.approx(case['expect']['vibrational_cm1'], rel=VECTORS['arithmetic_tolerance']['rel'], abs=VECTORS['arithmetic_tolerance']['abs_meV'])
    assert result['source_fc_sha256'] == hashlib.sha256(case['fc'].encode()).hexdigest()
    reference.write_text(reference.read_text().replace('DZP', 'SZP'))
    with pytest.raises(ValueError, match='GEOMETRY_NOT_RELAXED'):
        MolecularVibrationProtocol().run(fdf, reference_fdf=reference, cart=case['cart'], masses=case['masses'], policy=policy, runs_root=tmp_path / 'blocked')
    assert not (tmp_path / 'blocked').exists()


def test_technical_failure_preserves_observations_without_scientific_classification(tmp_path):
    case = next(c for c in VECTORS['cases'] if c['id'] == 'pre-mol-01')
    fdf = input_file(tmp_path, [[0, 0, 0]])
    overrides = executable(tmp_path, case['stdout'])
    script = tmp_path / 'engine.py'
    script.write_text(script.read_text().replace('siesta: FreeEng = -10.000000', 'energy deliberately absent').replace('Siesta started', 'banner deliberately absent'), encoding='utf-8')
    result = MoleculeProtocol().run(fdf, intent=case['intent'], overrides=overrides, runs_root=tmp_path / 'runs')
    assert result['execution']['attempt']['result']['technical_validation']['status'] != 'PASS'
    assert result['scientific_decision'] == 'NOT_EVALUATED'
    assert 'assessment' not in result
    stdout = _attempt_directory(result['execution'], tmp_path / 'runs') / result['execution']['attempt']['stdout']
    assert 'SCF cycle converged' in stdout.read_text()
    assert 'Job completed' in stdout.read_text()
