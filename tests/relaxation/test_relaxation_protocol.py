from __future__ import annotations

import json
import sys
import hashlib
from pathlib import Path

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.relaxation import _force_from_text, geometry_from_fdf, parse_struct_out, validate_relaxation
from qraft.engines.siesta.fdf_parser import FDFParser
from qraft.protocols.relaxation import RelaxationProtocol
from qraft.protocols.single_fdf import build_scientific_identity
from qraft.workflows import WorkflowCompiler


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


def test_real_force_blocks_choose_the_final_constrained_maximum() -> None:
    real = """siesta: Atomic forces (eV/Ang):
----------------------------------------
   Tot   -0.007380    0.003411   -0.000111
----------------------------------------
   Max    0.027049
   Res    0.014184    sqrt( Sum f_i^2 / 3N )
----------------------------------------
   Max    0.019000    constrained
"""
    assert _force_from_text(real) == pytest.approx(0.019)
    iterations = """siesta: Atomic forces (Ry/Bohr):
 Max 0.2
siesta: Atomic forces (eV/Ang):
 Max 0.04
 Max 0.01 constrained
"""
    assert _force_from_text(iterations) == pytest.approx(0.01)
    assert _force_from_text("Maximum force: 0.01 eV/Ang") == pytest.approx(0.01)
    with pytest.raises(ValueError, match="unsupported force unit"):
        _force_from_text("siesta: Atomic forces (Hartree/Bohr):\n Max 0.1\n")


def test_siesta_defaults_and_variable_cell_logicals_fail_closed(tmp_path: Path) -> None:
    default_bohr = FDF.replace("AtomicCoordinatesFormat Fractional\n", "").replace("0.1 0.2 0.3 1", "1 2 3 1")
    assert geometry_from_fdf(_input(tmp_path / "default-bohr", default_bohr))["atoms"][0]["coordinates"] == pytest.approx([0.529177210903, 1.058354421806, 1.587531632709])
    for value in ("T", "true", ".true.", "YES", ""):
        text = FDF.replace("MD.VariableCell F", f"MD.VariableCell {value}".rstrip())
        with pytest.raises(ValueError, match="variable-cell"):
            validate_relaxation(FDFParser().parse(text))
    for value in ("F", "false", ".false.", "no"):
        assert validate_relaxation(FDFParser().parse(FDF.replace("MD.VariableCell F", f"MD.VariableCell {value}"))) > 0
    assert validate_relaxation(FDFParser().parse(FDF.replace("MD.VariableCell F\n", ""))) > 0
    with pytest.raises(ValueError, match="invalid FDF logical"):
        validate_relaxation(FDFParser().parse(FDF.replace("MD.VariableCell F", "MD.VariableCell maybe")))
    blocked_fdf = _input(tmp_path / "prelaunch", FDF.replace("MD.VariableCell F", "MD.VariableCell .true."))
    launcher = tmp_path / "prelaunch" / "marker.py"
    launcher.write_text("from pathlib import Path\nPath('launched').write_text('unexpected launch')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="variable-cell"):
        RelaxationProtocol().run(blocked_fdf, runs_root=tmp_path / "blocked", overrides={"launcher": "direct", "partition": "local", "executable": sys.executable, "executable_arguments": [str(launcher)]})
    assert not (tmp_path / "blocked" / "work" / "relax" / "attempt-0001" / "launched").exists()


def test_canonical_closure_stages_includes_pseudos_and_normalized_label(tmp_path: Path) -> None:
    root = tmp_path / "scientific"; subdir = root / "subdir"; subdir.mkdir(parents=True)
    fdf = _input(root, FDF.replace("SystemLabel relax", "System_Label closure") + "%include subdir/settings.fdf\n")
    (subdir / "settings.fdf").write_text("MeshCutoff 100 Ry\n", encoding="utf-8")
    manifest = root / "pseudo-manifest.json"
    manifest.write_text(json.dumps({"entries": [{"species": "C", "path": "C.psf"}]}), encoding="utf-8")
    script = root / "closure_fake.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "required = ('input.fdf', 'subdir/settings.fdf', 'C.psf')\n"
        "if not all(Path(name).is_file() for name in required): sys.exit(2)\n"
        "Path('closure.STRUCT_OUT').write_text('10 0 0\\n0 10 0\\n0 0 10\\n1\\n1 0 0.1 0.2 0.3\\n')\n"
        "print('Siesta started')\nprint('SCF converged')\n"
        "print('siesta: Atomic forces (eV/Ang):')\nprint(' Max 0.01 constrained')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    protocol = RelaxationProtocol(); run_root = tmp_path / "runs"
    result = protocol.run(fdf, pseudo_manifest=manifest, runs_root=run_root, overrides={"launcher": "direct", "partition": "local", "executable": sys.executable, "executable_arguments": [str(script)]})
    assert result["technical_validation"] == "PASS" and result["scientific_decision"] == "CONVERGED", result
    attempt = run_root / "work" / "relax" / "attempt-0001"
    assert all((attempt / name).is_file() for name in ("input.fdf", "subdir/settings.fdf", "C.psf", "pseudo-manifest.json"))
    compiled = WorkflowCompiler().compile(run_root / "relaxation-workflow.json").compiled
    assert compiled is not None
    bound = {artifact.relative_path: artifact.sha256 for artifact in compiled.external_artifacts}
    for relative in ("inputs/input.fdf", "inputs/subdir/settings.fdf", "inputs/C.psf", "inputs/pseudo-manifest.json"):
        assert bound[relative] == hashlib.sha256((run_root / relative).read_bytes()).hexdigest()
    before = build_scientific_identity(fdf, pseudo_manifest=manifest).fingerprint
    (root / "C.psf").write_text("changed pseudo\n", encoding="utf-8")
    assert build_scientific_identity(fdf, pseudo_manifest=manifest).fingerprint != before


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
