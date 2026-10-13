"""Accepted byte-exact WF-EOS vectors evaluated by native QRAFT code."""
import hashlib
import json
from pathlib import Path

import pytest
from qraft.engines.siesta.eos import check_deformation, deform, final_energy, evaluate, volume

ROOT = Path(__file__).parents[1] / 'fixtures/scientific_protocols/eos'
VECTORS = json.loads((ROOT / 'wf-eos.cases.json').read_text(encoding='utf-8'))
DIGEST = '4839b429ea3c96be9ec1099fdfcec7dea697439c186753fb46ee72967541ed84'


def test_eos_fixture_hash():
    assert hashlib.sha256((ROOT / 'wf-eos.cases.json').read_bytes()).hexdigest() == DIGEST
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert DIGEST in readme
    assert '72c749d7fffaf13f2f92d559674bd888e203084e' in readme


def compare(actual, expected):
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        assert actual == expected
    elif isinstance(expected, (int, float)):
        tolerance = VECTORS['arithmetic_tolerance']
        assert actual == pytest.approx(expected, abs=tolerance['abs_meV'], rel=tolerance['rel'])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            compare(a, b)
    else:
        assert set(expected).issubset(actual)
        for key in expected:
            compare(actual[key], expected[key])


@pytest.mark.parametrize('case', VECTORS['cases'], ids=lambda c: c['id'])
def test_eos_vector(case):
    if case['kind'] == 'deformation':
        actual = check_deformation(case['reference'], case['candidate'], case['factor'], case['tolerance'])
    elif case['kind'] == 'energy':
        actual = final_energy(case['stdout'], case['quantity'])
    else:
        actual = evaluate(case['table'], case['policy'])
    compare(actual, case['expect'])


def test_deformation_scales_cell_and_cartesian_positions_preserving_atom_order():
    case = VECTORS['cases'][0]
    candidate = deform(case['reference'], case['factor'])
    assert check_deformation(case['reference'], candidate, case['factor'], case['tolerance']) is None
    assert volume(candidate['cell']) == pytest.approx(volume(case['reference']['cell']) * case['factor'])
