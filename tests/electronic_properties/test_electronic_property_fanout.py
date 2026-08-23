from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.electronic_properties import BandPathSpec, BandPathVertex, DosSpec, PdosSpec, render_property_fdf, validate_property_neutral_parent
from qraft.protocols.electronic_properties import ElectronicPropertiesProtocol, ElectronicStateSource


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
        BandPathVertex((0.0, 0.0, 0.0), 0, "G"),
        BandPathVertex((0.5, 0.0, 0.0), 8, "X"),
    ))
    return bands, DosSpec("EF", -2.0, 2.0, 0.1, 4, "eV", grid), PdosSpec("EF", -2.0, 2.0, 0.1, 4, "eV", grid)


def _source(root: Path) -> ElectronicStateSource:
    final = root / "final.fdf"; final.write_text(BASE, encoding="utf-8")
    dm = root / "carbon.DM"; dm.write_bytes(b"verified-dm")
    (root / "C.psf").write_text("pseudo", encoding="utf-8")
    state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={
        "schema_version": "1.0", "artifact_id": "electronic-state", "artifact_type": "qraft.electronic-state", "authority": "PROVISIONAL", "engine": "siesta",
        "final_scf": {"input_fdf_sha256": _sha(final), "system_label": "carbon", "density_matrix": {"filename": "carbon.DM", "sha256": _sha(dm)}},
    }).to_dict()
    state_path = root / "electronic-state.json"; state_path.write_text(json.dumps(state), encoding="utf-8")
    return ElectronicStateSource.load(state_path, final_fdf=final, density_matrix=dm)


def test_parent_gate_rendering_and_identity_locality(tmp_path: Path) -> None:
    source = _source(tmp_path); bands, dos, pdos = _specs()
    prepared = ElectronicPropertiesProtocol().prepare(source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "m7")
    assert {task.task_id for task in prepared.compiled.tasks} == {"bands", "dos", "pdos"}
    assert all(not task.dependencies for task in prepared.compiled.tasks)
    assert "DM.UseSaveDM true" in (prepared.source_root / "bands" / "input.fdf").read_text(encoding="utf-8")
    assert prepared.identities["bands"].fingerprint != prepared.identities["dos"].fingerprint
    changed_bands = BandPathSpec("ReciprocalLatticeVectors", (BandPathVertex((0, 0, 0), 0, "G"), BandPathVertex((0.25, 0, 0), 8, "Q")))
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


def test_fanout_publishes_independent_artifacts(tmp_path: Path) -> None:
    source = _source(tmp_path); bands, dos, pdos = _specs()
    script = tmp_path / "fake_siesta.py"
    script.write_text(
        "from pathlib import Path\n"
        "text=Path('input.fdf').read_text()\n"
        "if 'BandLinesScale' in text: Path('carbon.bands').write_text('0.0\\n0.0 1.0\\n')\n"
        "else:\n"
        " rows='-2 0.1\\n-1 0.2\\n0 0.3\\n1 0.4\\n'\n"
        " Path('carbon.DOS').write_text(rows)\n"
        " Path('carbon.PDOS').write_text(rows)\n"
        "print('Siesta started')\nprint('SCF cycle 1')\nprint('SCF converged')\nprint('attempting to read DM from file succeeded')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    result = ElectronicPropertiesProtocol().run(
        source, bands=bands, dos=dos, pdos=pdos, runs_root=tmp_path / "run",
        overrides={"partition": "local", "launcher": "direct", "executable": sys.executable, "executable_arguments": [str(script.resolve())]},
    )
    assert result["status"] == "COMPLETED"
    assert all(result["branches"][name].get("artifact") for name in ("bands", "dos", "pdos"))
