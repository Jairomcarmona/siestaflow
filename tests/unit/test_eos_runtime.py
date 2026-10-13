"""Synthetic canonical EOS runtime integration; never launches SIESTA."""
import json
import sys
from pathlib import Path

import pytest
from qraft.protocols.eos import EosProtocol

ROOT = Path(__file__).parents[1] / 'fixtures/scientific_protocols/eos'
VECTORS = json.loads((ROOT / 'wf-eos.cases.json').read_text(encoding='utf-8'))
POLICY = next(c['policy'] for c in VECTORS['cases'] if c['id'] == 'eos-table-01')
POLICY = {**POLICY, 'volume_factors': [0.94, 0.96, 0.98, 1, 1.02, 1.04, 1.06]}

FDF = """SystemLabel si
NetCharge 0
Spin non-polarized
NumberOfSpecies 1
NumberOfAtoms 1
PAO.BasisSize SZP
XC.functional GGA
XC.authors PBE
LatticeConstant 1 Ang
%block ChemicalSpeciesLabel
1 14 Si
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10 0 0
0 10 0
0 0 10
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
%endblock AtomicCoordinatesAndAtomicSpecies
%block kgrid.MonkhorstPack
6 0 0 0.5
0 6 0 0.5
0 0 6 0.5
%endblock kgrid.MonkhorstPack
MeshCutoff 154 Ry
Mesh.Sizes [30 30 30]
MD.TypeOfRun CG
MD.Steps 20
MD.VariableCell T
MD.TargetPressure 0 GPa
MD.MaxStressTol 0.05 GPa
MD.MaxForceTol 0.01 eV/Ang
"""


def prepare(root, *, mesh_bad=False):
    fdf = root / 'input.fdf'
    fdf.write_text(FDF, encoding='utf-8')
    (root / 'Si.psf').write_text('synthetic pseudo\n', encoding='utf-8')
    script = root / 'engine.py'
    script.write_text("""import sys, re
from pathlib import Path
text = Path(sys.argv[-1]).read_text()
block = re.search(r'%block LatticeVectors\\s*(.*?)%endblock', text, re.S).group(1)
cell = [[float(v) for v in row.split()] for row in block.splitlines() if row.strip()]
a,b,c=cell
volume=a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
strain=(1000/volume)**(2/3)-1
energy=-100+9*1000*(100/160.21766208)/16*(strain**3*4.5+strain**2*(6-4*(1000/volume)**(2/3)))
Path('si.STRUCT_OUT').write_text('10 0 0\\n0 10 0\\n0 0 10\\n1\\n1 0 0 0 0\\n')
print('Siesta started')
print('SCF cycle converged')
print('outcoor: Relaxed')
print('InitMesh: MESH = 30 x 30 x 30')
print('InitMesh: Mesh cutoff (required, used) = 154.000 250.000 Ry')
print('siesta: Atomic forces (eV/Ang):')
print(' Tot 0 0 0')
print(' Max 0.001')
print('siesta: FreeEng =', format(energy,'.12f'))
print('Job completed')
""", encoding='utf-8')
    if mesh_bad:
        script.write_text(script.read_text().replace("print('InitMesh: MESH = 30 x 30 x 30')", "print('InitMesh: MESH = 24 x 24 x 24' if 'MD.VariableCell F' in text else 'InitMesh: MESH = 30 x 30 x 30')"), encoding='utf-8')
    return fdf, {'launcher': 'direct', 'partition': 'local', 'executable': sys.executable, 'executable_arguments': [str(script)]}


def test_eos_reference_and_siblings_are_canonical_and_reused(tmp_path):
    fdf, overrides = prepare(tmp_path)
    root = tmp_path / 'runs'
    first = EosProtocol().run(fdf, policy=POLICY, runs_root=root, overrides=overrides)
    assert first['status'] == 'ESTABLISHED', first
    assert first['authority'] == 'PROVISIONAL'
    assert first['fit']['V0_A3'] == pytest.approx(1000)
    assert len(first['points']) == 7
    for rendered in (root / 'points/source').glob('volume-*/input.fdf'):
        assert 'Mesh.Sizes [30 30 30]' in rendered.read_text()
    second = EosProtocol().run(fdf, policy=POLICY, runs_root=root, overrides=overrides)
    assert second == first
    assert len(list(root.rglob('attempt-0001'))) == 8
    assert not list(root.rglob('attempt-0002'))
    changed = {**POLICY, 'volume_factors': [1.0]}
    with pytest.raises(ValueError, match='immutable'):
        EosProtocol().run(fdf, policy=changed, runs_root=root, overrides=overrides)


def test_eos_rejects_observed_mesh_change(tmp_path):
    fdf, overrides = prepare(tmp_path, mesh_bad=True)
    result = EosProtocol().run(fdf, policy=POLICY, runs_root=tmp_path / 'runs', overrides=overrides)
    assert result == {'status': 'REJECTED', 'reasons': ['MESH_INCONSISTENT']}


@pytest.mark.parametrize('change', ['spin', 'kgrid', 'pressure'])
def test_eos_invalid_reference_fails_before_launch(tmp_path, change):
    fdf, overrides = prepare(tmp_path)
    text = fdf.read_text()
    if change == 'spin':
        text = text.replace('Spin non-polarized','Spin polarized')
    elif change == 'kgrid':
        text += 'kgrid.Cutoff 10 Ang\n'
    else:
        text = text.replace('MD.TargetPressure 0 GPa', 'MD.TargetPressure 1 GPa')
    fdf.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError):
        EosProtocol().run(fdf, policy=POLICY, runs_root=tmp_path / 'runs', overrides=overrides)
    assert not (tmp_path / 'runs').exists()


@pytest.mark.parametrize('replace,expected', [
    (('250.000', '100.000'), {'status': 'REJECTED', 'reasons': ['MESH_CUTOFF_BELOW_REQUEST']}),
    (("print('InitMesh: MESH = 30 x 30 x 30')", "print('InitMesh: MESH = 24 x 24 x 24')\nprint('InitMesh: MESH = 30 x 30 x 30')"), {'status': 'REJECTED', 'reasons': ['MESH_CHANGED_DURING_RELAXATION']}),
    (('Tot 0 0 0', 'Tot 0.02 0 0'), {'status': 'REVIEW', 'reasons': ['NET_FORCE_ABOVE_TOLERANCE']}),
])
def test_eos_reference_presets_gates_prevent_point_launch(tmp_path, replace, expected):
    fdf, overrides = prepare(tmp_path)
    script = tmp_path / 'engine.py'
    script.write_text(script.read_text().replace(*replace), encoding='utf-8')
    result = EosProtocol().run(fdf, policy=POLICY, runs_root=tmp_path / 'runs', overrides=overrides)
    assert result == expected
    assert not (tmp_path / 'runs/points').exists()


def test_mesh_sizes_bare_form_is_rejected_before_runtime(tmp_path):
    fdf, overrides = prepare(tmp_path)
    fdf.write_text(fdf.read_text().replace('Mesh.Sizes [30 30 30]', 'Mesh.Sizes 30 30 30'), encoding='utf-8')
    with pytest.raises(ValueError, match='bracketed list or block'):
        EosProtocol().run(fdf, policy=POLICY, runs_root=tmp_path / 'runs', overrides=overrides)
    assert not (tmp_path / 'runs').exists()


def test_mesh_sizes_block_is_supported_and_preserved(tmp_path):
    fdf, overrides = prepare(tmp_path)
    fdf.write_text(fdf.read_text().replace('Mesh.Sizes [30 30 30]', '%block Mesh.Sizes\n30 30 30\n%endblock Mesh.Sizes'), encoding='utf-8')
    result = EosProtocol().run(fdf, policy=POLICY, runs_root=tmp_path / 'runs', overrides=overrides)
    assert result['status'] == 'ESTABLISHED'
    assert '%block Mesh.Sizes\n30 30 30\n%endblock Mesh.Sizes' in (tmp_path / 'runs/points/source/volume-000/input.fdf').read_text()

@pytest.mark.parametrize('missing',['NetCharge 0\n','Spin non-polarized\n'])
def test_missing_governed_source_is_rejected_before_launch(tmp_path,missing):
    fdf,overrides=prepare(tmp_path)
    fdf.write_text(fdf.read_text().replace(missing,''))
    with pytest.raises(ValueError,match='UNDECLARED_GOVERNED_VALUE'):
        EosProtocol().run(fdf,policy=POLICY,runs_root=tmp_path/'runs',overrides=overrides)
    assert not (tmp_path/'runs').exists()
