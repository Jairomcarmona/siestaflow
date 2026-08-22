from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.relaxation import geometry_from_fdf, parse_struct_out, validate_relaxation
from qraft.engines.siesta.fdf_parser import FDFParser
from qraft.protocols.relaxation import RelaxationProtocol


FDF = """SystemName relax
SystemLabel relax
NumberOfAtoms 1
NumberOfSpecies 1
MD.TypeOfRun CG
MD.Steps 20
MD.VariableCell F
MD.MaxForceTol 0.05 eV/Ang
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10 0 0
0 10 0
0 0 10
%endblock LatticeVectors
AtomicCoordinatesFormat Fractional
%block AtomicCoordinatesAndAtomicSpecies
0.1 0.2 0.3 1
%endblock AtomicCoordinatesAndAtomicSpecies
"""


def _input(root: Path, text: str = FDF) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "input.fdf"; path.write_text(text, encoding="utf-8")
    (root / "C.psf").write_text("pseudo\n", encoding="utf-8")
    return path


def _overrides(root: Path, *, force: float = 0.01, struct: bool = True, drift: bool = False) -> dict:
    script = root / "fake.py"
    cell = "11 0 0\\n0 10 0\\n0 0 10" if drift else "10 0 0\\n0 10 0\\n0 0 10"
    body = "" if not struct else f"open('relax.STRUCT_OUT','w').write('{cell}\\n1\\n1 0 0.1 0.2 0.3\\n')\n"
    script.write_text("import sys\nfrom pathlib import Path\n" + body + f"print('Siesta started')\nprint('SCF converged')\nprint('Maximum force: {force} eV/Ang')\nprint('Job completed')\n", encoding="utf-8")
    return {"launcher": "direct", "partition": "local", "executable": sys.executable, "executable_arguments": [str(script)]}


def test_geometry_normalization_and_struct_out(tmp_path: Path) -> None:
    fdf = _input(tmp_path)
    geometry = geometry_from_fdf(fdf)
    assert geometry["cell"] == [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]
    assert geometry["atoms"] == [{"index": 1, "species_index": 1, "coordinates": [1.0, 2.0, 3.0]}]
    struct = tmp_path / "relax.STRUCT_OUT"; struct.write_text("10 0 0\n0 10 0\n0 0 10\n1\n1 0 0.1 0.2 0.3\n", encoding="utf-8")
    assert parse_struct_out(struct)["atoms"][0]["coordinates"] == [1.0, 2.0, 3.0]
    bohr = geometry_from_fdf(_input(tmp_path / "bohr", FDF.replace("AtomicCoordinatesFormat Fractional", "AtomicCoordinatesFormat Bohr").replace("0.1 0.2 0.3 1", "1 2 3 1")))
    assert bohr["atoms"][0]["coordinates"] == pytest.approx([0.529177210903, 1.058354421806, 1.587531632709])
    with pytest.raises(ValueError, match="variable-cell"):
        validate_relaxation(FDFParser().parse(FDF.replace("MD.VariableCell F", "MD.VariableCell T")))
    with pytest.raises(ValueError, match="MaxForceTol"):
        validate_relaxation(FDFParser().parse(FDF.replace("MD.MaxForceTol 0.05 eV/Ang\n", "")))


def test_canonical_fixed_cell_relaxation_reuse_and_scientific_policy(tmp_path: Path) -> None:
    fdf = _input(tmp_path); root = tmp_path / "runs"; protocol = RelaxationProtocol()
    first = protocol.run(fdf, overrides=_overrides(tmp_path), runs_root=root)
    assert first["technical_validation"] == "PASS" and first["scientific_decision"] == "CONVERGED"
    geometry_path = root / "work" / "relax" / "attempt-0001" / "relaxed-geometry.json"
    envelope = ContractEnvelope.from_dict(json.loads(geometry_path.read_text(encoding="utf-8")), required_contract=SCIENTIFIC_ARTIFACT)
    assert envelope.payload["artifact_type"] == "qraft.geometry" and first["geometry_reference"].sha256 == __import__("hashlib").sha256(geometry_path.read_bytes()).hexdigest()
    second = protocol.run(fdf, overrides=_overrides(tmp_path), runs_root=root)
    assert second["reused"] and not (root / "work" / "relax" / "attempt-0002").exists()
    nonconverged = protocol.run(fdf, overrides=_overrides(tmp_path, force=0.2), runs_root=tmp_path / "nonconverged")
    assert nonconverged["technical_validation"] == "PASS" and nonconverged["scientific_decision"] == "NOT_CONVERGED" and "geometry_reference" not in nonconverged


def test_missing_geometry_and_fixed_cell_drift_are_rejected(tmp_path: Path) -> None:
    fdf = _input(tmp_path); protocol = RelaxationProtocol()
    missing = protocol.run(fdf, overrides=_overrides(tmp_path, struct=False), runs_root=tmp_path / "missing")
    assert missing["technical_validation"] != "PASS" and "geometry_reference" not in missing
    drift = protocol.run(fdf, overrides=_overrides(tmp_path, drift=True), runs_root=tmp_path / "drift")
    assert drift["technical_validation"] == "PASS" and drift["status"] == "BLOCKED" and "geometry_reference" not in drift
