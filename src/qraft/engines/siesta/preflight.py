"""SIESTA 5.4.2 scalar syntax and observed FDF usage (U-Q17).

Resolution belongs to effective_fdf; this module never executes an include or
assumes that an unknown keyword is an error in the SIESTA language.
"""
from __future__ import annotations

import re

UNITS = {
    'energy': {'ry': 1.0, 'ev': 0.07349864435, 'hartree': 2.0, 'ha': 2.0, 'mry': .001, 'mev': 7.349864435e-05},
    'length': {'ang': 1.0, 'bohr': .529177, 'nm': 10.0},
}
_INT = re.compile(r'^[+-]?\d+$')
_REAL = re.compile(r'^[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$')


def scalar_value(effective, label, entry, units=UNITS):
    node = effective.scalar(label)
    if node is None:
        return {'source': 'DEFAULT'}
    tokens = (node.value + (' '+node.unit if node.unit else '')).split()
    value = tokens[0] if tokens else ''
    kind = entry['type']
    if kind == 'integer':
        return {'value': int(value)} if _INT.fullmatch(value) else {'error': 'INTEGER_EXPECTED'}
    if kind in ('real', 'physical'):
        if not _REAL.fullmatch(value):
            return {'error': 'REAL_EXPECTED'}
        number = float(re.sub('[dD]', 'e', value))
        if kind == 'real':
            return {'value': number}
        if len(tokens) < 2:
            return {'error': 'UNIT_MISSING'}
        unit = tokens[1].casefold()
        for dimension, table in units.items():
            if unit in table:
                if dimension != entry['dimension']:
                    return {'error': 'UNIT_DIMENSION_MISMATCH'}
                return {'value': number*table[unit], 'unit': entry['canonical_unit']}
        return {'error': 'UNIT_UNKNOWN'}
    return {'value': ' '.join(tokens)}


def unused_labels(effective, fdf_log):
    from .models import normalize_label
    queried = set()
    for line in fdf_log.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0].startswith('#:') and len(tokens) > 1:
            queried.add(normalize_label(tokens[1]))
        elif tokens[0].startswith('#'):
            continue
        elif tokens[0].casefold() == '%block' and len(tokens) > 1:
            queried.add(normalize_label(tokens[1]))
        elif not tokens[0].startswith('%'):
            queried.add(normalize_label(tokens[0]))
    return [o.label for label, o in effective.occurrences.items() if label not in queried]


def _edit_distance(a, b):
    row = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(next_row[-1]+1, row[j]+1, row[j-1]+(x != y)))
        row = next_row
    return row[-1]


def keyword_suggestions(label, registry):
    from .models import normalize_label
    return [e.canonical_name for e in registry.entries
            if _edit_distance(normalize_label(label), normalize_label(e.canonical_name)) <= 2]
