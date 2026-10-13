"""PRESETS F-1..F-6: central force constants and Eckart projection.

Masses come from the declared intent (amu), never from a pseudopotential.
The numerical rank and conversion constants are those of the accepted oracle.
"""
from __future__ import annotations

import math
import re

from .presets import _cross, _dot, _norm, _decision

WAVENUMBER_PER_SQRT_EV_A2_AMU = 521.470898


def parse_fc(text):
    lines = [line for line in text.splitlines() if line.strip()]
    header = re.search(r'n_atoms, displacement \[Ang\]:\s+(\d+)\s+(\S+)', lines[0]) if lines else None
    if header is None:
        raise ValueError('FC_HEADER_MISSING')
    n = int(header.group(1))
    rows = [[float(v) for v in line.split()] for line in lines[1:]]
    if len(rows) != 6*n*n or any(len(row) != 3 for row in rows):
        raise ValueError('FC_SIZE_MISMATCH')
    matrix = [[0.0 for _ in range(3*n)] for _ in range(3*n)]
    for i in range(n):
        for direction in range(3):
            for sign in range(2):
                for j in range(n):
                    row = rows[((3*i+direction)*2+sign)*n+j]
                    for component in range(3):
                        matrix[3*i+direction][3*j+component] += row[component]/2
    asr = max(abs(sum(matrix[p][3*j+b] for j in range(n))) for p in range(3*n) for b in range(3))
    asymmetry = max(abs(matrix[p][q]-matrix[q][p]) for p in range(3*n) for q in range(3*n))
    return {'n_atoms': n, 'displacement_A': float(header.group(2)), 'K': matrix,
            'asr_violation_eV_A2': asr, 'asymmetry_eV_A2': asymmetry}


def symmetric_eigenvalues(matrix):
    """Cyclic Jacobi for a real symmetric matrix, with fixed oracle thresholds."""
    a = [row[:] for row in matrix]
    n = len(a)
    for _ in range(100):
        if sum(a[p][q]**2 for p in range(n) for q in range(p+1, n)) < 1e-30:
            break
        for p in range(n):
            for q in range(p+1, n):
                if abs(a[p][q]) < 1e-300:
                    continue
                theta = (a[q][q]-a[p][p])/(2*a[p][q])
                tangent = math.copysign(1.0, theta if theta else 1.0)/(abs(theta)+math.sqrt(theta*theta+1))
                c = 1/math.sqrt(1+tangent*tangent)
                s = tangent*c
                for k in range(n):
                    x, y = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c*x-s*y, s*x+c*y
                for k in range(n):
                    x, y = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c*x-s*y, s*x+c*y
    return sorted(a[i][i] for i in range(n))


def _add_orthonormal(basis, vector, tolerance):
    remaining = vector[:]
    for _ in range(2):
        for b in basis:
            dot = _dot(b, remaining)
            remaining = [v-dot*x for v, x in zip(remaining, b)]
    norm = _norm(remaining)
    if norm > tolerance:
        basis.append([v/norm for v in remaining])


def _cm1(eigenvalue):
    return math.copysign(math.sqrt(abs(eigenvalue)), eigenvalue)*WAVENUMBER_PER_SQRT_EV_A2_AMU


def harmonic_modes(fc, cart, masses):
    n, m = fc['n_atoms'], 3*fc['n_atoms']
    if len(cart) != n or len(masses) != n:
        raise ValueError('ATOM_MAP_MISMATCH')
    if any(not math.isfinite(mass) or mass <= 0 for mass in masses):
        raise ValueError('declared masses must be finite and positive')
    roots = [math.sqrt(masses[p//3]) for p in range(m)]
    k = fc['K']
    dynamical = [[(k[p][q]+k[q][p])/(2*roots[p]*roots[q]) for q in range(m)] for p in range(m)]
    raw = [_cm1(v) for v in symmetric_eigenvalues(dynamical)]
    total_mass = sum(masses)
    center = [sum(masses[i]*cart[i][axis] for i in range(n))/total_mass for axis in range(3)]
    relative = [[r[axis]-center[axis] for axis in range(3)] for r in cart]
    scale = math.sqrt(total_mass)*max(1, *(abs(v) for r in relative for v in r))
    basis = []
    for axis in range(3):
        _add_orthonormal(basis, [roots[p] if p%3 == axis else 0 for p in range(m)], 1e-8*scale)
    for axis in range(3):
        unit = [1 if a == axis else 0 for a in range(3)]
        rotation = [_cross(unit, r) for r in relative]
        _add_orthonormal(basis, [roots[p]*rotation[p//3][p%3] for p in range(m)], 1e-8*scale)
    rigid = len(basis)
    complement = basis[:]
    for p in range(m):
        if len(complement) == m:
            break
        _add_orthonormal(complement, [1 if q == p else 0 for q in range(m)], 1e-8)
    vibrational_basis = complement[rigid:]
    projected = [[sum(u[p]*sum(dynamical[p][q]*w[q] for q in range(m)) for p in range(m))
                  for w in vibrational_basis] for u in vibrational_basis]
    return {'rigid_modes': rigid, 'raw_cm1': raw,
            'raw_rigid_max_cm1': max(sorted(abs(v) for v in raw)[:rigid]),
            'vibrational_cm1': [_cm1(v) for v in symmetric_eigenvalues(projected)]}


def evaluate_vibrations(run, fc, cart, masses, policy):
    rejected, review = [], []
    if not run['completed']:
        rejected.append('SCF_NOT_PROVEN')
    mismatch = fc['n_atoms'] != len(cart) or len(masses) != len(cart)
    if mismatch:
        rejected.append('ATOM_MAP_MISMATCH')
    reference = run['forces'][0] if run['forces'] else None
    if reference is None or reference['max'] > policy['max_reference_force_eV_A']:
        rejected.append('GEOMETRY_NOT_RELAXED')
    if mismatch:
        return _decision(rejected, review)
    modes = harmonic_modes(fc, cart, masses)
    if any(v < -policy['imaginary_tol_cm1'] for v in modes['vibrational_cm1']):
        review.append('IMAGINARY_VIBRATION')
    return {**_decision(rejected, review), 'rigid_modes': modes['rigid_modes'],
            'raw_rigid_max_cm1': modes['raw_rigid_max_cm1'],
            'asr_violation_eV_A2': fc['asr_violation_eV_A2'], 'vibrational_cm1': modes['vibrational_cm1']}
