"""Byte-exact accepted PRESETS v1 vectors, evaluated by native QRAFT code."""
import hashlib
import json
from pathlib import Path

import pytest

from qraft.engines.siesta.presets import (
    parse_run, image_interaction, madelung_sc, evaluate_molecule, evaluate_relaxation,
)
from qraft.engines.siesta.molecular_vibrations import parse_fc, evaluate_vibrations

ROOT = Path(__file__).parents[1] / 'fixtures/scientific_protocols/presets'
VECTORS = json.loads((ROOT / 'presets.cases.json').read_text(encoding='utf-8'))
DIGEST = '8a3a0d74dce96caa04cbbf69499d6833f98a4b2fbdf29e7fd67c7f126523b69d'


def test_presets_fixture_hash():
    assert hashlib.sha256((ROOT / 'presets.cases.json').read_bytes()).hexdigest() == DIGEST
    assert DIGEST in (ROOT / 'README.md').read_text(encoding='utf-8')
    assert '72c749d7fffaf13f2f92d559674bd888e203084e' in (ROOT / 'README.md').read_text(encoding='utf-8')


def compare(actual, expected):
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        assert actual == expected
    elif isinstance(expected, (int, float)):
        tol = VECTORS['arithmetic_tolerance']
        assert actual == pytest.approx(expected, abs=tol['abs_meV'], rel=tol['rel'])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            compare(a, e)
    else:
        assert set(actual) == set(expected)
        for key in expected:
            compare(actual[key], expected[key])


@pytest.mark.parametrize('case', VECTORS['cases'], ids=lambda c: c['id'])
def test_presets_vector(case):
    kind = case['kind']
    if kind == 'image':
        actual = image_interaction(case['geometry'], case['radii'])
        # The vector measures interaction/clearance, not the oracle's optional
        # diagnostic closest_pair. Compare every normative expected field.
        actual = {key: actual[key] for key in case['expect']}
    else:
        run = parse_run(case['stdout'])
        if kind == 'parse':
            actual = run
        elif kind == 'madelung':
            actual = {'parsed_eV': run['emadel_eV'], 'formula_eV': madelung_sc(case['charge'], case['box_A'])}
        elif kind == 'molecule':
            actual = evaluate_molecule(run, case['intent'])
        elif kind == 'relaxation':
            actual = evaluate_relaxation(run, case['intent'])
        elif kind == 'vibrations':
            actual = evaluate_vibrations(run, parse_fc(case['fc']), case['cart'], case['masses'], case['policy'])
        else:
            raise AssertionError(kind)
    compare(actual, case['expect'])


def test_force_observation_reads_complete_atom_table_and_final_block():
    first = "siesta: Atomic forces (eV/Ang):\n" + "siesta: 1 0 0 0\n" * 12
    first += "siesta: Tot 0.1 0 0\nsiesta: Max 0.01\n"
    final = "siesta: Atomic forces (eV/Ang):\nsiesta: Tot 0 0 0\nsiesta: Max 0.002\nsiesta: Max 0.001 constrained\n"
    run = parse_run(first + final)
    assert run["forces"] == [
        {"tot": [0.1, 0.0, 0.0], "max": 0.01, "max_constrained": None},
        {"tot": [0.0, 0.0, 0.0], "max": 0.002, "max_constrained": 0.001},
    ]


def test_molecular_charge_is_observed_in_normative_success_case():
    case = next(c for c in VECTORS['cases'] if c['id'] == 'pre-mol-01')
    assert parse_run(case['stdout'])['net_charge'] == case['intent']['net_charge']
