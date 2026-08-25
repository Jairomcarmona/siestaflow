from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.engines.siesta.magnetism import magnetic_artifact_envelope, parse_collinear_magnetic_output
from qraft.engines.siesta.output_parser import final_scf_energy_artifact_envelope, parse_final_scf_energy_evidence
from qraft.magnetism import CollinearSpinMoment, CollinearSpinSpec
from qraft.protocols.electronic_properties import ElectronicStateSource
from qraft.protocols.magnetic_selection import MagneticCandidate, MagneticSelectionProtocol
from qraft.protocols.single_fdf import build_scientific_identity


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stdout(energy: float = -20.0) -> str:
    return (
        "Siesta started\nSCF cycle 4\nSCF cycle converged after 4 iterations\n"
        "redata: Spin configuration = polarized\nredata: Number of spin components = 2\n"
        "Mulliken Atomic Populations:\n  1 Total 8.0 2.0\n  2 Total 8.0 -2.0\n Total 16.0 0.0\n"
        f"Using DM_out to compute the final energy and forces\nsiesta: Final energy (eV):\nsiesta: Total = {energy:.6f}\nJob completed\n"
    )


def _fdf(label: str, spin: CollinearSpinSpec, *, mesh: int = 150) -> str:
    init = "" if spin.initial_moments is None else "%block DM.InitSpin\n" + "".join(f" {item.atom_index} {item.rendered}\n" for item in spin.initial_moments) + "%endblock DM.InitSpin\n"
    return f"""SystemName {label}
SystemLabel {label}
NumberOfAtoms 2
NumberOfSpecies 1
XC.Functional LDA
XC.Authors CA
PAO.BasisSize DZ
Mesh.Cutoff {mesh} Ry
Spin polarized
{init}%block ChemicalSpeciesLabel
1 26 Fe
%endblock ChemicalSpeciesLabel
LatticeConstant 1 Ang
%block LatticeVectors
3 0 0
0 3 0
0 0 3
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
1.5 1.5 1.5 1
%endblock AtomicCoordinatesAndAtomicSpecies
%block kgrid.MonkhorstPack
3 0 0 0.0
0 3 0 0.0
0 0 3 0.0
%endblock kgrid.MonkhorstPack
"""


def _candidate(root: Path, candidate_id: str, spin: CollinearSpinSpec, energy: float, *, mesh: int = 150, pseudo: bytes = b"Fe pseudo") -> MagneticCandidate:
    root.mkdir(parents=True, exist_ok=True)
    fdf = root / "final.fdf"; fdf.write_text(_fdf(candidate_id, spin, mesh=mesh), encoding="utf-8")
    (root / "Fe.psf").write_bytes(pseudo)
    dm = root / f"{candidate_id}.DM"; dm.write_bytes(b"verified-dm")
    stdout = root / "stdout.txt"; stdout.write_text(_stdout(energy), encoding="utf-8")
    observed = parse_collinear_magnetic_output(_stdout(energy).splitlines(True), scf_converged=True, required_atom_count=2)
    artifact = magnetic_artifact_envelope(
        parent_scientific_identity_sha256=build_scientific_identity(fdf).fingerprint,
        requested=spin, observed=observed, final_fdf=fdf, stdout=stdout,
        scf_converged=True, siesta_version="5.4.2", stdout_relative_path="stdout.txt",
    )
    magnetic_path = root / "magnetic-state.json"; magnetic_path.write_text(json.dumps(artifact), encoding="utf-8")
    energy_evidence = parse_final_scf_energy_evidence(stdout).to_dict()
    energy_evidence["source_final_fdf_sha256"] = _sha(fdf)
    state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={
        "schema_version": "1.0", "artifact_id": "electronic-state", "artifact_type": "qraft.electronic-state", "authority": "PROVISIONAL", "engine": "siesta",
        "final_scf": {"input_fdf_sha256": _sha(fdf), "scientific_identity_sha256": build_scientific_identity(fdf).fingerprint, "system_label": candidate_id, "scf_converged": True, "density_matrix": {"filename": dm.name, "sha256": _sha(dm)}, "spin_mode": "polarized", "final_energy": energy_evidence, "magnetic": {"spin_mode": "polarized", "requested": spin.canonical(), "observed": observed.canonical(), "artifact": {"artifact_type": "qraft.magnetic-state", "relative_path": magnetic_path.name, "sha256": _sha(magnetic_path), "content_sha256": artifact["content_sha256"]}}},
    }).to_dict()
    state_path = root / "electronic-state.json"; state_path.write_text(json.dumps(state), encoding="utf-8")
    source = ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)
    return MagneticCandidate.from_source(candidate_id, source)


def _historic_candidate(candidate: MagneticCandidate) -> MagneticCandidate:
    raw = json.loads(candidate.state_path.read_text(encoding="utf-8"))
    payload = raw["payload"]
    energy = payload["final_scf"].pop("final_energy")
    candidate.state_path.write_text(json.dumps(ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload=payload).to_dict()), encoding="utf-8")
    source = ElectronicStateSource.load(candidate.state_path, final_fdf=candidate.final_fdf, density_matrix=candidate.density_matrix)
    artifact = final_scf_energy_artifact_envelope(
        evidence=parse_final_scf_energy_evidence(candidate.state_path.parent / "stdout.txt"),
        final_fdf_sha256=source.final_fdf_sha256,
        electronic_state_file_sha256=source.state_file_sha256,
        electronic_state_content_sha256=source.state_content_sha256,
        magnetic_state_file_sha256=source.magnetic_state_file_sha256 or "",
        magnetic_state_content_sha256=source.magnetic_state_content_sha256 or "",
        scientific_identity_sha256=source.parent_scientific_identity_sha256,
    )
    path = candidate.state_path.parent / "final-energy.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return MagneticCandidate.from_source(candidate.candidate_id, source, final_energy_artifact_path=path)


def test_native_final_energy_parser_rejects_intermediate_missing_ambiguous_and_truncated(tmp_path: Path) -> None:
    stdout = tmp_path / "native.out"; stdout.write_text(_stdout(), encoding="utf-8")
    evidence = parse_final_scf_energy_evidence(stdout)
    assert evidence.value_ev == -20.0 and evidence.to_dict()["quantity"] == "siesta.final_total_energy"
    for name, content in {
        "no-convergence": _stdout().replace("SCF cycle converged after 4 iterations", "SCF not converged"),
        "no-final": _stdout().replace("siesta: Final energy (eV):\nsiesta: Total = -20.000000\n", ""),
        "ambiguous": _stdout().replace("siesta: Total = -20.000000", "siesta: Total = -20.000000\nsiesta: Total = -19.000000"),
        "truncated": _stdout().replace("Job completed", ""),
    }.items():
        path = tmp_path / f"{name}.out"; path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            parse_final_scf_energy_evidence(path)


def test_m8d_selection_is_deterministic_unique_and_immutable(tmp_path: Path) -> None:
    fm = _candidate(tmp_path / "fm", "FM", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "+"))), -20.0)
    afm = _candidate(tmp_path / "afm", "AFM1", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))), -19.8)
    afm2 = _candidate(tmp_path / "afm2", "AFM2", CollinearSpinSpec((CollinearSpinMoment(1, 2.0), CollinearSpinMoment(2, -2.0))), -19.6)
    selector = MagneticSelectionProtocol()
    first = selector.compare((fm, afm, afm2), energy_tolerance_ev_per_atom=0.01)
    second = selector.compare((afm2, afm, fm), energy_tolerance_ev_per_atom=0.01)
    assert first["selection_status"] == "SELECTED"
    assert fm.scientific_identity_sha256 != afm.scientific_identity_sha256
    assert first["selected_state_reference"]["candidate_id"] == "FM"
    assert first["selection_sha256"] == second["selection_sha256"]
    ranks = {item["candidate_id"]: item["rank"] for item in first["candidates"]}
    assert ranks == {"FM": 1, "AFM1": 2, "AFM2": 3}
    assert first["comparison_policy"]["partial_candidates"] == "FORBIDDEN"
    document = selector.write(tmp_path / "selection.json", first)
    assert document["payload"]["selection"]["selected_state"]["candidate_id"] == "FM"
    with pytest.raises(ValueError, match="immutable"):
        selector.write(tmp_path / "selection.json", second | {"reason": "tampered"})


def test_m8d_requires_complete_comparable_non_tied_hash_bound_evidence(tmp_path: Path) -> None:
    fm = _candidate(tmp_path / "fm", "FM", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "+"))), -20.0)
    afm = _candidate(tmp_path / "afm", "AFM", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))), -19.99)
    selector = MagneticSelectionProtocol()
    tied = selector.compare((fm, afm), energy_tolerance_ev_per_atom=0.01)
    assert tied["selection_status"] == "REVIEW_REQUIRED"
    assert any(item["selection_status"] == "DEGENERATE" for item in tied["candidates"])
    missing = _historic_candidate(afm)
    missing = replace(missing, final_energy_artifact_path=None, final_energy_artifact_file_sha256=None, final_energy_artifact_content_sha256=None)
    assert selector.compare((fm, missing), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "REVIEW_REQUIRED"
    for field in ("state_file_sha256", "state_content_sha256", "magnetic_state_file_sha256", "magnetic_state_content_sha256", "scientific_identity_sha256"):
        corrupted = replace(afm, **{field: "0" * 64})
        assert selector.compare((fm, corrupted), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "REVIEW_REQUIRED"
    historic = _historic_candidate(_candidate(tmp_path / "historic", "HIST", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))), -19.8))
    assert selector.compare((fm, historic), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "SELECTED"
    assert selector.compare((fm, replace(historic, final_energy_artifact_file_sha256="0" * 64)), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "REVIEW_REQUIRED"
    assert selector.compare((fm, replace(historic, final_energy_artifact_content_sha256="0" * 64)), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "REVIEW_REQUIRED"
    assert historic.final_energy_artifact_path is not None
    corrupt_energy = json.loads(historic.final_energy_artifact_path.read_text(encoding="utf-8"))
    corrupt_energy["payload"]["energy"]["source_stdout_sha256"] = "0" * 64
    historic.final_energy_artifact_path.write_text(json.dumps(corrupt_energy), encoding="utf-8")
    assert selector.compare((fm, historic), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "REVIEW_REQUIRED"
    pseudo = _candidate(tmp_path / "pseudo", "PSEUDO", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))), -19.8, pseudo=b"different")
    numerical = _candidate(tmp_path / "numerical", "NUM", CollinearSpinSpec((CollinearSpinMoment(1, "+"), CollinearSpinMoment(2, "-"))), -19.8, mesh=200)
    assert selector.compare((fm, pseudo), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "REVIEW_REQUIRED"
    assert selector.compare((fm, numerical), energy_tolerance_ev_per_atom=0.001)["selection_status"] == "REVIEW_REQUIRED"
