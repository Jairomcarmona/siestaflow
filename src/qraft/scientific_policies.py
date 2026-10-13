"""Operator-approved JSON documents delivered by the installed wheel."""
from copy import deepcopy

_DOCUMENTS = {
    'qraft.electronic.policy@1': dict(fit_halfwidth_invA=.05, min_points_per_side=3, degeneracy_meV=5,
        straightness_invA=2e-5, energy_match_eV=1e-4, weight_rounding=5e-6),
    'qraft.presets.policy@1': dict(max_reference_force_eV_A=.01, fc_displacement_A=.02,
        imaginary_tol_cm1=20, symprec_A=.01),
    'qraft.eos.policy@1': dict(policy_id='qraft.eos.policy@1', volume_factors=[.94,.96,.98,1.,1.02,1.04,1.06],
        energy_quantity='free_energy', relaxation_mode='fixed-fractional', min_points=7,
        min_points_each_side=2, max_rms_meV_per_atom=.5, max_rel_dV0=.005, max_rel_dB0=.05),
}


def scientific_policy_document(policy_id):
    """Return a detached JSON value; unknown IDs never acquire defaults."""
    if policy_id not in _DOCUMENTS:
        raise ValueError('Unknown approved scientific policy: '+str(policy_id))
    return deepcopy(_DOCUMENTS[policy_id])
