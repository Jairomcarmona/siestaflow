"""Exercise accepted checks through production validators and staging."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from qraft.cli import main
from qraft.engines.siesta.adapter import SiestaEngineAdapter
from qraft.engines.siesta.output_parser import SiestaOutputParser
from qraft.engines.siesta.pseudopotentials import (
    PseudopotentialEntry, PseudopotentialManifest, PseudopotentialStager,
    PseudopotentialVerifier,
)
from qraft.siesta_validation import SiestaContextualValidator
from qraft.workflow_preflight import WorkflowPreflightValidator
from tests.integration.test_validation_preflight_cli import _write_workflow
from tests.validation_fixture import BASE_FDF

FIXTURES = Path(__file__).parents[1] / 'fixtures/scientific_protocols'
PS = json.loads((FIXTURES / 'pseudos.cases.json').read_text())


def entry(path, species=None):
    return PseudopotentialEntry(
        species=species or path.stem, filename=path.name, format=path.suffix[1:],
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source='fixture',
        xc_family=None, relativity=None, location_status='CONFIGURED', path=str(path),
    )


def test_cli_and_workflow_resolve_includes_and_first_occurrence(tmp_path, capsys):
    text = BASE_FDF.replace('Mesh.Cutoff 350 Ry', '%include cutoff.fdf\nMeshCutoff 10 Ang')
    definition, fdf = _write_workflow(tmp_path, text)
    (fdf.parent / 'cutoff.fdf').write_text('MeshCutoff 350 Ry\n')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    report = WorkflowPreflightValidator().validate(definition)
    assert report.status.value == 'PASS'
    assert main(['input', 'validate', str(fdf), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'PASS'
    assert all(p.read_bytes() == data for p, data in before.items())
    (fdf.parent / 'cutoff.fdf').write_text('MeshCutoff 10 Ang\n')
    report = WorkflowPreflightValidator().validate(definition)
    assert any(f.code == 'UNIT_DIMENSION_MISMATCH' and f.status.value == 'FAIL' for f in report.findings)


def test_diagnostics_in_included_document_are_retained(tmp_path):
    path = tmp_path / 'root.fdf'
    path.write_text(BASE_FDF + '\n%include bad.fdf\n')
    (tmp_path / 'bad.fdf').write_text('%endblock bogus\n')
    report = SiestaContextualValidator().validate_path(path)
    assert report.status.value == 'FAIL'


def test_effective_xc_reaches_manifest_verifier(tmp_path):
    header = next(c['psml'] for c in PS['cases'] if c['kind'] == 'psml' and c['expect']['libxc_ids'] == [101, 130])
    manifests = []
    for label in ('C', 'O'):
        path = tmp_path / (label + '.psml')
        path.write_text(header)
        manifests.append(entry(path))
    manifest = PseudopotentialManifest(tuple(manifests))
    fdf = tmp_path / 'root.fdf'
    fdf.write_text(BASE_FDF + '\n%include xc.fdf\n')
    xc = tmp_path / 'xc.fdf'
    xc.write_text('XC.functional GGA\nXC.authors PBE\n')
    validator = SiestaContextualValidator()
    report = validator.validate_path(fdf, pseudopotential_manifest=manifest, require_pseudos=True)
    assert report.status.value == 'PASS'
    xc.write_text('XC.functional LDA\nXC.authors CA\n')
    report = validator.validate_path(fdf, pseudopotential_manifest=manifest, require_pseudos=True)
    assert report.status.value == 'FAIL'
    assert any('PSEUDO_XC_MISMATCH' in str(f) for f in report.findings)
    xc.write_text('XC.functional GGA\nXC.authors unknown\n')
    report = validator.validate_path(fdf, pseudopotential_manifest=manifest)
    assert report.status.value == 'FAIL'
    assert any('XC_UNKNOWN' in str(f) for f in report.findings)
    xc.write_text('XC.functional GGA\n')
    report = validator.validate_path(fdf, pseudopotential_manifest=manifest)
    assert report.status.value == 'BLOCKED'


@pytest.mark.parametrize('case', [c for c in PS['cases'] if c['kind'] == 'stdout'], ids=lambda c: c['id'])
def test_post_run_xc_warning_is_fail_even_on_normal_completion(case):
    text = 'Siesta Version : 5.4.2\nSCF converged\n' + case['stdout'] + '\nJob completed\n'
    parsed = SiestaOutputParser().parse(text.splitlines())
    gate = SiestaOutputParser().gate(parsed)
    validation = SiestaEngineAdapter().classify_result(parsed)
    assert gate.status.value == ('FAIL' if case['expect'] else 'PASS')
    assert validation.status == gate.status.value
    if case['expect']:
        assert gate.reason == 'PSEUDO_XC_MISMATCH'


def test_vps_staging_and_hash_and_ambiguity(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    vps = source / 'Si.vps'
    vps.write_bytes(b'fixture vps\n')
    manifest = PseudopotentialManifest((entry(vps),))
    destination = tmp_path / 'run'
    result = PseudopotentialStager().stage(manifest, source, destination, policy='copy')
    assert result.status.value == 'PASS'
    assert hashlib.sha256((destination / 'Si.vps').read_bytes()).hexdigest() == manifest.entries[0].sha256
    (destination / 'Si.psf').write_text('second format')
    staged = PseudopotentialManifest((entry(destination / 'Si.vps'),))
    audit = PseudopotentialVerifier().verify(staged, ['Si'])
    assert audit.status.value == 'FAIL'
    assert 'PSEUDO_FILE_AMBIGUOUS:Si' in audit.findings
    (source / 'Si.psml').write_text('<psml/>')
    assert PseudopotentialVerifier().verify(manifest, ['Si']).status.value == 'FAIL'


def test_case_sensitive_filename_is_not_a_prefix_match(tmp_path):
    pseudo = tmp_path / 'Si_old.psf'
    pseudo.write_text('fixture')
    manifest = PseudopotentialManifest((entry(pseudo, 'Si'),))
    result = PseudopotentialVerifier().verify(manifest, ['Si'])
    assert result.status.value == 'FAIL'
    assert 'SPECIES_FILENAME_MISMATCH:Si:Si_old.psf' in result.findings


def test_post_run_discovery_persists_native_unused_label_finding(tmp_path):
    case = next(c for c in json.loads((FIXTURES / 'preflight.cases.json').read_text())['cases'] if c['kind'] == 'unused')
    for name, text in case['files'].items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    log = tmp_path / 'fdf.fixture.log'
    log.write_text(case['fdf_log'])
    primary = tmp_path / case['root']
    before = primary.read_bytes()
    found = SiestaEngineAdapter().discover_artifacts(tmp_path, task_id='fixture', attempt_id='attempt-0001',
        settings={'primary_input': 'fdf'}, inputs={'fdf': primary}, bindings={})
    report_path = next(Path(a.path) for a in found if Path(a.path).name == 'input-validation-report.json')
    from qraft.contracts import ContractEnvelope, VALIDATION_REPORT
    envelope = ContractEnvelope.from_dict(json.loads(report_path.read_text()), required_contract=VALIDATION_REPORT)
    findings = [f for f in envelope.payload['findings'] if f['code'] == 'INPUT_LABEL_UNUSED']
    assert [f['message'].split()[-1] for f in findings] == case['expect']
    assert all(f['status'] == 'REVIEW' for f in findings)
    assert envelope.payload['metadata']['fdf_logs_sha256'][log.name] == hashlib.sha256(log.read_bytes()).hexdigest()
    assert primary.read_bytes() == before


def test_packaged_worker_post_run_does_not_depend_on_checkout(tmp_path):
    from qraft.controller_package import ControllerPackageBuilder
    from tests.m4.test_controller_package import source_campaign, resolution_lock
    from zipfile import ZipFile
    source = tmp_path / 'source'
    source.mkdir()
    campaign = source_campaign(source)
    lock = resolution_lock(source, qos='normal')
    result = ControllerPackageBuilder().build(campaign, tmp_path / 'package', provenance_files={'run.lock.json': lock})
    extracted = tmp_path / 'extracted'
    with ZipFile(result.zip_path) as archive:
        archive.extractall(extracted)
    runtime = next(extracted.rglob('runtime/qraft/engines/siesta/adapter.py')).parents[3]
    script = tmp_path / 'post_run.py'
    script.write_text('''import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from qraft.engines.siesta.adapter import SiestaEngineAdapter
from qraft.contracts import ContractEnvelope, VALIDATION_REPORT
workspace = pathlib.Path(sys.argv[2])
workspace.mkdir()
(workspace / "input.fdf").write_text("SystemLabel fixture\\nMeshCutof 300 Ry\\n")
(workspace / "fdf.fixture.log").write_text("SystemLabel fixture\\nMeshCutoff 300 Ry\\n")
found = SiestaEngineAdapter().discover_artifacts(workspace, task_id="fixture", attempt_id="attempt-0001",
    inputs={"fdf": workspace / "input.fdf"}, bindings={}, settings={"primary_input": "fdf"})
report = ContractEnvelope.from_dict(json.loads((workspace / "input-validation-report.json").read_text()), required_contract=VALIDATION_REPORT)
assert any(f["code"] == "INPUT_LABEL_UNUSED" and f["status"] == "REVIEW" for f in report.payload["findings"])
assert any(a.artifact_type == VALIDATION_REPORT.name for a in found)
assert str(pathlib.Path(sys.argv[1]).resolve()) in str(pathlib.Path(sys.modules["qraft"].__file__).resolve())
''')
    execution = subprocess.run([sys.executable, '-I', str(script), str(runtime), str(tmp_path / 'work')],
        cwd=tmp_path, capture_output=True, text=True)
    assert execution.returncode == 0, execution.stderr
