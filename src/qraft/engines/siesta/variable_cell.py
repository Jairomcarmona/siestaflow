"""PRESETS V-4 with the Si-measured, operator-approved 0.01 Angstrom policy."""
from .eos import fractional
from .presets import evaluate_relaxation
from ...scientific_policies import scientific_policy_document

SYMPREC_A = scientific_policy_document('qraft.presets.policy@1')['symprec_A']


def space_group(geometry):
    import spglib
    positions = fractional(geometry['cell'], [a['coordinates'] for a in geometry['atoms']])
    types = [a['species_index'] for a in geometry['atoms']]
    dataset = spglib.get_symmetry_dataset((geometry['cell'], positions, types), symprec=SYMPREC_A)
    if dataset is None:
        raise ValueError('Space group could not be established from the supplied geometry')
    return int(dataset.number)


def assess_variable_cell(run, intent, initial, final):
    if [(a['index'],a['species_index']) for a in initial['atoms']] != [(a['index'],a['species_index']) for a in final['atoms']]:
        raise ValueError('ATOM_MAP_MISMATCH')
    assessment = evaluate_relaxation(run, intent)
    first, last = space_group(initial), space_group(final)
    if first != last:
        assessment['reasons'].append('SYMMETRY_CHANGED')
        if assessment['status']=='ACCEPTED':
            assessment['status']='REVIEW'
    return assessment, {'initial_space_group':first, 'final_space_group':last,
                        'symprec_A':SYMPREC_A, 'provider':'spglib'}
