"""Operator-approved JSON documents delivered by the installed wheel."""
from copy import deepcopy
import re

_DOCUMENTS = {
    'qraft.electronic.policy@1': dict(fit_halfwidth_invA=.05, min_points_per_side=3, degeneracy_meV=5,
        straightness_invA=2e-5, energy_match_eV=1e-4, weight_rounding=5e-6),
    'qraft.presets.policy@1': dict(max_reference_force_eV_A=.01, fc_displacement_A=.02,
        imaginary_tol_cm1=20, symprec_A=.01),
    'qraft.eos.policy@1': dict(policy_id='qraft.eos.policy@1', volume_factors=[.94,.96,.98,1.,1.02,1.04,1.06],
        energy_quantity='free_energy', relaxation_mode='fixed-fractional', min_points=7,
        min_points_each_side=2, max_rms_meV_per_atom=.5, max_rel_dV0=.005, max_rel_dB0=.05),
    'qraft.surface.policy@1': dict(potential='VH', allow_vt=False, window_A=1.0, step_A=.25,
        margin_A=4.0, width_min_A=2.0, slope_max_eV_per_A=.005, range_max_meV=5.0,
        stability_meV=3.0, perpendicular_tol_deg=.01, convergence_meV=10.0),
}


def scientific_policy_document(policy_id, *, rule_document=None):
    """Return a detached JSON value; unknown IDs never acquire defaults."""
    if rule_document is not None:
        if policy_id in _DOCUMENTS or not re.fullmatch(r'[a-z][a-z0-9_.-]*@[1-9][0-9]*', policy_id) or rule_document.get('rule_id') != policy_id:
            raise ValueError('Explicit versioned convergence rule ID must agree with the document')
        from .scientific_convergence import MeshConvergenceRule
        from .scientific_kgrid import KGridConvergenceRule
        model = {'Mesh.Cutoff': MeshConvergenceRule, 'kgrid.MonkhorstPack': KGridConvergenceRule}.get(rule_document.get('parameter'))
        if model is None:
            raise ValueError('Unsupported convergence rule')
        model.from_mapping(rule_document)
        return deepcopy(rule_document)
    if policy_id not in _DOCUMENTS:
        raise ValueError('Unknown approved scientific policy: '+str(policy_id))
    return deepcopy(_DOCUMENTS[policy_id])


def scientific_policy_evidence(policy_id, *, rule_document=None):
    """Native extensible artifact; its digest stays QRAFT's original algorithm."""
    from .contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
    document = scientific_policy_document(policy_id, rule_document=rule_document)
    payload = dict(schema_version='1.0', artifact_id='scientific-policy',
                   artifact_type='qraft.scientific-policy', authority='PROVISIONAL',
                   policy_id=policy_id, policy_document=document,
                   origin='operator rule' if rule_document is not None else 'approved policy')
    if policy_id=='qraft.presets.policy@1':
        payload['protocol_ids']=['qraft.preset.s-'+str(n).zfill(2)+'@1' for n in range(1,9)]
    return ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer='qraft.scientific-policies', payload=payload)
