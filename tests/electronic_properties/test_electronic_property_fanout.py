from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.electronic_properties import BandPathSpec, BandPathVertex, DosSpec, PdosSpec, parse_bands, parse_dos, parse_pdos, validate_property_neutral_parent
from qraft.protocols.electronic_properties import ElectronicPropertiesProtocol, ElectronicStateSource
from qraft.protocols.single_fdf import build_scientific_identity


BASE = """SystemName carbon
SystemLabel carbon
NumberOfAtoms 1
NumberOfSpecies 1
Mesh.Cutoff 100 Ry
PAO.EnergyShift 50 meV
LatticeConstant 1 Ang
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10 0 0
0 10 0
0 0 10
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
%endblock AtomicCoordinatesAndAtomicSpecies
%block kgrid.MonkhorstPack
1 0 0 0.0
0 1 0 0.0
0 0 1 0.0
%endblock kgrid.MonkhorstPack
MD.Steps 0
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _specs() -> tuple[BandPathSpec, DosSpec, PdosSpec]:
    grid = ((2, 0, 0, 0.0), (0, 2, 0, 0.0), (0, 0, 2, 0.0))
    bands = BandPathSpec("ReciprocalLatticeVectors", (
        BandPathVertex((0.0, 0.0, 0.0), 1, "G"),
        BandPathVertex((0.5, 0.0, 0.0), 8, "X"),
    ))
    return bands, DosSpec("EF", -2.0, 2.0, 0.1, 4, "eV", grid), PdosSpec("EF", -2.0, 2.0, 0.1, 4, "eV", grid)


def _source(root: Path, *, included: bool = False) -> ElectronicStateSource:
    final = root / "final.fdf"
    if included:
        (root / "included.fdf").write_text(BASE, encoding="utf-8")
        final.write_text("%include included.fdf\n", encoding="utf-8")
    else:
        final.write_text(BASE, encoding="utf-8")
    dm = root / "carbon.DM"; dm.write_bytes(b"verified-dm")
    (root / "C.psf").write_text("pseudo", encoding="utf-8")
    state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={
        "schema_version": "1.0", "artifact_id": "electronic-state", "artifact_type": "qraft.electronic-state", "authority": "PROVISIONAL", "engine": "siesta",
        "final_scf": {"input_fdf_sha256": _sha(final), "scientific_identity_sha256": build_scientific_identity(final).fingerprint, "system_label": "carbon", "density_matrix": {"filename": "carbon.DM", "sha256": _sha(dm)}},
    }).to_dict()
    state_path = root / "electronic-state.json"; state_path.write_text(json.dumps(state), encoding="utf-8")
    return ElectronicStateSource.load(state_path, final_fdf=final, density_matrix=dm)


def test_parent_gate_rendering_and_identity_locality(tmp_path: Path) -> None:
    source = _source(tmp_path); bands, dos, pdos = _specs()
    prepared = ElectronicPropertiesProtocol().prepare(source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "m7")
    assert {task.task_id for task in prepared.compiled.tasks} == {"bands", "dos", "pdos"}
    assert all(not task.dependencies for task in prepared.compiled.tasks)
    assert "DM.UseSaveDM true" in (prepared.source_root / "bands" / "input.fdf").read_text(encoding="utf-8")
    assert "%block BandLines\n  1 " in (prepared.source_root / "bands" / "input.fdf").read_text(encoding="utf-8")
    assert prepared.identities["bands"].fingerprint != prepared.identities["dos"].fingerprint
    changed_bands = BandPathSpec("ReciprocalLatticeVectors", (BandPathVertex((0, 0, 0), 1, "G"), BandPathVertex((0.25, 0, 0), 8, "Q")))
    again = ElectronicPropertiesProtocol().prepare(source, bands=changed_bands, dos=dos, pdos=pdos, runs_root=tmp_path / "m7-other")
    assert prepared.identities["bands"].fingerprint != again.identities["bands"].fingerprint
    assert prepared.identities["dos"].fingerprint == again.identities["dos"].fingerprint
    assert prepared.identities["pdos"].fingerprint == again.identities["pdos"].fingerprint


def test_parent_property_directives_fail_closed(tmp_path: Path) -> None:
    final = tmp_path / "bad.fdf"; final.write_text(BASE + "%block BandLines\n0 0 0 0 G\n%endblock BandLines\n", encoding="utf-8")
    with pytest.raises(ValueError, match="property directives"):
        validate_property_neutral_parent(final)


def test_parent_density_matrix_tampering_is_rejected_before_compilation(tmp_path: Path) -> None:
    source = _source(tmp_path); bands, dos, pdos = _specs()
    source.density_matrix.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="density-matrix SHA-256"):
        ElectronicPropertiesProtocol().prepare(source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "m7")


def test_m7_requires_integral_sampling_and_renders_ef_physically(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        BandPathVertex((0, 0, 0), 1.5, "G")
    grid = ((1, 0, 0, 0.0), (0, 1, 0, 0.0), (0, 0, 1, 0.0))
    with pytest.raises(ValueError, match="integer"):
        DosSpec("EF", -1, 1, 0.1, 4.7, "eV", grid)
    source = _source(tmp_path); bands, dos, pdos = _specs()
    absolute = DosSpec("ABSOLUTE", -2, 2, 0.1, 4, "eV", dos.pdos_kgrid)
    first = ElectronicPropertiesProtocol().prepare(source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "ef")
    second = ElectronicPropertiesProtocol().prepare(source, bands=bands, dos=absolute, pdos=pdos, runs_root=tmp_path / "absolute")
    ef_text = (first.source_root / "dos" / "input.fdf").read_text(encoding="utf-8")
    absolute_text = (second.source_root / "dos" / "input.fdf").read_text(encoding="utf-8")
    assert "ProjectedDensityOfStates\nEF  -2" in ef_text
    assert "EF  -2.0  2.0  0.1  4  eV" in ef_text
    assert "ProjectedDensityOfStates\n-2" in absolute_text
    assert ef_text != absolute_text
    assert first.identities["dos"].fingerprint != second.identities["dos"].fingerprint
    repeated = ElectronicPropertiesProtocol().prepare(source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "ef")
    assert (repeated.source_root / "dos" / "input.fdf").read_text(encoding="utf-8") == ef_text


def test_real_siesta_bands_and_xml_pdos_parsers_fail_closed(tmp_path: Path) -> None:
    bands = tmp_path / "carbon.bands"
    bands.write_text("0.0\n0.0 1.0\n-5.0 5.0\n2 1 2\n0.0 -1.0 1.0\n0.5 -0.5 2.0\n2\n0.0 Γ\n0.5 X\n", encoding="utf-8")
    parsed = parse_bands(bands)
    assert parsed["bands"] == 2 and parsed["kpoints"] == 2 and parsed["line_labels"] == ("Γ", "X")
    bands.write_text("0.0\n0.0 1.0\n-5.0 5.0\n2 1 2\n0.0 -1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="truncated"):
        parse_bands(bands)
    pdos = tmp_path / "carbon.PDOS"
    pdos.write_text("<?xml version='1.0'?><pdos><energy_values>-2 -1 0 1</energy_values><orbital><data>0.1 0.2 0.3 0.4</data></orbital></pdos>", encoding="utf-8")
    assert parse_pdos(pdos, expected_points=4)["orbitals"] == 1
    pdos.write_text("<pdos><energy_values>-2 -1", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        parse_pdos(pdos, expected_points=4)
    dos = tmp_path / "carbon.DOS"; dos.write_text("-1 0.1\n0 0.2\n", encoding="utf-8")
    assert parse_dos(dos)["rows"] == 2
    dos.write_text("-1 0.1\n-2 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="monotonic"):
        parse_dos(dos)


def test_identity_locality_for_each_spec_and_parent_state(tmp_path: Path) -> None:
    source = _source(tmp_path); bands, dos, pdos = _specs(); protocol = ElectronicPropertiesProtocol()
    first = protocol.prepare(source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "one")
    changed_dos = DosSpec("ABSOLUTE", -2, 2, 0.1, 4, "eV", dos.pdos_kgrid)
    dos_only = protocol.prepare(source, bands=bands, dos=changed_dos, pdos=pdos, runs_root=tmp_path / "two")
    changed_pdos = PdosSpec("ABSOLUTE", -2, 2, 0.1, 4, "eV", pdos.pdos_kgrid)
    pdos_only = protocol.prepare(source, bands=bands, dos=dos, pdos=changed_pdos, runs_root=tmp_path / "three")
    assert first.identities["bands"].fingerprint == dos_only.identities["bands"].fingerprint
    assert first.identities["pdos"].fingerprint == dos_only.identities["pdos"].fingerprint
    assert first.identities["dos"].fingerprint != dos_only.identities["dos"].fingerprint
    assert first.identities["bands"].fingerprint == pdos_only.identities["bands"].fingerprint
    assert first.identities["dos"].fingerprint == pdos_only.identities["dos"].fingerprint
    assert first.identities["pdos"].fingerprint != pdos_only.identities["pdos"].fingerprint
    source.density_matrix.write_bytes(b"new verified dm")
    raw = json.loads(source.state_path.read_text(encoding="utf-8")); payload = raw["payload"]
    payload["final_scf"]["density_matrix"]["sha256"] = _sha(source.density_matrix)
    source.state_path.write_text(json.dumps(ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload=payload).to_dict()), encoding="utf-8")
    changed_parent = ElectronicStateSource.load(source.state_path, final_fdf=source.final_fdf, density_matrix=source.density_matrix)
    parent_only = protocol.prepare(changed_parent, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "four")
    assert all(first.identities[name].fingerprint != parent_only.identities[name].fingerprint for name in ("bands", "dos", "pdos"))


def test_parent_root_include_pseudo_and_state_tampering_are_rejected(tmp_path: Path) -> None:
    bands, dos, pdos = _specs()
    root = tmp_path / "root"; root.mkdir(); source = _source(root)
    source.final_fdf.write_text(BASE + "# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="final FDF SHA"):
        ElectronicPropertiesProtocol().prepare(source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "root-run")
    included_root = tmp_path / "include"; included_root.mkdir(); included = _source(included_root, included=True)
    (included_root / "included.fdf").write_text(BASE + "# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="scientific identity"):
        ElectronicPropertiesProtocol().prepare(included, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "include-run")
    pseudo_root = tmp_path / "pseudo"; pseudo_root.mkdir(); pseudo = _source(pseudo_root)
    (pseudo_root / "C.psf").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="scientific identity"):
        ElectronicPropertiesProtocol().prepare(pseudo, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "pseudo-run")
    state_root = tmp_path / "state"; state_root.mkdir(); state = _source(state_root)
    raw = json.loads(state.state_path.read_text(encoding="utf-8")); raw["payload"]["artifact_type"] = "qraft.not-electronic-state"; state.state_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        ElectronicPropertiesProtocol().prepare(state, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "state-run")


def test_fanout_publishes_independent_artifacts(tmp_path: Path) -> None:
    source = _source(tmp_path); bands, dos, pdos = _specs()
    script = tmp_path / "fake_siesta.py"
    script.write_text(
        "from pathlib import Path\n"
        "text=Path('input.fdf').read_text()\n"
        "if 'BandLinesScale' in text: Path('carbon.bands').write_text('0.0\\n0.0 1.0\\n-5.0 5.0\\n2 1 2\\n0.0 -1.0 1.0\\n0.5 -0.5 2.0\\n2\\n0.0 G\\n0.5 X\\n')\n"
        "else:\n"
        " rows='-2 0.1\\n-1 0.2\\n0 0.3\\n1 0.4\\n'\n"
        " Path('carbon.DOS').write_text(rows)\n"
        " Path('carbon.PDOS').write_text(\"<?xml version='1.0'?><pdos><energy_values>-2 -1 0 1</energy_values><orbital><data>0.1 0.2 0.3 0.4</data></orbital></pdos>\")\n"
        "print('Siesta started')\nprint('SCF cycle 1')\nprint('SCF converged')\nprint('attempting to read DM from file succeeded')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    result = ElectronicPropertiesProtocol().run(
        source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "run",
        overrides={"partition": "local", "launcher": "direct", "executable": sys.executable, "executable_arguments": [str(script.resolve())]},
    )
    assert result["status"] == "COMPLETED"
    assert all(result["branches"][name].get("artifact") for name in ("bands", "dos", "pdos"))


def test_failed_dos_retries_while_successful_siblings_reuse(tmp_path: Path) -> None:
    source = _source(tmp_path); bands, _, _ = _specs()
    grid = ((2, 0, 0, 0.0), (0, 2, 0, 0.0), (0, 0, 2, 0.0))
    dos, pdos = DosSpec("ABSOLUTE", -2, 2, 0.1, 4, "eV", grid), PdosSpec("EF", -2, 2, 0.1, 4, "eV", grid)
    fail = tmp_path / "fail-dos"
    fail.write_text("yes", encoding="utf-8")
    script = tmp_path / "toggle_siesta.py"
    script.write_text(
        "from pathlib import Path\n"
        f"fail=Path(r'{fail.resolve()}')\ntext=Path('input.fdf').read_text()\n"
        "if 'BandLinesScale' in text: Path('carbon.bands').write_text('0.0\\n0.0 1.0\\n-5.0 5.0\\n2 1 2\\n0.0 -1.0 1.0\\n0.5 -0.5 2.0\\n2\\n0.0 G\\n0.5 X\\n')\n"
        "elif 'ProjectedDensityOfStates\\nEF' in text: Path('carbon.PDOS').write_text(\"<pdos><energy_values>-2 -1 0 1</energy_values><orbital><data>0.1 0.2 0.3 0.4</data></orbital></pdos>\")\n"
        "elif not fail.exists(): Path('carbon.DOS').write_text('-2 0.1\\n-1 0.2\\n0 0.3\\n1 0.4\\n')\n"
        "print('Siesta started')\nprint('SCF cycle 1')\nprint('SCF converged')\nprint('attempting to read DM from file succeeded')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    kwargs = {"partition": "local", "launcher": "direct", "executable": sys.executable, "executable_arguments": [str(script.resolve())]}
    protocol = ElectronicPropertiesProtocol(); root = tmp_path / "run"
    first = protocol.run(source, bands=bands, dos=dos, pdos=pdos, runs_root=root, overrides=kwargs)
    assert first["status"] == "FAILED" and first["branches"]["bands"].get("artifact") and first["branches"]["pdos"].get("artifact")
    fail.unlink()
    second = protocol.run(source, bands=bands, dos=dos, pdos=pdos, runs_root=root, overrides=kwargs)
    assert second["status"] == "COMPLETED"
    assert second["branches"]["bands"]["reused"] and second["branches"]["pdos"]["reused"]
    assert not second["branches"]["dos"]["reused"]
