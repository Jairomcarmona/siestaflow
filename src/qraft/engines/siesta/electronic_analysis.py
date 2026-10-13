"""WF-ELECTRONIC B-0 through B-4, preserving native energy references."""
from math import isfinite, sqrt
from decimal import Decimal
import re
from ...scientific_policies import scientific_policy_document

BOHR_ANG = 0.529177210903
HBAR2_ME = 27.211386245988 * BOHR_ANG ** 2
POLICY = scientific_policy_document('qraft.electronic.policy@1')


def band_run_check(stdout, bands_written):
    if 'pi/a option should only be used for orthorhombic cells' in stdout:
        return {'status': 'FAIL', 'code': 'BAND_SCALE_REJECTED'}
    if not bands_written:
        return {'status': 'FAIL', 'code': 'BANDS_NOT_WRITTEN'}
    return {'status': 'PASS'}


def _numbers(tokens):
    values = [float(t.replace('D', 'E').replace('d', 'e')) for t in tokens]
    if not all(isfinite(v) for v in values):
        raise ValueError('Nonfinite electronic data')
    return values


def parse_bands(text):
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith(('#', '!', ';'))]
    header = next((i for i, l in enumerate(lines[:4]) if re.fullmatch(r'\d+\s+\d+\s+\d+', l)), None)
    kind = {3: 'lines', 2: 'points'}.get(header)
    if kind is None or len(lines[0].split()) != 1:
        raise ValueError('Invalid bands header')
    nb, ns, nk = map(int, lines[header].split())
    if min(nb, ns, nk) <= 0 or ns not in (1, 2):
        raise ValueError('Invalid bands dimensions')
    kc = 1 if kind == 'lines' else 3
    tokens = ' '.join(lines[header+1:]).split()
    count = nk * (kc+nb*ns)
    if len(tokens) < count:
        raise ValueError('Truncated bands payload')
    values = _numbers(tokens[:count])
    if kind == 'points' and len(tokens) != count:
        raise ValueError('Unexpected bands points payload')
    if kind == 'lines':
        tail = tokens[count:]
        # Normative table extracts omit the optional path-label section.
        if tail and (not re.fullmatch(r'\d+', tail[0]) or len(tail) != 1+2*int(tail[0])):
            raise ValueError('Invalid bands labels')
    k, energies = [], []
    for i in range(nk):
        offset = i*(kc+nb*ns)
        k.append(values[offset:offset+kc])
        e = values[offset+kc:offset+kc+nb*ns]
        energies.append([e[s*nb:(s+1)*nb] for s in range(ns)])
    return dict(kind=kind, fermi_eV=_numbers(lines[0].split())[0], nbands=nb, nspin=ns, nk=nk, k=k, E=energies)


def band_gap(bands, n_occupied):
    if type(n_occupied) is not int or not 0 < n_occupied < bands['nbands']:
        raise ValueError('Occupied bands must be explicit and within the sample')
    vbm, cbm = {'eV': -float('inf')}, {'eV': float('inf')}
    for ik, spins in enumerate(bands['E']):
        for spin, e in enumerate(spins):
            if e[n_occupied-1] > vbm['eV']:
                vbm = dict(eV=e[n_occupied-1], k_index=ik, spin=spin)
            if e[n_occupied] < cbm['eV']:
                cbm = dict(eV=e[n_occupied], k_index=ik, spin=spin)
    scope = 'PATH' if bands['kind'] == 'lines' else 'POINTS'
    if cbm['eV'] <= vbm['eV']:
        return dict(status='NO_GAP', scope=scope, vbm=vbm, cbm=cbm)
    return dict(status='GAP', scope=scope, gap_eV=cbm['eV']-vbm['eV'], direct=vbm['k_index']==cbm['k_index'],
                vbm=vbm, cbm=cbm, fermi_in_gap=vbm['eV'] < bands['fermi_eV'] < cbm['eV'])


def _quadratic(ts, es):
    # Center energy to avoid cancellation; the fitted quadratic is unchanged.
    origin = es[0]
    powers = [sum(t**p for t in ts) for p in range(5)]
    matrix = [[powers[r+c] for c in range(3)]+[sum((e-origin)*t**r for t, e in zip(ts, es))] for r in range(3)]
    for c in range(3):
        pivot = max(range(c, 3), key=lambda r: abs(matrix[r][c]))
        matrix[c], matrix[pivot] = matrix[pivot], matrix[c]
        if matrix[c][c] == 0:
            raise ValueError('Singular mass fit')
        denominator = matrix[c][c]
        matrix[c] = [v/denominator for v in matrix[c]]
        for r in range(3):
            if r != c:
                factor = matrix[r][c]
                matrix[r] = [a-factor*b for a, b in zip(matrix[r], matrix[c])]
    return [matrix[0][3]+origin, matrix[1][3], matrix[2][3]]


def directional_mass(bands, line, policy):
    first, last, band = line['from'], line['to'], line['band']
    spin, carrier = line.get('spin', 0), line['carrier']
    if not (0 <= first < last < bands['nk'] and 1 <= band <= bands['nbands'] and 0 <= spin < bands['nspin']) or carrier not in ('electron', 'hole'):
        raise ValueError('Invalid mass line')
    idx = list(range(first, last+1))
    reasons, direction = [], None
    if bands['kind'] == 'points':
        points = [[x/BOHR_ANG for x in bands['k'][i]] for i in idx]
        delta = [b-a for a, b in zip(points[0], points[-1])]
        norm = sqrt(sum(x*x for x in delta))
        if norm == 0:
            raise ValueError('Zero length mass line')
        direction = [x/norm for x in delta]
        s = [sum((x-y)*d for x, y, d in zip(p, points[0], direction)) for p in points]
        off = max(sqrt(sum((x-y-t*d)**2 for x, y, d in zip(p, points[0], direction))) for p, t in zip(points, s))
        if off > policy['straightness_invA']:
            reasons.append('LINE_NOT_STRAIGHT')
    else:
        s = [(bands['k'][i][0]-bands['k'][first][0])/BOHR_ANG for i in idx]
    e = [bands['E'][i][spin][band-1] for i in idx]
    j = (min if carrier == 'electron' else max)(range(len(e)), key=lambda i: e[i])
    win = [i for i, x in enumerate(s) if abs(x-s[j]) <= policy['fit_halfwidth_invA']+1e-12]
    if min(sum(s[i] < s[j] for i in win), sum(s[i] > s[j] for i in win)) < policy['min_points_per_side']:
        reasons.append('EXTREMUM_AT_LINE_END')
    near = [x for b, x in enumerate(bands['E'][idx[j]][spin]) if b != band-1 and abs(x-e[j])*1000 <= policy['degeneracy_meV']]
    if near:
        reasons.append('DEGENERATE_EXTREMUM')
    ts, es = [s[i]-s[j] for i in win], [e[i] for i in win]
    c = _quadratic(ts, es)
    curvature = 2*c[2]
    mass = (1 if carrier == 'electron' else -1)*HBAR2_ME/curvature if curvature else float('inf')
    if not mass > 0:
        reasons.append('CURVATURE_SIGN')
    rms = sqrt(sum((c[0]+c[1]*t+c[2]*t*t-energy)**2 for t, energy in zip(ts, es))/len(ts))
    return dict(status='NOT_ESTABLISHED' if reasons else 'ESTABLISHED', reasons=reasons,
                mass_me=None if reasons else mass, extremum_k_index=idx[j], extremum_eV=e[j],
                degenerate_bands=len(near), extremum_offset_invA=-c[1]/curvature if curvature else None,
                direction=direction, n_points=len(win), curvature_eV_A2=curvature, rms_meV=rms*1000)


def parse_eigfat(text):
    lines = text.splitlines()
    match = re.search(r'min_band, max_band:\s*(\d+)\s+(\d+)', lines[0] if lines else '')
    numeric = [l.strip() for l in lines if l.strip() and not l.lstrip().startswith('#')]
    if not numeric or not re.fullmatch(r'\d+\s+\d+\s+\d+', numeric[0]):
        raise ValueError('Invalid EIGFAT header')
    nb, ns, nk = map(int, numeric[0].split())
    values = _numbers(' '.join(numeric[1:]).split())
    if min(nb, ns, nk) <= 0 or ns not in (1, 2) or len(values) != nk*(4+2*nb*ns):
        raise ValueError('Invalid EIGFAT payload')
    k, energies, weights = [], [], []
    for i in range(nk):
        offset = i*(4+2*nb*ns)
        if values[offset] != i+1:
            raise ValueError('Invalid EIGFAT k order')
        k.append(values[offset+1:offset+4])
        pairs = values[offset+4:offset+4+2*nb*ns]
        energies.append(pairs[::2]); weights.append(pairs[1::2])
    return dict(min_band=int(match[1]) if match else 1, nbands=nb, nspin=ns, nk=nk, k=k, E=energies, W=weights)


def fat_partition(bands, sets, policy):
    names = sorted(sets)
    if not names:
        raise ValueError('Fat partition must be explicit')
    first = sets[names[0]]
    reasons = []
    if any(any(sets[n][f] != first[f] for f in ('nk', 'nbands', 'nspin', 'min_band')) for n in names) or first['nk'] != bands['nk'] or first['nspin'] != bands['nspin'] or first['min_band']-1+first['nbands'] > bands['nbands']:
        reasons.append('FAT_BANDS_MISMATCH')
    max_energy, max_sum, min_weight = 0., 0., float('inf')
    if not reasons:
        for q in range(first['nk']):
            for b in range(first['nbands']*first['nspin']):
                ref = bands['E'][q][b//first['nbands']][first['min_band']-1+b%first['nbands']]
                total = 0.
                for name in names:
                    max_energy = max(max_energy, abs(sets[name]['E'][q][b]-ref))
                    total += sets[name]['W'][q][b]
                    min_weight = min(min_weight, sets[name]['W'][q][b])
                max_sum = max(max_sum, abs(total-1))
        if max_energy > policy['energy_match_eV']:
            reasons.append('FAT_BANDS_MISMATCH')
        if max_sum > policy['weight_rounding']*len(names):
            reasons.append('PARTITION_INCOMPLETE')
    return dict(status='FAIL' if reasons else 'PASS', reasons=reasons, sets=names,
                max_energy_diff_eV=max_energy, max_sum_error=max_sum, min_weight=min_weight)


def fat_groups(bands, sets, policy):
    """Basis-invariant weights for maximal energy chains at each k and spin.

    Band identities are retained after energy sorting. A partial projection
    range must contain entire groups: otherwise there is no invariant weight
    for that range and presentation is refused.
    """
    partition = fat_partition(bands, sets, policy)
    if partition['status'] != 'PASS':
        raise ValueError('Invalid fat partition: '+str(partition['reasons']))
    first = sets[partition['sets'][0]]
    low, high = first['min_band']-1, first['min_band']-1+first['nbands']
    result = []
    for k, spins in enumerate(bands['E']):
        for spin, energies in enumerate(spins):
            ordered = sorted(range(len(energies)), key=lambda i: (energies[i], i))
            groups = []
            for band in ordered:
                if not groups or (Decimal(str(energies[band]))-Decimal(str(energies[groups[-1][-1]])))*1000 > Decimal(str(policy['degeneracy_meV'])):
                    groups.append([])
                groups[-1].append(band)
            for group in groups:
                selected = [band for band in group if low <= band < high]
                if not selected:
                    continue
                if len(selected) != len(group):
                    raise ValueError('Fat range cuts a degenerate group')
                result.append(dict(k_index=k, spin=spin, bands=[b+1 for b in group], size=len(group),
                    weights={name: sum(sets[name]['W'][k][spin*first['nbands']+b-low] for b in group)
                             for name in partition['sets']}))
    return result
