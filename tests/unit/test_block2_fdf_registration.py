"""R12 registration and governed declarations; no engine is launched."""
from pathlib import Path
import hashlib,json
import pytest
from qraft.api import SiestaContextualValidator
from qraft.engines.siesta.fdf_registry import FDFRegistry

BASE='''SystemLabel si
NumberOfAtoms 1
NumberOfSpecies 1
XC.functional GGA
XC.authors PBE
NetCharge 0
Spin non-polarized
MeshCutoff 200 Ry
%block ChemicalSpeciesLabel
1 14 Si
%endblock
LatticeConstant 1 Ang
%block LatticeVectors
10 0 0
0 10 0
0 0 10
%endblock
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0.0 0.0 0.0 1
%endblock
'''

def report(tmp_path,extra):
    path=tmp_path/'input.fdf';path.write_text(BASE+extra,encoding='utf-8')
    return SiestaContextualValidator().validate_path(path)

@pytest.mark.parametrize('extra',[
 'MD.TargetPressure 0 GPa\nMD.MaxStressTol 0.1 GPa\nMesh.Sizes [30 30 30]\n',
 '%block Mesh.Sizes\n30 30 30\n%endblock\n',
 '%block Geometry.Constraints\natom 1\n%endblock\n',
 'SaveElectrostaticPotential T\nWriteDenchar T\nWriteWaveFunctions T\n',
 '%block BandPoints\n0.0 0.0 0.0\n%endblock\nSaveHS T\nWFS.Write.For.Bands T\n',
])
def test_all_swept_forms_are_registered(tmp_path,extra):
    result=report(tmp_path,'MD.TypeOfRun CG\nMD.Steps 0\n'+extra)
    assert result.status.value=='PASS',result.findings

def test_fc_requires_its_declared_controls_instead_of_cg_steps(tmp_path):
    controls='FC.Displacement 0.02 Ang\nFC.First 1\nFC.Last 1\n'
    assert report(tmp_path,'MD.TypeOfRun fC\n'+controls).status.value=='PASS'
    for line in controls.splitlines():
        result=report(tmp_path,'MD.TypeOfRun FC\n'+controls.replace(line+'\n',''))
        assert any(f.code=='UNDECLARED_GOVERNED_VALUE' and line.split()[0] in f.message for f in result.findings)
    assert any(f.code=='UNDECLARED_GOVERNED_VALUE' for f in report(tmp_path,'MD.TypeOfRun CG\n').findings)

@pytest.mark.parametrize('extra,code',[
 ('MD.TargetPressure abc GPa\n','REAL_EXPECTED'),
 ('MD.TargetPressure 0 Ang\n','UNIT_DIMENSION_MISMATCH'),
 ('MD.MaxStressTol 0.1\n','UNIT_MISSING'),
 ('FC.Displacement 0.02 Ry\n','UNIT_DIMENSION_MISMATCH'),
 ('FC.First 1.5\n','INTEGER_EXPECTED'),
 ('WriteDenchar maybe\n','KEYWORD_VALUE_INVALID'),
 ('Mesh.Sizes [30 30]\n','KEYWORD_VALUE_INVALID'),
 ('Mesh.Sizes 30 30 30\n','KEYWORD_VALUE_INVALID'),
 ('%block Mesh.Sizes\n30 0 30\n%endblock\n','KEYWORD_VALUE_INVALID'),
])
def test_registered_types_and_units_remain_fail_closed(tmp_path,extra,code):
    result=report(tmp_path,'MD.TypeOfRun CG\nMD.Steps 0\n'+extra)
    assert result.status.value=='FAIL'
    assert any(f.code==code for f in result.findings)

def test_unknown_labels_and_mutation_permissions_are_not_promoted(tmp_path):
    assert report(tmp_path,'MD.TypeOfRun CG\nMD.Steps 0\nNotASiestaKeyword T\n').status.value=='REVIEW'
    for label in ['BandPoints','SaveHS','Mesh.Sizes','Geometry.Constraints','FC.First']:
        with pytest.raises(PermissionError):FDFRegistry.load_default().require_mutable(label)

def test_real_keyword_query_fixture_is_unchanged():
    path=Path(__file__).parents[1]/'fixtures/block2_fdf_registration/provenance.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='2d7e71851a97467958014d51089ec271a31b6d3901947637dbeca04e1bf9cb75'
    data=json.loads(path.read_bytes())
    assert len(data['records'])==13
    for record in data['records']:
        assert FDFRegistry.load_default().get(record['label']) is not None
        assert record['observed_lines'] and len(record['log_sha256'])==64
