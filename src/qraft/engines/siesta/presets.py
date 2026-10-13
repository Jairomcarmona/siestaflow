"""Accepted PRESETS v1 observations and gates, owned by QRAFT.

Coordinates are Cartesian Angstrom, radii Bohr, forces eV/Angstrom.
The caller supplies the intent and policy; this module never infers them.
"""
from __future__ import annotations

import itertools
import math
import re

BOHR_A = 0.529177210903
COULOMB_EV_A = 14.399645478
MADELUNG_SC = 2.8372974794806


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _sub(a, b):
    return [x-y for x, y in zip(a, b)]


def parse_run(text):
    lines = text.splitlines()

    def matches(pattern):
        return [m for line in lines if (m := re.search(pattern, line))]

    def scalar(pattern, numeric=False, last=False):
        found = matches(pattern)
        if not found:
            return None
        value = found[-1 if last else 0].group(1)
        return float(value) if numeric else value

    meshes = []
    for match in matches(r'^InitMesh: MESH =\s*(\d+) x\s*(\d+) x\s*(\d+)'):
        mesh = [int(v) for v in match.groups()]
        if not meshes or mesh != meshes[-1]:
            meshes.append(mesh)
    cuts = matches(r'^InitMesh: Mesh cutoff \(required, used\) =\s*(\S+)\s+(\S+) Ry')
    forces = []
    for index, line in enumerate(lines):
        if not re.match(r'^siesta: Atomic forces \(eV/Ang\):\s*$', line):
            continue
        total = maximum = constrained = None
        for row in lines[index+1:]:
            if re.match(r'^siesta: Atomic forces', row):
                break
            row = re.sub(r'^siesta:', '', row)
            match = re.match(r'^\s+Tot\s+(\S+)\s+(\S+)\s+(\S+)\s*$', row)
            if total is None and match:
                total = [float(v) for v in match.groups()]
            match = re.match(r'^\s+Max\s+(\S+)\s*$', row)
            if maximum is None and match:
                maximum = float(match.group(1))
            match = re.match(r'^\s+Max\s+(\S+)\s+constrained\s*$', row)
            if constrained is None and match:
                constrained = float(match.group(1))
        if total is not None and maximum is not None:
            forces.append({'tot': total, 'max': maximum, 'max_constrained': constrained})
    madelung = scalar(r'^madelung: Charged system with (SC|FCC|BCC) cell')
    if matches(r'^madelung: WARNING: Energy correction terms can not be applied'):
        madelung = 'NOT_APPLIED'
    return {
        'completed': bool(matches(r'^Job completed')),
        'scf_converged': len(matches(r'^SCF cycle converged')),
        'gamma_only': bool(matches(r'^siesta: k-point is Gamma-only')),
        'folding': bool(matches(r'^Folding of H and S implicitly performed')),
        'electrons': scalar(r'^Total number of electrons:\s+(\S+)', True),
        'spin': scalar(r'^redata: Spin configuration\s+=\s+(\S+)'),
        'net_charge': scalar(r'^redata: Net charge of the system\s+=\s+(\S+) \|e\|', True),
        'madelung': madelung,
        'emadel_eV': scalar(r'^siesta: Emadel\s+=\s+(\S+)', True, True),
        'meshes': meshes,
        'mesh_cutoff_Ry': {'required': float(cuts[-1].group(1)), 'used_min': min(float(m.group(2)) for m in cuts)} if cuts else None,
        'forces': forces,
        'relaxed': True if matches(r'^outcoor: Relaxed') else False if matches(r'^outcoor: Final \(unrelaxed\)') else None,
    }


def madelung_sc(charge, box_A):
    return COULOMB_EV_A * charge**2 * MADELUNG_SC / (2 * box_A)


def image_interaction(geometry, radii):
    atoms = geometry['atoms']
    if any(a['species'] not in radii for a in atoms):
        return {'status': 'NOT_CHECKED'}
    cell = [[v / BOHR_A for v in row] for row in geometry['cell']]
    positions = [[v / BOHR_A for v in a['cart']] for a in atoms]
    volume = abs(_dot(cell[0], _cross(cell[1], cell[2])))
    heights = [volume / _norm(_cross(cell[(i+1)%3], cell[(i+2)%3])) for i in range(3)]
    orbital = [radii[a['species']]['orb'] for a in atoms]
    projector = [radii[a['species']]['kb'] for a in atoms]
    reach = 2*max(orbital) + 2*max(projector)
    extent = max(_norm(_sub(a, b)) for a in positions for b in positions)
    bounds = [math.ceil((reach+extent)/h) for h in heights]
    shifts = list(itertools.product(*(range(-n, n+1) for n in bounds)))

    def translated(position, shift):
        return [position[x] + sum(shift[d]*cell[d][x] for d in range(3)) for x in range(3)]

    # Projectors reaching the first atom are filtered once. This is exactly the
    # same finite lattice enumeration, avoiding its Cartesian square.
    nearby = []
    for i, position in enumerate(positions):
        nearby.append([(k, translated(p, shift)) for shift in shifts for k, p in enumerate(positions)
                       if _norm(_sub(position, translated(p, shift))) < orbital[i] + projector[k]])
    clearance = math.inf
    pair = None
    via_projector = False
    for shift in shifts:
        if shift == (0, 0, 0):
            continue
        for i, a in enumerate(positions):
            for j, b in enumerate(positions):
                target = translated(b, shift)
                distance = _norm(_sub(a, target)) - orbital[i] - orbital[j]
                if distance < clearance:
                    clearance, pair = distance, [i+1, j+1, list(shift)]
                if not via_projector:
                    via_projector = any(_norm(_sub(target, p)) < orbital[j] + projector[k] for k, p in nearby[i])
    return {'interacts': clearance < 0 or via_projector, 'min_clearance_bohr': clearance,
            'closest_pair': pair, 'via_projector': via_projector}


def _decision(rejected, review):
    return {'status': 'REJECTED' if rejected else 'REVIEW' if review else 'ACCEPTED', 'reasons': rejected + review}


def evaluate_molecule(run, intent):
    rejected = []
    if not run['completed'] or run['scf_converged'] < 1:
        rejected.append('SCF_NOT_PROVEN')
    if not run['gamma_only']:
        rejected.append('KGRID_NOT_GAMMA')
    if run['folding']:
        rejected.append('BASIS_OVERLAPS_IMAGES')
    if intent['net_charge'] != 0 and run['madelung'] in (None, 'NOT_APPLIED'):
        rejected.append('CHARGED_CELL_NO_MADELUNG')
    if run['electrons'] is not None and math.floor(run['electrons']+.5) % 2 and run['spin'] == 'none':
        rejected.append('ODD_ELECTRONS_UNPOLARIZED')
    result = _decision(rejected, [])
    result['net_force_eV_A'] = _norm(run['forces'][-1]['tot']) if run['forces'] else None
    return result


def evaluate_relaxation(run, intent):
    rejected, review = [], []
    if not run['completed'] or run['scf_converged'] < 1:
        rejected.append('SCF_NOT_PROVEN')
    if run['relaxed'] is not True:
        rejected.append('NOT_RELAXED')
    if intent['variable_cell']:
        if len(run['meshes']) > 1:
            rejected.append('MESH_CHANGED_DURING_RELAXATION')
        cutoff = run['mesh_cutoff_Ry']
        if cutoff is not None and cutoff['used_min'] < cutoff['required']:
            rejected.append('MESH_CUTOFF_BELOW_REQUEST')
    if run['forces'] and not intent.get('has_constraints', False) and _norm(run['forces'][-1]['tot']) >= intent['max_force_tol_eV_A']:
        review.append('NET_FORCE_ABOVE_TOLERANCE')
    return _decision(rejected, review)
