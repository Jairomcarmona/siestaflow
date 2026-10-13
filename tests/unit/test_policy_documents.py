"""Explicit operator convergence IDs and unchanged rule JSON, not approval."""
from copy import deepcopy
import pytest
from qraft.api import scientific_policy_document, MeshConvergenceRule, MeshConvergenceEvaluator
from test_scientific_convergence import rule_data


def test_explicit_convergence_rule_is_delivered_without_normalizing_values():
    document = rule_data(); document['rule_id']='operator.mesh.policy@2'
    document['energy_tolerance']['value']='1.0000'
    delivered = scientific_policy_document(document['rule_id'], rule_document=document)
    assert delivered==document
    assert delivered['energy_tolerance']['value']=='1.0000'
    delivered['eggbox']['required']=False
    assert document['eggbox']['required'] is True
    assert MeshConvergenceRule and MeshConvergenceEvaluator


@pytest.mark.parametrize('change', ['legacy', 'mismatch', 'eggbox', 'reserved'])
def test_unversioned_mismatched_incomplete_or_reserved_rules_rejected(change):
    document=rule_data();document['rule_id']='operator.mesh.policy@2'
    policy_id=document['rule_id']
    if change=='legacy':
        policy_id=document['rule_id']='TEST_MESH_V1'
    elif change=='mismatch':
        policy_id='operator.mesh.policy@3'
    elif change=='eggbox':
        document['eggbox']['required']=False
    else:
        policy_id=document['rule_id']='qraft.eos.policy@1'
    with pytest.raises(ValueError):
        scientific_policy_document(policy_id,rule_document=document)
