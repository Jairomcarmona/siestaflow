from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.band_paths import time_reversal_evidence_from_final_fdf
from qraft.engines.siesta.ground_state import validate_final_scf
from qraft.engines.siesta.magnetism import (
    PseudoRelativity,
    classify_psml_relativity,
    magnetic_artifact_envelope,
    magnetic_spin_from_fdf,
    materialize_noncollinear_spin_fdf,
    materialize_spin_orbit_fdf,
    parse_spin_orbit_magnetic_output,
    soc_pseudopotential_evidence,
)
from qraft.engines.siesta.input_closure import resolve_scientific_input_closure
from qraft.magnetism import NonCollinearSpinMoment, NonCollinearSpinSpec, SpinOrbitSpec
from qraft.protocols.electronic_properties import ElectronicStateSource
from qraft.protocols.single_fdf import build_fdf_plan, build_scientific_identity


BASE = """SystemName SOC fixture
SystemLabel soc
NumberOfAtoms 2
NumberOfSpecies 1
Mesh.Cutoff 100 Ry
PAO.EnergyShift 50 meV
LatticeConstant 1 Ang
%block ChemicalSpeciesLabel
1 26 Fe
%endblock ChemicalSpeciesLabel
%block LatticeVectors
20 0 0
0 20 0
0 0 20
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


def _psml(kind: str = "full") -> str:
    if kind == "full":
        return '<psml><pseudo-atom-spec relativistic="full"/><projector l="2" j="2.5"/></psml>\n'
    if kind == "scalar":
        return '<psml><pseudo-atom-spec relativity="scalar-relativistic"/></psml>\n'
    if kind == "unknown":
        return '<psml><pseudo-atom-spec/></psml>\n'
    return '<psml><pseudo-atom-spec>'


def _base(root: Path, *, pseudo: str = "full") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    fdf = root / "base.fdf"
    fdf.write_text(BASE, encoding="utf-8")
    (root / "Fe.psml").write_text(_psml(pseudo), encoding="utf-8")
    return fdf


def _render(root: Path, name: str, spec: SpinOrbitSpec) -> Path:
    rendered = materialize_spin_orbit_fdf(_base(root / "source"), root / name, spec, primary_destination="input.fdf")
    (root / name / "Fe.psml").write_text(_psml(), encoding="utf-8")
    return rendered.root_fdf


def _soc_stdout() -> str:
    return """Version : 5.4.2
redata: Spin configuration = spin-orbit
redata: Number of spin components = 4
Mulliken Atomic Populations:
Atom # charge [q] valence [e] S [e] Sx [e] Sy [e] Sz [e] Species
  1 0.0 8.0 2.0 2.0 0.0 0.0 Fe
  2 0.0 8.0 2.0 0.0 2.0 0.0 Fe
 Total 0.0 16.0 2.828427124746 2.0 2.0 0.0
"""


def _real_soc_542_dialect() -> str:
    """Small structural fixture extracted from preserved native SOC-Z output."""

    return """There are spin-orbit semi-local pseudopotentials available
redata: Spin configuration                          = spin-orbit+offsite
redata: Number of spin components                   = 8
siesta: Enl(+so)=      -240.616329
Mulliken Atomic Populations:
Atom #   charge [q] valence [e]           S      Sx [e]      Sy [e]      Sz [e]  Species
     1     0.000000   16.000000    3.997496   -0.000000    0.000000    3.997496  Fe
-------------------------------------------------------------------------------
 Total     0.000000                3.997496   -0.000000    0.000000    3.997496
"""


def test_soc_model_reuses_directional_initialization_and_canonical_renderer(tmp_path: Path) -> None:
    spec = SpinOrbitSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0), NonCollinearSpinMoment(2, -1.5, 90.0, 90.0)))
    fdf = _render(tmp_path, "xy", spec)
    text = fdf.read_text(encoding="utf-8")
    assert "Spin spin-orbit" in text
    assert "  1 + 90.0 0.0" in text and "  2 -1.5 90.0 90.0" in text
    assert "Charge.Mulliken end" in text
    parsed = magnetic_spin_from_fdf(fdf)
    assert parsed is not None and parsed.canonical() == spec.canonical()
    assert "%block DM.InitSpin" not in _render(tmp_path, "absent", SpinOrbitSpec()).read_text(encoding="utf-8")
    assert "%block DM.InitSpin\n\n%endblock DM.InitSpin" in _render(tmp_path, "empty", SpinOrbitSpec(())).read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="both theta_deg"):
        SpinOrbitSpec((NonCollinearSpinMoment(1, "+", 90.0),))
    with pytest.raises(ValueError, match="unique"):
        SpinOrbitSpec((NonCollinearSpinMoment(1, "+"), NonCollinearSpinMoment(1, "-")))


def test_soc_scope_and_psml_preflight_are_fail_closed(tmp_path: Path) -> None:
    for name, directive in (
        ("fix", "Spin.Fix true"), ("total", "Spin.Total 1"), ("spiral", "Spin.Spiral true"),
        ("strength", "Spin.OrbitStrength 1.0"), ("onsite", "Spin spin-orbit+onsite"),
        ("tr", "TimeReversalSymmetryForKpoints true"), ("hubbard", "DFTU.FirstIteration true"),
    ):
        fdf = _base(tmp_path / name)
        fdf.write_text(BASE + "Spin spin-orbit\n" + directive + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            validate_final_scf(fdf)
    full = _base(tmp_path / "full")
    scalar = _base(tmp_path / "scalar", pseudo="scalar")
    unknown = _base(tmp_path / "unknown", pseudo="unknown")
    malformed = _base(tmp_path / "malformed", pseudo="malformed")
    assert classify_psml_relativity(full.parent / "Fe.psml")[0] is PseudoRelativity.FULLY_RELATIVISTIC
    assert classify_psml_relativity(scalar.parent / "Fe.psml")[0] is PseudoRelativity.SCALAR_RELATIVISTIC
    assert classify_psml_relativity(unknown.parent / "Fe.psml")[0] is PseudoRelativity.UNKNOWN
    for fdf in (scalar, unknown, malformed):
        fdf.write_text(BASE + "Spin spin-orbit\n", encoding="utf-8")
        with pytest.raises(ValueError):
            validate_final_scf(fdf)
        with pytest.raises(ValueError):
            build_fdf_plan(fdf, overrides={"launcher": "direct", "executable": "siesta", "mpi_ranks": 1})
    full.write_text(BASE + "Spin spin-orbit\n", encoding="utf-8")
    assert soc_pseudopotential_evidence(full)["Fe"]["compatibility"] == "FULLY_RELATIVISTIC"


def test_soc_classifier_recognizes_real_psml_dirac_lj_semantics(tmp_path: Path) -> None:
    pseudo = tmp_path / "Fe.psml"
    pseudo.write_text(
        '<psml version="1.1"><pseudo-atom-spec atomic-label="Fe" atomic-number="26" relativity="dirac"/>'
        '<nonlocal-projectors set="scalar_relativistic"><proj l="d"/></nonlocal-projectors>'
        '<nonlocal-projectors set="spin_orbit"><proj l="d"/></nonlocal-projectors>'
        '<nonlocal-projectors set="lj"><proj l="d" j="2.5"/></nonlocal-projectors></psml>\n',
        encoding="utf-8",
    )
    state, evidence = classify_psml_relativity(pseudo)
    assert state is PseudoRelativity.FULLY_RELATIVISTIC
    assert "pseudo-atom-spec@relativity=dirac" in evidence
    assert "nonlocal-projectors@set=lj" in evidence


def test_soc_identity_is_directional_and_resource_independent_without_changing_legacy(tmp_path: Path) -> None:
    z = _render(tmp_path, "z", SpinOrbitSpec((NonCollinearSpinMoment(1, "+"),)))
    x = _render(tmp_path, "x", SpinOrbitSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0),)))
    y = _render(tmp_path, "y", SpinOrbitSpec((NonCollinearSpinMoment(1, "+", 90.0, 90.0),)))
    assert len({build_scientific_identity(path).fingerprint for path in (z, x, y)}) == 3
    noncollinear = materialize_noncollinear_spin_fdf(_base(tmp_path / "nc-source"), tmp_path / "nc", NonCollinearSpinSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0),)), primary_destination="input.fdf").root_fdf
    (noncollinear.parent / "Fe.psml").write_text(_psml(), encoding="utf-8")
    assert build_scientific_identity(noncollinear).fingerprint != build_scientific_identity(x).fingerprint
    first = build_fdf_plan(x, overrides={"launcher": "direct", "executable": "siesta", "mpi_ranks": 1})
    second = build_fdf_plan(x, overrides={"launcher": "openmpi", "executable": "siesta", "nodes": 2, "mpi_ranks": 4})
    assert first["scientific_identity"]["fingerprint"] == second["scientific_identity"]["fingerprint"]
    before = build_scientific_identity(x).fingerprint
    (x.parent / "Fe.psml").write_text(_psml() + "<!-- distinct full-SOC pseudo bytes -->\n", encoding="utf-8")
    assert build_scientific_identity(x).fingerprint != before
    # The exact historical native fixture remains fixed by M8-A/M8-B's
    # dedicated regression tests; this SOC fixture intentionally uses PSML.


def test_soc_parser_artifact_and_m7_handoff_verify_full_evidence(tmp_path: Path) -> None:
    fdf = _render(tmp_path, "m6", SpinOrbitSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0),)))
    dm, stdout = fdf.parent / "soc.DM", fdf.parent / "stdout.txt"
    dm.write_bytes(b"verified-dm")
    stdout.write_text(_soc_stdout(), encoding="utf-8")
    requested = magnetic_spin_from_fdf(fdf)
    assert requested is not None
    observed = parse_spin_orbit_magnetic_output(_soc_stdout().splitlines(True), scf_converged=True, required_atom_count=2)
    assert observed.spin_mode == "spin-orbit" and observed.canonical()["quantity"]["name"] == "mulliken_spin_population"
    with pytest.raises(ValueError, match="truncated"):
        parse_spin_orbit_magnetic_output(_soc_stdout().splitlines(True)[:-1], scf_converged=True)
    with pytest.raises(ValueError, match="unambiguous"):
        parse_spin_orbit_magnetic_output(_soc_stdout().replace("spin-orbit", "non-collinear").splitlines(True), scf_converged=True)
    real = parse_spin_orbit_magnetic_output(_real_soc_542_dialect().splitlines(True), scf_converged=True, required_atom_count=1)
    assert real.atomic_vectors == ((1, 3.997496, -0.0, 0.0, 3.997496),)
    with pytest.raises(ValueError, match="8 SOC"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().replace("= 8", "= 4").splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="runtime evidence"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().replace("There are spin-orbit semi-local pseudopotentials available\n", "").replace("siesta: Enl(+so)", "siesta: energy" ).splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="unambiguous"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().replace("redata: Spin configuration                          = spin-orbit+offsite\n", "").splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="8 SOC"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().replace("redata: Number of spin components                   = 8\n", "").splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="truncated"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().splitlines(True)[:-1], scf_converged=True)
    with pytest.raises(ValueError, match="header"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().replace("Sx [e]", "Sx" ).splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="complete"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().splitlines(True), scf_converged=True, required_atom_count=2)
    duplicate = _real_soc_542_dialect().replace("-------------------------------------------------------------------------------\n", "     1     0.000000   16.000000    3.997496   -0.000000    0.000000    3.997496  Fe\n-------------------------------------------------------------------------------\n")
    with pytest.raises(ValueError, match="duplicate"):
        parse_spin_orbit_magnetic_output(duplicate.splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="malformed"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().replace("3.997496", "NaN", 1).splitlines(True), scf_converged=True)
    with pytest.raises(ValueError, match="inconsistent"):
        parse_spin_orbit_magnetic_output(_real_soc_542_dialect().replace("3.997496", "2.997496", 1).splitlines(True), scf_converged=True)
    conflict = _real_soc_542_dialect() + " Total     0.000000                2.997496    0.000000    0.000000    2.997496\n"
    with pytest.raises(ValueError, match="conflicting"):
        parse_spin_orbit_magnetic_output(conflict.splitlines(True), scf_converged=True)
    artifact = magnetic_artifact_envelope(
        parent_scientific_identity_sha256=build_scientific_identity(fdf).fingerprint,
        requested=requested, observed=observed, final_fdf=fdf, stdout=stdout,
        scf_converged=True, siesta_version="5.4.2", stdout_relative_path="stdout.txt",
        soc_pseudo_evidence=soc_pseudopotential_evidence(fdf),
    )
    assert artifact["payload"]["soc"]["enabled"] is True
    assert artifact["payload"]["soc"]["implementation"] == "full"
    assert artifact["payload"]["soc"]["pseudopotentials"]["Fe"]["compatibility"] == "FULLY_RELATIVISTIC"
    magnetic_path = fdf.parent / "magnetic-state.json"
    magnetic_path.write_text(json.dumps(artifact), encoding="utf-8")
    state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={
        "schema_version": "1.0", "artifact_id": "electronic-state", "artifact_type": "qraft.electronic-state", "authority": "PROVISIONAL", "engine": "siesta",
        "final_scf": {"input_fdf_sha256": _sha(fdf), "scientific_identity_sha256": build_scientific_identity(fdf).fingerprint, "system_label": "soc", "density_matrix": {"filename": dm.name, "sha256": _sha(dm)}, "spin_mode": "spin-orbit", "magnetic": {"spin_mode": "spin-orbit", "requested": requested.canonical(), "observed": observed.canonical(), "artifact": {"artifact_type": "qraft.magnetic-state", "relative_path": magnetic_path.name, "sha256": _sha(magnetic_path), "content_sha256": artifact["content_sha256"]}}},
    }).to_dict()
    state_path = fdf.parent / "electronic-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm).spin_mode == "spin-orbit"

    state_payload = json.loads(json.dumps(state))["payload"]

    def write_state_reference(magnetic_document: dict[str, object], *, content_sha256: str | None = None) -> None:
        payload = json.loads(json.dumps(state_payload))
        artifact_reference = payload["final_scf"]["magnetic"]["artifact"]
        artifact_reference["sha256"] = _sha(magnetic_path)
        artifact_reference["content_sha256"] = content_sha256 or magnetic_document["content_sha256"]
        state_path.write_text(json.dumps(ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload=payload).to_dict()), encoding="utf-8")

    def write_magnetic_payload(payload: dict[str, object]) -> dict[str, object]:
        document = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="qraft.siesta-magnetism", payload=payload).to_dict()
        magnetic_path.write_text(json.dumps(document), encoding="utf-8")
        write_state_reference(document)
        return document

    # Each case operates on a local copy of the test evidence.  M7 must reject
    # byte corruption, envelope/reference hash corruption, stdout corruption,
    # wrong parent identity, and wrong spin mode before property preparation.
    magnetic_path.write_bytes(b"corrupt magnetic artifact bytes")
    with pytest.raises(ValueError, match="artifact file SHA-256 mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    magnetic_path.write_text(json.dumps(artifact), encoding="utf-8")
    write_state_reference(artifact, content_sha256="0" * 64)
    with pytest.raises(ValueError, match="artifact content SHA-256 mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    write_state_reference(artifact)
    stdout.write_text("corrupt stdout evidence\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stdout SHA-256 mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    stdout.write_text(_soc_stdout(), encoding="utf-8")
    wrong_parent = json.loads(json.dumps(artifact["payload"]))
    wrong_parent["parent_scientific_identity_sha256"] = "0" * 64
    write_magnetic_payload(wrong_parent)
    with pytest.raises(ValueError, match="identity mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    wrong_mode = json.loads(json.dumps(artifact["payload"]))
    wrong_mode["observed"]["spin_mode"] = "non-collinear"
    write_magnetic_payload(wrong_mode)
    with pytest.raises(ValueError, match="observed state is invalid"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    magnetic_path.write_text(json.dumps(artifact), encoding="utf-8")
    write_state_reference(artifact)
    pseudo = fdf.parent / "Fe.psml"
    pseudo.write_text(_psml() + "<!-- tampered -->\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pseudopotential SHA-256 mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)


def test_soc_parent_leaves_m71_time_reversal_auto_unresolved(tmp_path: Path) -> None:
    fdf = _render(tmp_path, "soc", SpinOrbitSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0),)))
    assert time_reversal_evidence_from_final_fdf(fdf) is None


def test_unexecuted_real_soc_fixtures_use_only_canonical_input() -> None:
    fixtures = Path(__file__).parents[2] / "docs" / "validation" / "m8_c_full_soc_real_siesta_fixtures"
    z = magnetic_spin_from_fdf(fixtures / "fe_atom_soc_z.fdf")
    x = magnetic_spin_from_fdf(fixtures / "fe_atom_soc_x.fdf")
    assert z is not None and z.canonical()["initialization"]["moments"][0]["direction"] == "explicit"
    assert x is not None and x.canonical()["initialization"]["moments"][0]["theta_deg"] == "90.0"


def test_soc_does_not_add_an_ion_reuse_channel(tmp_path: Path) -> None:
    fdf = _render(tmp_path, "ion", SpinOrbitSpec((NonCollinearSpinMoment(1, "+", 90.0, 0.0),)))
    (fdf.parent / "soc.ion").write_text("untrusted prior-ion bytes\n", encoding="utf-8")
    closure = resolve_scientific_input_closure(fdf)
    assert all(not entry.destination.casefold().endswith(".ion") for entry in closure.entries)
