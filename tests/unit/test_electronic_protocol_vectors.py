"""Accepted WF-ELECTRONIC vectors against the native implementation."""
import hashlib
import json
from pathlib import Path
import pytest
from qraft.engines.siesta.electronic_analysis import band_run_check, parse_bands, band_gap, directional_mass, parse_eigfat, fat_partition

ROOT = Path(__file__).parents[1] / 'fixtures/scientific_protocols/electronic'
VECTORS = json.loads((ROOT / 'electronic.cases.json').read_text(encoding='utf-8'))
DIGEST = 'b739a7d36bcd1a1c773930c5803e4fcc513973b62988d27a3760bef2ce5e9e3f'


def test_electronic_fixture_hash():
    assert hashlib.sha256((ROOT / 'electronic.cases.json').read_bytes()).hexdigest() == DIGEST
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert DIGEST in readme
    assert '72c749d7fffaf13f2f92d559674bd888e203084e' in readme


def compare(actual, expected):
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        assert actual == expected
    elif isinstance(expected, (int, float)):
        t = VECTORS['arithmetic_tolerance']
        assert actual == pytest.approx(expected, abs=t['abs'], rel=t['rel'])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            compare(a, e)
    else:
        assert set(expected).issubset(actual)
        for k in expected:
            compare(actual[k], expected[k])


@pytest.mark.parametrize('case', VECTORS['cases'], ids=lambda c: c['id'])
def test_electronic_vector(case):
    if case['kind'] == 'run':
        result = band_run_check(case['stdout'], case['bands_written'])
    else:
        bands = parse_bands(VECTORS['inputs'][case['bands']])
        if case['kind'] == 'gap':
            result = band_gap(bands, case['n_occupied'])
        elif case['kind'] == 'mass':
            result = directional_mass(bands, case['line'], case['policy'])
        else:
            sets = {k: parse_eigfat(VECTORS['inputs'][v]) for k, v in case['eigfat'].items()}
            result = fat_partition(bands, sets, case['policy'])
    compare(result, case['expect'])


def test_invalid_numeric_and_truncated_streams_rejected():
    with pytest.raises(ValueError):
        parse_bands(VECTORS['inputs']['mass.bands'][:-500])
    with pytest.raises(ValueError):
        parse_bands('nan\n0 1\n1 1 1\n0 0 0 3')
    with pytest.raises(ValueError):
        parse_eigfat(VECTORS['inputs']['fatsi.s.EIGFAT'][:-100])
