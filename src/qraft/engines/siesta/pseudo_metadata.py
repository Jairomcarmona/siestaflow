"""U-Q18: PSML header metadata and the fixed SIESTA 5.4.2 XC identities."""
from __future__ import annotations

import re
from xml.etree import ElementTree

LIBXC = {1: 'LDA_X', 9: 'LDA_C_PZ', 12: 'LDA_C_PW', 101: 'GGA_X_PBE',
         130: 'GGA_C_PBE', 116: 'GGA_X_PBE_SOL', 133: 'GGA_C_PBE_SOL'}
XC_AUTHORS = {'LDA': {'CA': [1, 9], 'PZ': [1, 9], 'PW92': [1, 12]},
              'GGA': {'PBE': [101, 130], 'PBESOL': [116, 133]}}


def psml_info(text):
    # Qualification fixtures contain the real header through exchange-correlation,
    # with radial tables omitted; parse these XML elements without inventing data.
    spec = re.search(r'<(?:pseudo-atom-spec|header)\b[^>]*>', text)
    if spec is None:
        return {'error': 'PSML_HEADER_MISSING'}
    tag = spec.group().rstrip('>').rstrip('/')+'/>'
    node = ElementTree.fromstring(tag)
    xc = re.search(r'<exchange-correlation>([\s\S]*?)</exchange-correlation>', text)
    funcs = ElementTree.fromstring(xc.group()).findall('.//functional') if xc else []
    rank = lambda f: 0 if 'exchange' in f.get('type', '').lower() else 1 if 'correlation' in f.get('type', '').lower() else 2
    ids = [int(f.attrib['id']) for f in sorted(funcs, key=rank)]
    return {'label': node.get('atomic-label'), 'z': float(node.attrib['atomic-number']),
            'z_valence': float(node.attrib['z-pseudo']), 'relativity': node.get('relativity'),
            'core_corrections': node.get('core-corrections') == 'yes',
            'libxc_ids': ids, 'xc': [LIBXC.get(i, f'LIBXC_{i}') for i in ids]}


def xc_gate(run, pseudos):
    ids = XC_AUTHORS.get(str(run['functional']).upper(), {}).get(str(run['authors']).upper())
    if ids is None:
        return {'status': 'FAIL', 'code': 'XC_UNKNOWN'}
    mismatched = sorted(label for label, p in pseudos.items() if p['libxc_ids'] != ids)
    return {'status': 'FAIL', 'code': 'PSEUDO_XC_MISMATCH', 'run_libxc_ids': ids,
            'mismatched': mismatched} if mismatched else {'status': 'PASS', 'run_libxc_ids': ids}


def stdout_xc_warnings(stdout):
    return [m.strip() for m in re.findall(r'xc_check: WARNING: Pseudopotential generated with (.+?) functional', stdout)]


def resolve_pseudo_file(label, files):
    found = [label+'.'+extension for extension in ('vps', 'psf', 'psml') if label+'.'+extension in files]
    return {'file': found[0], 'ambiguous': len(found) > 1} if found else {'error': 'PSEUDO_FILE_NOT_FOUND'}


def manifest_check(entries):
    findings = [f"SPECIES_FILENAME_MISMATCH:{e['species']}:{e['filename']}" for e in entries
                if re.sub(r'\.(psml|psf|vps)$', '', e['filename'], flags=re.I) != e['species']]
    return {'status': 'FAIL' if findings else 'PASS', 'findings': findings}
