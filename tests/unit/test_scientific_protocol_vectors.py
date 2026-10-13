"""Accepted U-Q17/U-Q18 fixtures; hashes guard immutable upstream inputs."""
import hashlib
import json
from pathlib import Path
import re
import pytest
from qraft.engines.siesta.effective_fdf import resolve_effective_fdf
from qraft.engines.siesta.preflight import scalar_value, unused_labels
from qraft.engines.siesta.pseudo_metadata import psml_info, xc_gate, stdout_xc_warnings, resolve_pseudo_file, manifest_check
from qraft.siesta_validation import SiestaContextualValidator

FIXTURES=Path(__file__).parents[1]/'fixtures/scientific_protocols'
PF=json.loads((FIXTURES/'preflight.cases.json').read_text())
PS=json.loads((FIXTURES/'pseudos.cases.json').read_text())

def test_fixture_hashes():
    readme=(FIXTURES/'README.md').read_text()
    for name,digest in json.loads((FIXTURES/'hashes.json').read_text()).items():
        assert hashlib.sha256((FIXTURES/name).read_bytes()).hexdigest()==digest
        assert digest in readme

def close(actual,expected,tolerance):
    if isinstance(expected,bool) or expected is None or isinstance(expected,str):assert actual==expected
    elif isinstance(expected,(int,float)):assert actual==pytest.approx(expected,rel=tolerance['rel'],abs=tolerance.get('abs_meV',0))
    elif isinstance(expected,list):
        assert len(actual)==len(expected)
        for a,e in zip(actual,expected):close(a,e,tolerance)
    else:
        assert set(actual)==set(expected)
        for k in expected:close(actual[k],expected[k],tolerance)

@pytest.mark.parametrize('case',PF['cases'],ids=lambda c:c['id'])
def test_preflight_vectors(case,tmp_path):
    for name,text in case['files'].items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    try:effective=resolve_effective_fdf(tmp_path/case['root'])
    except (ValueError,FileNotFoundError) as e:
        code='INCLUDE_NOT_FOUND' if isinstance(e,FileNotFoundError) else 'CYCLIC_INCLUDE' if 'cyclic' in str(e) else 'REDIRECT_LABEL_NOT_FOUND'
        actual={'error':code}
    else:
        if case['kind']=='unused':actual=unused_labels(effective,case['fdf_log'])
        elif case['kind']=='block':actual={'rows':[[float(x) for x in line.split()] for line in effective.block(case['label']).body_lines if line.strip()]}
        else:
            actual=None
            for occurrence in effective.occurrences.values():
                label=next((label for label in PF['registry'] if re.sub('[._-]','',label).lower()==re.sub('[._-]','',occurrence.label).lower()),None)
                if label and occurrence.scalar:
                    parsed=scalar_value(effective,label,PF['registry'][label],PF['units'])
                    if 'error' in parsed:actual=parsed;break
            if actual is None:
                parsed=scalar_value(effective,case['label'],PF['registry'][case['label']],PF['units'])
                actual={'MeshCutoff_Ry':PF['registry'][case['label']]['default'],'default':True} if parsed.get('source')=='DEFAULT' else {'MeshCutoff_Ry':parsed['value'],'default':False}
    close(actual,case['expect'],PF['arithmetic_tolerance'])
    report=SiestaContextualValidator().validate_path(tmp_path/case['root'])
    if isinstance(actual,dict) and 'error' in actual:
        assert any(f.code==actual['error'] and f.status.value=='FAIL' for f in report.findings)

@pytest.mark.parametrize('case',PS['cases'],ids=lambda c:c['id'])
def test_pseudo_vectors(case):
    funcs={'psml':lambda:psml_info(case['psml']),'xc':lambda:xc_gate(case['run'],case['pseudos']),
           'stdout':lambda:stdout_xc_warnings(case['stdout']),'file':lambda:resolve_pseudo_file(case['label'],case['files']),
           'manifest':lambda:manifest_check(case['entries'])}
    close(funcs[case['kind']](),case['expect'],PS['arithmetic_tolerance'])