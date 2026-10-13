"""R5 operator-approved grouping; independent synthetic cases, not vectors."""
import pytest
from qraft.engines.siesta.electronic_analysis import POLICY, fat_groups


def sample(energies):
    # Deliberately include negative Mulliken weights and an unsorted spectrum.
    count = len(energies)
    bands = dict(nk=1, nspin=1, nbands=count, E=[[energies]])
    common = dict(nk=1, nspin=1, nbands=count, min_band=1, E=[energies])
    return bands, {'a': {**common, 'W': [[-.25]*count]},
                   'b': {**common, 'W': [[1.25]*count]}}


@pytest.mark.parametrize('energies,sizes', [([0.], [1]), ([0., .003], [2]),
    ([.006, 0., .003], [3]), ([0., .005, .010], [3]),
    ([0., .005, .010001], [2, 1])])
def test_maximal_chains_and_unclipped_group_weights(energies, sizes):
    bands, sets = sample(energies)
    groups = fat_groups(bands, sets, POLICY)
    assert [g['size'] for g in groups] == sizes
    assert [g['bands'] for g in groups] == [[i+1 for i in sorted(range(len(energies)), key=energies.__getitem__)][sum(sizes[:j]):sum(sizes[:j+1])]
                                           for j in range(len(sizes))]
    for group in groups:
        assert group['weights'] == {'a': -.25*group['size'], 'b': 1.25*group['size']}
        assert 'individual_weights' not in group


def test_k_and_spin_are_independent():
    bands = dict(nk=2, nspin=2, nbands=2, E=[[[0., .001], [0., .1]], [[0., .1], [0., .001]]])
    common = dict(nk=2, nspin=2, nbands=2, min_band=1, E=[[0., .001, 0., .1], [0., .1, 0., .001]])
    groups = fat_groups(bands, {'all': {**common, 'W': [[1.]*4, [1.]*4]}}, POLICY)
    assert [(g['k_index'], g['spin'], g['size']) for g in groups] == [(0,0,2), (0,1,1), (0,1,1), (1,0,1), (1,0,1), (1,1,2)]


def test_partial_degenerate_group_cannot_be_presented():
    bands, sets = sample([0., .001])
    for value in sets.values():
        value.update(nbands=1, E=[[0.]], W=[value['W'][0][:1]])
    with pytest.raises(ValueError, match='cuts a degenerate group'):
        fat_groups(bands, sets, POLICY)
