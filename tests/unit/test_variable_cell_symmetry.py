"""Own tests: measured Si distortion and a genuine symmetry change, not vectors."""
from copy import deepcopy
from pathlib import Path
import pytest
from qraft.engines.siesta.variable_cell import space_group, assess_variable_cell, SYMPREC_A
from qraft.engines.siesta.relaxation import parse_struct_out


def initial():
    return {'cell':[[0,2.715,2.715],[2.715,0,2.715],[2.715,2.715,0]],
        'atoms':[{'index':1,'species_index':1,'coordinates':[0,0,0]},
                 {'index':2,'species_index':1,'coordinates':[1.3575]*3}]}


def run():
    return dict(completed=True,scf_converged=1,relaxed=True,meshes=[[30]*3],
        mesh_cutoff_Ry={'required':154,'used_min':241},forces=[{'tot':[0,0,0]}])


def test_measured_fixed_mesh_silicon_does_not_create_false_transition():
    path=Path(__file__).parents[1]/'fixtures/variable_cell/si-fixed.STRUCT_OUT'
    final=parse_struct_out(path)
    assessment,evidence=assess_variable_cell(run(),{'variable_cell':True,'max_force_tol_eV_A':.01},initial(),final)
    assert assessment=={'status':'ACCEPTED','reasons':[]}
    assert evidence['initial_space_group']==evidence['final_space_group']==227
    assert evidence['symprec_A']==SYMPREC_A==.01
    import spglib
    from qraft.engines.siesta.eos import fractional
    positions=fractional(final['cell'],[a['coordinates'] for a in final['atoms']])
    assert spglib.get_symmetry_dataset((final['cell'],positions,[1,1]),symprec=.005).number==166


def test_changed_group_requires_review_and_preserves_other_rejections():
    changed=deepcopy(initial()); changed['atoms'][1]['coordinates'][0]+=.3
    result,evidence=assess_variable_cell(run(),{'variable_cell':True,'max_force_tol_eV_A':.01},initial(),changed)
    assert evidence['initial_space_group']!=evidence['final_space_group']
    assert result=={'status':'REVIEW','reasons':['SYMMETRY_CHANGED']}
    failed=run();failed['relaxed']=False
    result,_=assess_variable_cell(failed,{'variable_cell':True,'max_force_tol_eV_A':.01},initial(),changed)
    assert result=={'status':'REJECTED','reasons':['NOT_RELAXED','SYMMETRY_CHANGED']}


def test_atom_mapping_cannot_change_during_symmetry_comparison():
    changed=deepcopy(initial());changed['atoms'].reverse()
    with pytest.raises(ValueError,match='ATOM_MAP_MISMATCH'):
        assess_variable_cell(run(),{'variable_cell':True,'max_force_tol_eV_A':.01},initial(),changed)
