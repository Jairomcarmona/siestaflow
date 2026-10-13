"""V-4 is reached through the canonical single-calculation runtime."""
from pathlib import Path
import sys
import pytest
from qraft.protocols.presets import VariableCellProtocol


BASE='''SystemLabel si
NumberOfAtoms 2
NumberOfSpecies 1
XC.functional GGA
XC.authors PBE
MeshCutoff 154 Ry
PAO.BasisSize SZP
LatticeConstant 5.43 Ang
%block ChemicalSpeciesLabel
1 14 Si
%endblock ChemicalSpeciesLabel
%block LatticeVectors
0 .5 .5
.5 0 .5
.5 .5 0
%endblock LatticeVectors
AtomicCoordinatesFormat Fractional
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
.25 .25 .25 1
%endblock AtomicCoordinatesAndAtomicSpecies
MD.TypeOfRun CG
MD.Steps 200
MD.VariableCell T
MD.TargetPressure 0 GPa
MD.MaxStressTol .05 GPa
MD.MaxForceTol .01 eV/Ang
Mesh.Sizes [30 30 30]
'''


def setup(root, *, converged=True):
    fdf=root/'input.fdf';fdf.write_text(BASE)
    (root/'Si.psf').write_text('synthetic pseudo')
    struct=(Path(__file__).parents[1]/'fixtures/variable_cell/si-fixed.STRUCT_OUT').read_text()
    stdout='Siesta started\nSCF cycle converged\nInitMesh: MESH = 30 x 30 x 30\nInitMesh: Mesh cutoff (required, used) = 154 241 Ry\nsiesta: Atomic forces (eV/Ang):\n   Tot 0 0 0\n   Max 0.001\noutcoor: Relaxed\nsiesta: FreeEng = -10.000000\nJob completed\n'
    if not converged:
        stdout=stdout.replace('SCF cycle converged','SCF did not converge').replace('Job completed','Run aborted')
    script=root/'fake.py';script.write_text('from pathlib import Path\n'+
        "Path('si.STRUCT_OUT').write_text("+repr(struct)+')\nprint('+repr(stdout)+')\n')
    return fdf,dict(launcher='direct',partition='local',executable=sys.executable,executable_arguments=[str(script)])


def test_variable_cell_runtime_reports_native_symmetry_and_reuses_attempt(tmp_path):
    fdf,profile=setup(tmp_path)
    first=VariableCellProtocol().run(fdf,runs_root=tmp_path/'run',overrides=profile)
    assert first['assessment']=={'status':'ACCEPTED','reasons':[]}
    assert first['symmetry']['final_space_group']==227
    assert first['authority']=='PROVISIONAL'
    second=VariableCellProtocol().run(fdf,runs_root=tmp_path/'run',overrides=profile)
    assert second['execution']['status']=='REUSED_VALIDATED_ATTEMPT'
    assert first['source_struct_out_sha256']==second['source_struct_out_sha256']


def test_technical_failure_has_no_symmetry_assessment(tmp_path):
    fdf,profile=setup(tmp_path,converged=False)
    result=VariableCellProtocol().run(fdf,runs_root=tmp_path/'run',overrides=profile)
    assert result['scientific_decision']=='NOT_EVALUATED'
    assert 'assessment' not in result


@pytest.mark.parametrize('label', ['MD.TargetPressure','MD.MaxStressTol','Mesh.Sizes'])
def test_missing_required_controls_stop_before_launch(tmp_path,label):
    fdf,profile=setup(tmp_path)
    fdf.write_text('\n'.join(l for l in fdf.read_text().splitlines() if not l.startswith(label))+'\n')
    with pytest.raises(ValueError):
        VariableCellProtocol().run(fdf,runs_root=tmp_path/'run',overrides=profile)
    assert not (tmp_path/'run').exists()
