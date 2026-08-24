from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.band_paths import time_reversal_evidence_from_final_fdf
from qraft.engines.siesta.ground_state import validate_final_scf
from qraft.engines.siesta.magnetism import (
    collinear_spin_from_fdf,
    magnetic_artifact_envelope,
    materialize_collinear_spin_fdf,
    parse_collinear_magnetic_output,
)
from qraft.magnetism import CollinearSpinMoment, CollinearSpinSpec
from qraft.protocols.electronic_properties import ElectronicStateSource
from qraft.protocols.single_fdf import build_fdf_plan, build_scientific_identity


BASE = """SystemName magnetic fixture
SystemLabel magnetic
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


def _render(root: Path, name: str, spec: CollinearSpinSpec) -> Path:
    source = _base(root / "source")
    rendered = materialize_collinear_spin_fdf(source, root / name, spec, primary_destination="input.fdf")
    (root / name / "Fe.psf").write_text("pseudo", encoding="utf-8")
    return rendered.root_fdf


def test_collinear_identity_distinguishes_fm_afm_numeric_and_initialization(tmp_path: Path) -> None:
    fm = _render(tmp_path, "fm", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "+"))))
    afm = _render(tmp_path, "afm", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))))
    numeric = _render(tmp_path, "numeric", CollinearSpinSpec((CollinearSpinMoment(1, 4.0), CollinearSpinMoment(2, -4.0))))
    absent = _render(tmp_path, "absent", CollinearSpinSpec())
    empty = _render(tmp_path, "empty", CollinearSpinSpec(()))
    identities = [build_scientific_identity(path).fingerprint for path in (fm, afm, numeric, absent, empty)]
    assert len(set(identities)) == 5
    assert "%block DM.InitSpin" not in absent.read_text(encoding="utf-8")
    assert "%block DM.InitSpin\n\n%endblock DM.InitSpin" in empty.read_text(encoding="utf-8")


def test_legacy_m6_identity_regression_is_preserved(tmp_path: Path) -> None:
    """Regression fixture with no M8-A labels: the historical M6 hash is fixed."""

    assert build_scientific_identity(_base(tmp_path / "legacy-hash")).fingerprint == "8e8723a8216fd0f0f6dfb0cbf61ee1da3f7381162878b85431255ef380785522"


def test_collinear_renderer_is_exact_and_validates_indices_and_moments(tmp_path: Path) -> None:
    fdf = _render(tmp_path, "fixed", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, 0.0)), True, 2.0))
    text = fdf.read_text(encoding="utf-8")
    assert "Spin polarized" in text
    assert "  1 +" in text and "  2 0.0" in text
    assert "Spin.Fix true" in text and "Spin.Total 2.0" in text
    assert "Charge.Mulliken end" in text
    parsed = collinear_spin_from_fdf(fdf)
    assert parsed is not None and parsed.canonical()["initialization"]["kind"] == "explicit"
    with pytest.raises(ValueError, match="unique"):
        CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(1, "-")))
    with pytest.raises(ValueError, match="positive"):
        CollinearSpinMoment(0, "+")
    with pytest.raises(ValueError, match="exceeds"):
        materialize_collinear_spin_fdf(_base(tmp_path / "range"), tmp_path / "range-out", CollinearSpinSpec((CollinearSpinMoment(3, "+"),)))
    with pytest.raises(ValueError, match="finite"):
        CollinearSpinMoment(1, float("nan"))
    with pytest.raises(ValueError, match="token"):
        CollinearSpinMoment(1, "up")
    with pytest.raises(ValueError, match="requires Spin.Fix"):
        CollinearSpinSpec(total_spin=1.0)
    fixed_only = _render(tmp_path, "fixed-only", CollinearSpinSpec(fix_total_spin=True))
    assert "Spin.Fix true" in fixed_only.read_text(encoding="utf-8") and "Spin.Total" not in fixed_only.read_text(encoding="utf-8")
    first = build_fdf_plan(fdf, overrides={"partition": "local", "launcher": "direct", "executable": "siesta", "mpi_ranks": 1})
    second = build_fdf_plan(fdf, overrides={"partition": "remote", "launcher": "openmpi", "executable": "siesta", "nodes": 2, "mpi_ranks": 8})
    assert first["scientific_identity"]["fingerprint"] == second["scientific_identity"]["fingerprint"]


def test_collinear_rejects_parent_conflicts_and_out_of_scope_directives(tmp_path: Path) -> None:
    parent = _base(tmp_path / "conflict")
    parent.write_text(BASE + "Spin non-colinear\n", encoding="utf-8")
    # M8-B permits the global final-SCF validator to accept non-collinear
    # input, while the M8-A-only adapter must still refuse to reinterpret it.
    with pytest.raises(ValueError, match="only Spin polarized"):
        collinear_spin_from_fdf(parent)
    soc = _base(tmp_path / "soc")
    soc.write_text(BASE + "Spin polarized\nSpin.Orbit true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="out-of-scope"):
        validate_final_scf(soc)
    total_without_fix = _base(tmp_path / "total")
    total_without_fix.write_text(BASE + "Spin polarized\nSpin.Total 2.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requires Spin.Fix"):
        validate_final_scf(total_without_fix)
    conflicting = _base(tmp_path / "different")
    conflicting.write_text(BASE + "Spin polarized\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflict"):
        materialize_collinear_spin_fdf(conflicting, tmp_path / "different-out", CollinearSpinSpec((CollinearSpinMoment(1, "+"),)))
    mulliken = _base(tmp_path / "mulliken")
    mulliken.write_text(BASE + "Charge.Mulliken all\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Charge.Mulliken end"):
        materialize_collinear_spin_fdf(mulliken, tmp_path / "mulliken-out", CollinearSpinSpec((CollinearSpinMoment(1, "+"),)))
    with pytest.raises(ValueError, match="does not support"):
        CollinearSpinSpec.from_mapping({"theta": 0.0})


def test_magnetic_parser_is_fail_closed_and_artifact_separates_request_from_observation(tmp_path: Path) -> None:
    stdout = tmp_path / "magnetic.out"
    stdout.write_text(
        "Version : 5.4.2\n"
        "redata: Spin configuration = collinear\n"
        "redata: Number of spin components = 2\n"
        "Mulliken Atomic Populations:\n"
        "Atom # charge [q] valence [e] Sz [e] Species\n"
        "  1 0.0 8.0 2.10 Fe\n"
        "  2 0.0 8.0 -2.10 Fe\n"
        " Total 0.0 0.0\n",
        encoding="utf-8",
    )
    observed = parse_collinear_magnetic_output(stdout.read_text(encoding="utf-8").splitlines(True), scf_converged=True)
    assert observed.spin_mode == "polarized" and observed.atomic_moments == ((1, 2.1), (2, -2.1)) and observed.total_moment == 0.0
    with pytest.raises(ValueError, match="truncated"):
        parse_collinear_magnetic_output(("redata: Spin configuration = collinear\n", "redata: Number of spin components = 2\n", "Mulliken Atomic Populations:\n", "  1 0.0 8.0 2.10 Fe\n"), scf_converged=True)
    with pytest.raises(ValueError, match="complete Mulliken"):
        parse_collinear_magnetic_output(stdout.read_text(encoding="utf-8").splitlines(True), scf_converged=True, required_atom_count=3)
    fdf = _render(tmp_path, "artifact", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))))
    artifact = magnetic_artifact_envelope(parent_scientific_identity_sha256=build_scientific_identity(fdf).fingerprint, requested=CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))), observed=observed, final_fdf=fdf, stdout=stdout, scf_converged=True, siesta_version="5.4.2")
    payload = artifact["payload"]
    assert payload["requested"]["initialization"]["moments"][0]["moment"] == "+"
    assert payload["observed"]["atomic_moments"][0]["moment"] == "2.1"


def test_m8a_rejects_out_of_scope_soc_and_hubbard_directives(tmp_path: Path) -> None:
    for name, directive in (("soc", "SpinOrbit true"), ("hubbard", "DFTU.EnergyShift 0.1 eV")):
        fdf = tmp_path / f"{name}.fdf"
        fdf.write_text(BASE + "Spin polarized\n" + directive + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="out-of-scope magnetic directive"):
            collinear_spin_from_fdf(fdf)


def test_m6_magnetic_electronic_state_and_m71_time_reversal_are_conservative(tmp_path: Path) -> None:
    assert collinear_spin_from_fdf(_base(tmp_path / "legacy")) is None
    fdf = _render(tmp_path, "m6", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))))
    dm = tmp_path / "m6" / "magnetic.DM"; dm.write_bytes(b"verified-dm")
    stdout = tmp_path / "m6" / "stdout.txt"; stdout.write_text("redata: Spin configuration = polarized\nredata: Number of spin components = 2\nMulliken Atomic Populations:\n  1 Total 8.0 2.0\n  2 Total 8.0 -2.0\n Total 16.0 0.0\n", encoding="utf-8")
    observed = parse_collinear_magnetic_output(stdout.read_text(encoding="utf-8").splitlines(True), scf_converged=True)
    requested = collinear_spin_from_fdf(fdf); assert requested is not None
    magnetic = magnetic_artifact_envelope(parent_scientific_identity_sha256=build_scientific_identity(fdf).fingerprint, requested=requested, observed=observed, final_fdf=fdf, stdout=stdout, scf_converged=True, siesta_version="5.4.2", stdout_relative_path="stdout.txt")
    magnetic_path = tmp_path / "m6" / "magnetic-state.json"; magnetic_path.write_text(json.dumps(magnetic), encoding="utf-8")
    state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={
        "schema_version": "1.0", "artifact_id": "electronic-state", "artifact_type": "qraft.electronic-state", "authority": "PROVISIONAL", "engine": "siesta",
        "final_scf": {"input_fdf_sha256": _sha(fdf), "scientific_identity_sha256": build_scientific_identity(fdf).fingerprint, "system_label": "magnetic", "density_matrix": {"filename": dm.name, "sha256": _sha(dm)}, "spin_mode": "polarized", "magnetic": {"spin_mode": "polarized", "requested": requested.canonical(), "observed": observed.canonical(), "artifact": {"artifact_type": "qraft.magnetic-state", "relative_path": magnetic_path.name, "sha256": _sha(magnetic_path), "content_sha256": magnetic["content_sha256"]}}},
    }).to_dict()
    state_path = tmp_path / "m6" / "electronic-state.json"; state_path.write_text(json.dumps(state), encoding="utf-8")
    source = ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    assert source.spin_mode == "polarized" and source.magnetic_state_content_sha256 == magnetic["content_sha256"]
    assert source.magnetic_state_file_sha256 == _sha(magnetic_path)
    magnetic_path.write_text(json.dumps({**magnetic, "content_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact file SHA-256 mismatch"):
        ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    assert time_reversal_evidence_from_final_fdf(fdf) is None
    assert build_scientific_identity(fdf).fingerprint == build_scientific_identity(fdf).fingerprint
