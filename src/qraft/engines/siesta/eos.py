"""WF-EOS v1 geometry, final-energy evidence and BM3 evaluation.

Pure postprocessing: no execution ownership and no inferred numerical policy.
"""
from __future__ import annotations

import math
import re

EV_A3_TO_GPA = 160.21766208


def determinant(cell):
    a, b, c = cell
    return a[0]*(b[1]*c[2]-b[2]*c[1]) - a[1]*(b[0]*c[2]-b[2]*c[0]) + a[2]*(b[0]*c[1]-b[1]*c[0])


def volume(cell):
    return abs(determinant(cell))


def fractional(cell, cart):
    # Row-vector convention: r = f A, so solve A^T f^T = r^T.
    transpose = [[cell[j][i] for j in range(3)] for i in range(3)]
    return [_solve(transpose, row) for row in cart]


def deform(reference, factor):
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError('volume factor must be finite and positive')
    scale = factor ** (1/3)
    return {'cell': [[v*scale for v in row] for row in reference['cell']],
            'atoms': [{**atom, 'cart': [v*scale for v in atom['cart']]} for atom in reference['atoms']]}


def check_deformation(reference, candidate, factor, tolerance):
    scale = factor ** (1/3)
    if any(abs(candidate['cell'][i][j]-scale*reference['cell'][i][j]) > tolerance['cell_A'] for i in range(3) for j in range(3)):
        return 'CELL_NOT_SCALED'
    if len(candidate['atoms']) != len(reference['atoms']):
        return 'ATOM_MAP_MISMATCH'
    initial = fractional(reference['cell'], [a['cart'] for a in reference['atoms']])
    final = fractional(candidate['cell'], [a['cart'] for a in candidate['atoms']])
    for index, (a, b) in enumerate(zip(reference['atoms'], candidate['atoms'])):
        if a['id'] != b['id'] or a['species'] != b['species']:
            return 'ATOM_MAP_MISMATCH'
        if any(abs(initial[index][j]-final[index][j]) > tolerance['fractional'] for j in range(3)):
            return 'FRACTIONAL_NOT_PRESERVED'
    return None


def final_energy(text, quantity):
    patterns = {'free_energy': r'^siesta: FreeEng =\s*(\S+)\s*$',
                'total_energy': r'^siesta:\s+Total =\s*(\S+)\s*$'}
    if quantity not in patterns:
        return {'error': 'ENERGY_QUANTITY_UNKNOWN'}
    lines = text.splitlines()
    if not any('SCF cycle converged' in line for line in lines) or not any(line.strip() == 'Job completed' for line in lines):
        return {'error': 'SCF_NOT_PROVEN'}
    values = [m.group(1) for line in lines if (m := re.match(patterns[quantity], line))]
    try:
        value = float(values[-1])
    except (ValueError, IndexError):
        return {'error': 'ENERGY_MISSING'}
    return {'value': value} if math.isfinite(value) else {'error': 'ENERGY_MISSING'}


def admissibility(table, policy):
    reasons = []
    points = table['points']
    if table['quantity'] != policy['energy_quantity']:
        reasons.append('ENERGY_QUANTITY_MISMATCH')
    if len(points) < policy['min_points']:
        reasons.append('TOO_FEW_POINTS')
    if any(p['kgrid']['kind'] != 'MonkhorstPack' for p in points):
        reasons.append('KGRID_NOT_FIXED')
    elif points and any(p['kgrid']['block'] != points[0]['kgrid']['block'] for p in points):
        reasons.append('KGRID_INCONSISTENT')
    if points and any(p['mesh'] != points[0]['mesh'] for p in points):
        reasons.append('MESH_INCONSISTENT')
    if any(p['relaxation_mode'] != policy['relaxation_mode'] for p in points):
        reasons.append('RELAXATION_MODE_MISMATCH')
    return reasons


def _solve(matrix, rhs):
    rows = [list(row) + [value] for row, value in zip(matrix, rhs)]
    n = len(rhs)
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(rows[i][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        if rows[col][col] == 0:
            raise ValueError('singular least-squares system')
        for row in range(n):
            if row == col:
                continue
            factor = rows[row][col] / rows[col][col]
            for j in range(col, n+1):
                rows[row][j] -= factor*rows[col][j]
    return [row[n]/row[i] for i, row in enumerate(rows)]


def fit_bm3(volumes, energies):
    x = [v ** (-2/3) for v in volumes]
    n = len(x)
    mean = math.fsum(x)/n
    std = math.sqrt(math.fsum((v-mean)**2 for v in x)/n)
    if std == 0:
        return None
    t = [(v-mean)/std for v in x]
    # Centering energies improves arithmetic without changing the fitted cubic.
    offset = math.fsum(energies)/n
    matrix = [[math.fsum(v**(i+j) for v in t) for j in range(4)] for i in range(4)]
    rhs = [math.fsum(v**i*(e-offset) for v, e in zip(t, energies)) for i in range(4)]
    try:
        c = _solve(matrix, rhs)
    except ValueError:
        return None
    c[0] += offset
    polynomial = lambda v: c[0]+c[1]*v+c[2]*v**2+c[3]*v**3
    second = lambda v: 2*c[2]+6*c[3]*v
    discriminant = (2*c[2])**2-12*c[3]*c[1]
    if discriminant < 0:
        return None
    if abs(c[3]) < 1e-300:
        if c[2] == 0:
            return None
        roots = [-c[1]/(2*c[2])]
    else:
        roots = [(-2*c[2]+math.sqrt(discriminant))/(6*c[3]), (-2*c[2]-math.sqrt(discriminant))/(6*c[3])]
    root = next((r for r in roots if second(r) > 0 and mean+std*r > 0), None)
    if root is None:
        return None
    v0 = (mean+std*root)**-1.5
    px2, px3 = second(root)/std**2, 6*c[3]/std**3
    xv1, xv2 = -2/3*v0**(-5/3), 10/9*v0**(-8/3)
    e2 = px2*xv1**2
    e3 = px3*xv1**3+3*px2*xv1*xv2
    rms = math.sqrt(math.fsum((e-polynomial(tt))**2 for e, tt in zip(energies, t))/n)
    return {'E0_eV': polynomial(root), 'V0_A3': v0, 'B0_GPa': v0*e2*EV_A3_TO_GPA,
            'B0_prime': -1-v0*e3/e2, 'rms_meV': rms*1000}


def evaluate(table, policy):
    reasons = admissibility(table, policy)
    if reasons:
        return {'status': 'REJECTED', 'reasons': reasons}
    volumes, energies = [p['volume_A3'] for p in table['points']], [p['energy_eV'] for p in table['points']]
    fit = fit_bm3(volumes, energies)
    if fit is None:
        return {'status': 'NOT_ESTABLISHED', 'reasons': ['NO_MINIMUM']}
    reasons = []
    if fit['V0_A3'] <= min(volumes) or fit['V0_A3'] >= max(volumes):
        reasons.append('MINIMUM_OUTSIDE_RANGE')
    elif min(sum(v < fit['V0_A3'] for v in volumes), sum(v > fit['V0_A3'] for v in volumes)) < policy['min_points_each_side']:
        reasons.append('MINIMUM_NOT_BRACKETED')
    if fit['rms_meV']/table['n_atoms'] > policy['max_rms_meV_per_atom']:
        reasons.append('RESIDUAL_TOO_LARGE')
    order = sorted(range(len(volumes)), key=volumes.__getitem__)
    dv = db = 0
    for omitted in (order[0], order[-1]):
        indices = [i for i in order if i != omitted]
        alternative = fit_bm3([volumes[i] for i in indices], [energies[i] for i in indices])
        if alternative is None:
            reasons.append('SENSITIVITY_UNDEFINED')
            continue
        dv = max(dv, abs(alternative['V0_A3']-fit['V0_A3'])/fit['V0_A3'])
        db = max(db, abs(alternative['B0_GPa']-fit['B0_GPa'])/fit['B0_GPa'])
    if dv > policy['max_rel_dV0']:
        reasons.append('V0_SENSITIVE')
    if db > policy['max_rel_dB0']:
        reasons.append('B0_SENSITIVE')
    return {'status': 'NOT_ESTABLISHED' if reasons else 'ESTABLISHED', 'reasons': list(dict.fromkeys(reasons)),
            'fit': fit, 'sensitivity': {'max_rel_dV0': dv, 'max_rel_dB0': db},
            'per_atom': {'V0_A3': fit['V0_A3']/table['n_atoms'], 'E0_eV': fit['E0_eV']/table['n_atoms']}}
