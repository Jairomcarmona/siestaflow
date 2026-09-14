from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qraft.band_paths import BandPathMode, BandPathRequest, CrystalStructure
from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.band_paths import time_reversal_evidence_from_final_fdf
from qraft.engines.siesta.ground_state import validate_final_scf
from qraft.engines.siesta.magnetism import (
    magnetic_artifact_envelope,
    magnetic_spin_from_fdf,
    materialize_noncollinear_spin_fdf,
    parse_noncollinear_magnetic_output,
)
from qraft.magnetism import (
    CollinearSpinMoment,
    CollinearSpinSpec,
    NonCollinearSpinMoment,
    NonCollinearSpinSpec,
)
from qraft.protocols.electronic_properties import ElectronicStateSource
from qraft.protocols.single_fdf import build_fdf_plan, build_scientific_identity


BASE = """SystemName noncollinear fixture
SystemLabel noncollinear
NumberOfAtoms 2
NumberOfSpecies 1
Mesh.Cutoff 100 Ry
PAO.EnergyShift 50 meV
LatticeConstant 1 Ang
%block ChemicalSpeciesLabel
1 26 Fe
%endblock ChemicalSpeciesLabel
%block LatticeVectors
5 0 0
0 5 0
0 0 5
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
2 0 0 1
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


def _base(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    fdf = root / "base.fdf"
    fdf.write_text(BASE, encoding="utf-8")
    (root / "Fe.psf").write_text("pseudo", encoding="utf-8")
    return fdf


def _render(root: Path, name: str, spec: NonCollinearSpinSpec) -> Path:
    rendered = materialize_noncollinear_spin_fdf(_base(root / "source"), root / name, spec, primary_destination="input.fdf")
    (root / name / "Fe.psf").write_text("pseudo", encoding="utf-8")
    return rendered.root_fdf


def _vector_stdout() -> str:
    return """Version : 5.4.2
redata: Spin configuration = non-collinear
redata: Number of spin components = 4
Mulliken Atomic Populations:
Atom # charge [q] valence [e] S [e] Sx [e] Sy [e] Sz [e] Species
  1 0.0 8.0 2.0 2.0 0.0 0.0 Fe
  2 0.0 8.0 2.0 0.0 2.0 0.0 Fe
 Total 0.0 16.0 2.828427124746 2.0 2.0 0.0
"""


def _native_siesta_542_vector_stdout() -> str:
    """Native SIESTA 5.4.2 header: S is deliberately printed without [e]."""

    return """Version : 5.4.2
redata: Spin configuration = non-collinear
redata: Number of spin components = 4
mulliken: Atomic and Orbital Populations:
    1  1 3s         2.00997   0.00026     -0.000   0.000   0.000
Mulliken Atomic Populations:
Atom #   charge [q] valence [e]           S      Sx [e]      Sy [e]      Sz [e]  Species
     1    -0.000018   16.000018    3.203569    2.997290    1.130978   -0.000000  Fe
     2     0.000018   15.999982    3.202395    1.126546    2.997704   -0.000000  Fe
-------------------------------------------------------------------------------
 Total     0.000000                5.835412    4.123836    4.128681   -0.000000
"""


def test_noncollinear_model_renderer_and_initialization_semantics(tmp_path: Path) -> None:
    spec = NonCollinearSpinSpec((
        NonCollinearSpinMoment(1, "+", 90.0, 0.0),
        NonCollinearSpinMoment(2, -2.5, 45.0, -90.0),
    ))
    fdf = _render(tmp_path, "vector", spec)
    text = fdf.read_text(encoding="utf-8")
    assert "Spin non-colinear" in text
    assert "  1 + 90.0 0.0" in text and "  2 -2.5 45.0 -90.0" in text
    assert "Charge.Mulliken end" in text
    parsed = magnetic_spin_from_fdf(fdf)
    assert parsed is not None and parsed.canonical() == spec.canonical()

    implicit = _render(tmp_path, "implicit", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+"),)))
    zero = _render(tmp_path, "zero", NonCollinearSpinSpec((NonCollinearSpinMoment(1, 0.0, 90.0, 0.0),)))
    explicit_empty = _render(tmp_path, "empty", NonCollinearSpinSpec(()))
    absent = _render(tmp_path, "absent", NonCollinearSpinSpec())
    assert "  1 +\n" in implicit.read_text(encoding="utf-8")
    assert "  1 0.0 90.0 0.0" in zero.read_text(encoding="utf-8")
    assert "%block DM.InitSpin\n\n%endblock DM.InitSpin" in explicit_empty.read_text(encoding="utf-8")
    assert "%block DM.InitSpin" not in absent.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="both theta_deg and phi_deg"):
        NonCollinearSpinMoment(1, "+", 90.0)
    with pytest.raises(ValueError, match="finite"):
        NonCollinearSpinMoment(1, 1.0, float("nan"), 0.0)
    with pytest.raises(ValueError, match="unique"):
        NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+"), NonCollinearSpinMoment(1, "-")))
    with pytest.raises(ValueError, match="exceeds"):
        _render(tmp_path, "range", NonCollinearSpinSpec((NonCollinearSpinMoment(3, "+"),)))


def test_noncollinear_scope_is_fail_closed(tmp_path: Path) -> None:
    for name, directive in (
        ("fix", "Spin.Fix true"),
        ("total", "Spin.Total 2.0"),
        ("spiral", "Spin.Spiral true"),
        ("soc", "Spin.Orbit true"),
        ("hubbard", "DFTU.FirstIteration true"),
        ("time-reversal", "TimeReversalSymmetryForKpoints true"),
    ):
        fdf = _base(tmp_path / name)
        fdf.write_text(BASE + "Spin non-colinear\n" + directive + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            validate_final_scf(fdf)
    fdf = _base(tmp_path / "partial")
    fdf.write_text(BASE + "Spin non-colinear\n%block DM.InitSpin\n  1 + 90.0\n%endblock DM.InitSpin\n", encoding="utf-8")
    with pytest.raises(ValueError, match="atom polarization theta phi"):
        magnetic_spin_from_fdf(fdf)


def test_unexecuted_real_siesta_fixtures_use_canonical_m8b_input() -> None:
    fixtures = Path(__file__).parents[2] / "docs" / "validation" / "m8_b_noncollinear_real_siesta_fixtures"
    bcc = magnetic_spin_from_fdf(fixtures / "bcc_fe_x.fdf")
    fcc = magnetic_spin_from_fdf(fixtures / "fcc_fe_nonparallel.fdf")
    fe2 = magnetic_spin_from_fdf(fixtures / "fe2_nonparallel.fdf")
    assert bcc is not None and bcc.canonical()["initialization"]["moments"] == [{"atom_index": 1, "polarization": "+", "theta_deg": "90.0", "phi_deg": "0.0", "direction": "explicit"}]
    assert fcc is not None and len(fcc.canonical()["initialization"]["moments"]) == 2
    assert fe2 is not None and len(fe2.canonical()["initialization"]["moments"]) == 2


def test_noncollinear_identity_binds_direction_not_resources(tmp_path: Path) -> None:
    z = _render(tmp_path, "z", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+"),)))
    x = _render(tmp_path, "x", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0),)))
    y = _render(tmp_path, "y", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+", 90.0, 90.0),)))
    multi = _render(tmp_path, "multi", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0), NonCollinearSpinMoment(2, "+", 90.0, 90.0))))
    assert len({build_scientific_identity(path).fingerprint for path in (z, x, y, multi)}) == 4
    first = build_fdf_plan(x, overrides={"partition": "local", "launcher": "direct", "executable": "siesta", "mpi_ranks": 1})
    second = build_fdf_plan(x, overrides={"partition": "remote", "launcher": "openmpi", "executable": "siesta", "nodes": 2, "mpi_ranks": 4})
    assert first["scientific_identity"]["fingerprint"] == second["scientific_identity"]["fingerprint"]
    collinear = _base(tmp_path / "collinear")
    collinear.write_text(BASE + "Spin polarized\n%block DM.InitSpin\n  1 +\n%endblock DM.InitSpin\n", encoding="utf-8")
    assert build_scientific_identity(collinear).fingerprint != build_scientific_identity(x).fingerprint
    assert CollinearSpinSpec((CollinearSpinMoment(1, "+"),)).spin_mode == "polarized"


def test_noncollinear_vector_parser_and_artifact_are_fail_closed(tmp_path: Path) -> None:
    stdout = tmp_path / "stdout.txt"
    stdout.write_text(_vector_stdout(), encoding="utf-8")
    observed = parse_noncollinear_magnetic_output(stdout.read_text(encoding="utf-8").splitlines(True), scf_converged=True, required_atom_count=2)
    assert observed.spin_mode == "non-collinear"
    assert observed.atomic_vectors[0] == (1, 2.0, 2.0, 0.0, 0.0)
    assert observed.canonical()["quantity"]["name"] == "mulliken_spin_population"
    assert observed.canonical()["atomic_vectors"][0]["S"] == "2.0"  # never the charge column
    with pytest.raises(ValueError, match="truncated"):
        parse_noncollinear_magnetic_output(_vector_stdout().splitlines(True)[:-1], scf_converged=True)
    with pytest.raises(ValueError, match="complete"):
        parse_noncollinear_magnetic_output(_vector_stdout().splitlines(True), scf_converged=True, required_atom_count=3)
    duplicate = _vector_stdout().replace("  2 0.0 8.0 2.0 0.0 2.0 0.0 Fe", "  1 0.0 8.0 2.0 0.0 2.0 0.0 Fe")
    with pytest.raises(ValueError, match="duplicate"):
        parse_noncollinear_magnetic_output(duplicate.splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="SOC"):
        parse_noncollinear_magnetic_output((_vector_stdout() + "Spin-orbit enabled\n").splitlines(True), scf_converged=True)
    with pytest.raises(ValueError):
        parse_noncollinear_magnetic_output(_vector_stdout().replace("2.0 2.0 0.0 0.0 Fe", "NaN 2.0 0.0 0.0 Fe").splitlines(True), scf_converged=True)
    native = parse_noncollinear_magnetic_output(_native_siesta_542_vector_stdout().splitlines(True), scf_converged=True, required_atom_count=2)
    assert native.atomic_vectors[0] == (1, 3.203569, 2.99729, 1.130978, -0.0)
    with pytest.raises(ValueError, match="inconsistent"):
        parse_noncollinear_magnetic_output(_native_siesta_542_vector_stdout().replace("3.203569", "3.204569").splitlines(True), scf_converged=True, required_atom_count=2)
    with pytest.raises(ValueError, match="complete"):
        parse_noncollinear_magnetic_output(_native_siesta_542_vector_stdout().replace("     2     0.000018   15.999982    3.202395    1.126546    2.997704   -0.000000  Fe\n", "").splitlines(True), scf_converged=True, required_atom_count=2)
    with pytest.raises(ValueError, match="duplicate"):
        parse_noncollinear_magnetic_output(_native_siesta_542_vector_stdout().replace("     2     0.000018", "     1     0.000018").splitlines(True), scf_converged=True, required_atom_count=2)
    with pytest.raises(ValueError, match="malformed"):
        parse_noncollinear_magnetic_output(_native_siesta_542_vector_stdout().replace("3.203569", "NaN").splitlines(True), scf_converged=True, required_atom_count=2)

    fdf = _render(tmp_path, "artifact", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0), NonCollinearSpinMoment(2, "+", 90.0, 90.0))))
    requested = magnetic_spin_from_fdf(fdf)
    assert requested is not None
    artifact = magnetic_artifact_envelope(parent_scientific_identity_sha256=build_scientific_identity(fdf).fingerprint, requested=requested, observed=observed, final_fdf=fdf, stdout=stdout, scf_converged=True, siesta_version="5.4.2", stdout_relative_path="stdout.txt")
    payload = artifact["payload"]
    assert payload["requested"]["spin_mode"] == "non-collinear"
    assert payload["observed"]["spin_mode"] == "non-collinear"
    assert payload["observed"]["quantity"]["representation"] == "cartesian"


def test_noncollinear_m6_to_m7_verifies_hashes_and_m71_remains_conservative(tmp_path: Path) -> None:
    fdf = _render(tmp_path, "m6", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0), NonCollinearSpinMoment(2, "+", 90.0, 90.0))))
    dm = tmp_path / "m6" / "noncollinear.DM"
    dm.write_bytes(b"verified-dm")
    stdout = tmp_path / "m6" / "stdout.txt"
    stdout.write_text(_vector_stdout(), encoding="utf-8")
    requested = magnetic_spin_from_fdf(fdf)
    assert requested is not None
    observed = parse_noncollinear_magnetic_output(_vector_stdout().splitlines(True), scf_converged=True, required_atom_count=2)
    magnetic = magnetic_artifact_envelope(parent_scientific_identity_sha256=build_scientific_identity(fdf).fingerprint, requested=requested, observed=observed, final_fdf=fdf, stdout=stdout, scf_converged=True, siesta_version="5.4.2", stdout_relative_path="stdout.txt")
    magnetic_path = tmp_path / "m6" / "magnetic-state.json"
    magnetic_path.write_text(json.dumps(magnetic), encoding="utf-8")
    state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={
        "schema_version": "1.0", "artifact_id": "electronic-state", "artifact_type": "qraft.electronic-state", "authority": "PROVISIONAL", "engine": "siesta",
        "final_scf": {"input_fdf_sha256": _sha(fdf), "scientific_identity_sha256": build_scientific_identity(fdf).fingerprint, "system_label": "noncollinear", "density_matrix": {"filename": dm.name, "sha256": _sha(dm)}, "spin_mode": "non-collinear", "magnetic": {"spin_mode": "non-collinear", "requested": requested.canonical(), "observed": observed.canonical(), "artifact": {"artifact_type": "qraft.magnetic-state", "relative_path": magnetic_path.name, "sha256": _sha(magnetic_path), "content_sha256": magnetic["content_sha256"]}}},
    }).to_dict()
    state_path = tmp_path / "m6" / "electronic-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    source = ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    assert source.spin_mode == "non-collinear" and source.magnetic_state_file_sha256 == _sha(magnetic_path)
    magnetic_path.write_text(json.dumps({**magnetic, "content_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact file SHA-256 mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    magnetic_path.write_text(json.dumps(magnetic), encoding="utf-8")
    stdout.write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="stdout SHA-256 mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    assert time_reversal_evidence_from_final_fdf(fdf) is None
    structure = CrystalStructure(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), ((0.0, 0.0, 0.0),), (26,))
    assert BandPathRequest(BandPathMode.SUGGEST, structure=structure, time_reversal="auto").resolved_time_reversal is None
    assert BandPathRequest(BandPathMode.SUGGEST, structure=structure, time_reversal="false").resolved_time_reversal is False
