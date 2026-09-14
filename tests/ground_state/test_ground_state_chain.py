from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from qraft.campaign_spec import CampaignSpec
from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.contracts.scientific import NumericalProfileReference, ScientificArtifactReference, ScientificAuthority
from qraft.engines.siesta.ground_state import render_geometry, validate_final_scf
from qraft.engines.siesta.relaxation import geometry_envelope
from qraft.protocols.ground_state import GroundStateProtocol
from qraft.protocols.single_fdf import build_scientific_identity


BASE = """SystemName ground
SystemLabel ground
NumberOfAtoms 1
NumberOfSpecies 1
PAO.EnergyShift 50 meV
Mesh.Cutoff 100 Ry
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
LatticeConstant 1 Ang
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
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _campaigns(root: Path) -> tuple[CampaignSpec, CampaignSpec, CampaignSpec]:
    (root / "system.fdf").write_text(BASE, encoding="utf-8")
    (root / "C.psf").write_text("pseudo\n", encoding="utf-8")
    common = {"schema_version": "1.0", "engine": "siesta", "protocol": "convergence", "system": {"fdf": "system.fdf"}, "criterion": {"metric": "energy_per_atom", "delta": 0.01, "unit": "eV", "consecutive": 1}}
    def make(name: str, parameters: dict) -> CampaignSpec:
        return CampaignSpec.from_mapping({**common, "campaign_id": name, "parameters": parameters}, source=root / f"{name}.yaml")
    return (make("basis", {"basis_energy_shift": {"mode": "scan", "values": [200, 300], "unit": "meV"}}), make("mesh", {"mesh_cutoff": {"mode": "scan", "values": [300, 350], "unit": "Ry"}}), make("kpoints", {"kpoints": {"mode": "scan", "grids": [[3, 3, 2], [4, 4, 2]]}}))


class _Convergence:
    def __init__(self, *, tamper: bool = False) -> None:
        self.tamper = tamper

    def run(self, *_args: object, runs_root: Path, **_kwargs: object) -> dict:
        selections = {"basis_energy_shift": {"value": 300, "unit": "meV", "selection_artifact_sha256": "a" * 64, "selection_contract_sha256": "b" * 64}, "mesh_cutoff": {"value": 350, "unit": "Ry", "selection_artifact_sha256": "c" * 64, "selection_contract_sha256": "d" * 64}, "kpoints": {"value": [4, 4, 2], "unit": None, "selection_artifact_sha256": "e" * 64, "selection_contract_sha256": "f" * 64}}
        raw = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={"schema_version": "1.0", "artifact_id": "f03-numerical-profile", "artifact_type": "siestaflow.numerical-profile", "authority": "PROVISIONAL", "selections": selections}).to_dict()
        path = runs_root / "numerical-profile.json"; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(raw, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        digest = _sha(path)
        if self.tamper:
            alternate = dict(raw); alternate["payload"] = dict(raw["payload"]); alternate["payload"]["selections"] = dict(selections); alternate["payload"]["selections"]["mesh_cutoff"] = {**selections["mesh_cutoff"], "value": 400}; alternate = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload=alternate["payload"]).to_dict(); path.write_text(json.dumps(alternate, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return {"status": "COMPLETED", "numerical_profile": str(path), "numerical_profile_sha256": digest, "profile_reference": NumericalProfileReference("f03-numerical-profile", raw["content_sha256"], ScientificAuthority.PROVISIONAL)}


class _Relaxation:
    def __init__(self, *, tamper: bool = False) -> None:
        self.calls = 0; self.tamper = tamper

    def run(self, _fdf: Path, *, runs_root: Path, **_kwargs: object) -> dict:
        self.calls += 1
        path = runs_root / "work" / "relax" / "attempt-0001" / "relaxed-geometry.json"; path.parent.mkdir(parents=True, exist_ok=True)
        raw = geometry_envelope(artifact_id="relaxed-geometry", geometry={"cell": [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]], "atoms": [{"index": 1, "species_index": 1, "coordinates": [1.0, 2.0, 3.0]}]}, provenance={"force_ev_per_ang": 0.01})
        path.write_text(json.dumps(raw, sort_keys=True, indent=2) + "\n", encoding="utf-8"); digest = _sha(path)
        if self.tamper:
            changed = geometry_envelope(artifact_id="relaxed-geometry", geometry={"cell": [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]], "atoms": [{"index": 1, "species_index": 1, "coordinates": [9.0, 9.0, 9.0]}]}, provenance={"force_ev_per_ang": 0.01}); path.write_text(json.dumps(changed, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return {"technical_validation": "PASS", "scientific_decision": "CONVERGED", "attempt": {"attempt_id": "attempt-0001"}, "geometry_reference": ScientificArtifactReference("relaxed-geometry", "qraft.geometry", digest, raw["content_sha256"], ScientificAuthority.PROVISIONAL)}


def _templates(root: Path) -> tuple[Path, Path]:
    relax = root / "relax.fdf"; relax.write_text(BASE + "MD.TypeOfRun CG\nMD.Steps 2\nMD.MaxForceTol 0.05 eV/Ang\nMD.VariableCell F\n", encoding="utf-8")
    final = root / "final.fdf"; final.write_text(BASE + "MD.Steps 0\nMD.VariableCell .false.\nHarris.Functional false\nUseStructFile no\n", encoding="utf-8")
    return relax, final


def _overrides(root: Path, *, dm: bool = True, converged: bool = True, magnetic: bool = False, noncollinear: bool = False, final_energy: bool = False) -> dict:
    script = root / "final_fake.py"
    script.write_text(
        "from pathlib import Path\nimport sys\ntext=Path('input.fdf').read_text()\n"
        "assert '1 2 3 1' in text and 'PAO.EnergyShift 300 meV' in text and 'Mesh.Cutoff 350 Ry' in text\n"
        + ("Path('ground.DM').write_bytes(b'dm')\n" if dm else "")
        + "print('Siesta started')\nprint('SCF cycle 1')\n"
        + (
            "print('redata: Spin configuration = non-collinear')\nprint('redata: Number of spin components = 4')\nprint('Mulliken Atomic Populations:')\nprint('Atom # charge [q] valence [e] S [e] Sx [e] Sy [e] Sz [e] Species')\nprint('  1 0.0 4.0 2.0 2.0 0.0 0.0 C')\nprint(' Total 0.0 4.0 2.0 2.0 0.0 0.0')\n"
            if noncollinear else "print('redata: Spin configuration = polarized')\nprint('redata: Number of spin components = 2')\nprint('Mulliken Atomic Populations:')\nprint('  1 Total 4.0 2.0')\nprint(' Total 4.0 2.0')\n" if magnetic else ""
        )
        + ("print('SCF converged')\n" if converged else "print('SCF not converged')\n")
        + ("print('Using DM_out to compute the final energy and forces')\nprint('siesta: Final energy (eV):')\nprint('siesta: Total = -12.500000')\n" if final_energy else "")
        + "print('Job completed')\n",
        encoding="utf-8",
    )
    return {"partition": "local", "launcher": "direct", "executable": sys.executable, "executable_arguments": [str(script)]}


def test_render_geometry_and_static_final_scf_validation(tmp_path: Path) -> None:
    final = _templates(tmp_path)[1]
    rendered = render_geometry(final.read_text(encoding="utf-8"), {"cell": [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]], "atoms": [{"index": 1, "species_index": 1, "coordinates": [1.0, 2.0, 3.0]}]})
    path = tmp_path / "rendered.fdf"; path.write_text(rendered, encoding="utf-8")
    validate_final_scf(path)
    assert "AtomicCoordinatesFormat Ang" in rendered and "1 2 3 1" in rendered
    assert "10 0.0 0.0" in rendered
    path.write_text(rendered.replace("MD.Steps 0", "MD.Steps 1"), encoding="utf-8")
    with pytest.raises(ValueError, match="MD.Steps"):
        validate_final_scf(path)
    for label in ("MD.VariableCell true", "Harris.Functional yes", "UseStructFile .true.", "Harris.Functional maybe"):
        name = label.split()[0]
        candidate = rendered.replace("MD.VariableCell .false.", label) if name == "MD.VariableCell" else rendered.replace(f"{name} false" if name == "Harris.Functional" else f"{name} no", label)
        path.write_text(candidate, encoding="utf-8")
        with pytest.raises(ValueError):
            validate_final_scf(path)


def test_final_scf_rejects_effective_included_static_hazards(tmp_path: Path) -> None:
    root = tmp_path / "effective"; root.mkdir()
    template = root / "final.fdf"
    template.write_text("%include defaults.fdf\nMD.Steps 0\n", encoding="utf-8")
    (root / "defaults.fdf").write_text(BASE + "MD.Steps 4\nMD.VariableCell false\nHarris.Functional false\nUseStructFile false\n", encoding="utf-8")
    with pytest.raises(ValueError, match="MD.Steps"):
        validate_final_scf(template)
    (root / "defaults.fdf").write_text((root / "defaults.fdf").read_text(encoding="utf-8").replace("MD.Steps 4", "MD.Steps 0").replace("UseStructFile false", "UseStructFile .true."), encoding="utf-8")
    with pytest.raises(ValueError, match="UseStructFile"):
        validate_final_scf(template)


def test_ground_state_final_scf_artifact_reuse_and_blocking(tmp_path: Path) -> None:
    basis, mesh, kpoints = _campaigns(tmp_path); relax, final = _templates(tmp_path)
    convergence = _Convergence(); relaxation = _Relaxation()
    protocol = GroundStateProtocol(convergence=convergence, relaxation=relaxation)
    root = tmp_path / "runs"
    first = protocol.run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=root, overrides=_overrides(tmp_path))
    assert first["status"] == "COMPLETED" and first["final_scf"]["scf_started"] and first["final_scf"]["scf_converged"]
    relaxation_input = (root / "handoff" / "relaxation" / "input.fdf").read_text(encoding="utf-8")
    final_input = root / "handoff" / "final-scf" / "input.fdf"
    assert "PAO.EnergyShift 300 meV" in relaxation_input and "Mesh.Cutoff 350 Ry" in relaxation_input
    assert build_scientific_identity(final_input).geometry_sha256 != build_scientific_identity(final).geometry_sha256
    state = Path(first["electronic_state"]); envelope = ContractEnvelope.from_dict(json.loads(state.read_text(encoding="utf-8")), required_contract=SCIENTIFIC_ARTIFACT)
    assert envelope.payload["artifact_type"] == "qraft.electronic-state" and envelope.payload["final_scf"]["density_matrix"]["sha256"]
    assert first["electronic_state_reference"].sha256 == _sha(state)
    second = protocol.run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=root, overrides=_overrides(tmp_path))
    assert second["final_scf"]["reused"] and not (root / "stages" / "final-scf" / "work" / "final-scf" / "attempt-0002").exists()
    profile_block = GroundStateProtocol(convergence=_Convergence(tamper=True), relaxation=_Relaxation()).run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=tmp_path / "tampered-profile", overrides=_overrides(tmp_path))
    assert profile_block["status"] == "BLOCKED" and profile_block["blocking_stage"] == "handoff-validation"
    geometry_block = GroundStateProtocol(convergence=_Convergence(), relaxation=_Relaxation(tamper=True)).run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=tmp_path / "tampered-geometry", overrides=_overrides(tmp_path))
    assert geometry_block["status"] == "BLOCKED" and geometry_block["blocking_stage"] == "handoff-validation"
    missing_dm = GroundStateProtocol(convergence=_Convergence(), relaxation=_Relaxation()).run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=tmp_path / "missing-dm", overrides=_overrides(tmp_path, dm=False))
    assert missing_dm["status"] == "BLOCKED" and not (tmp_path / "missing-dm" / "electronic-state.json").exists()
    nonconverged = GroundStateProtocol(convergence=_Convergence(), relaxation=_Relaxation()).run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=tmp_path / "nonconverged", overrides=_overrides(tmp_path, converged=False))
    assert nonconverged["status"] == "BLOCKED" and not (tmp_path / "nonconverged" / "electronic-state.json").exists()

    class FailedConvergence:
        def run(self, *_args: object, **_kwargs: object) -> dict:
            return {"status": "BLOCKED"}
    blocked_relaxation = _Relaxation()
    blocked = GroundStateProtocol(convergence=FailedConvergence(), relaxation=blocked_relaxation).run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=tmp_path / "f03-blocked", overrides=_overrides(tmp_path))
    assert blocked["blocking_stage"] == "numerical-convergence" and blocked_relaxation.calls == 0


def test_ground_state_publishes_optional_verified_final_energy(tmp_path: Path) -> None:
    basis, mesh, kpoints = _campaigns(tmp_path); relax, final = _templates(tmp_path)
    result = GroundStateProtocol(convergence=_Convergence(), relaxation=_Relaxation()).run(
        basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final,
        runs_root=tmp_path / "energy-runs", overrides=_overrides(tmp_path, final_energy=True),
    )
    state = ContractEnvelope.from_dict(
        json.loads(Path(result["electronic_state"]).read_text(encoding="utf-8")),
        required_contract=SCIENTIFIC_ARTIFACT,
    ).payload["final_scf"]
    assert state["final_energy"]["quantity"] == "siesta.final_total_energy"
    assert state["final_energy"]["value_ev"] == -12.5
    assert state["final_energy"]["source_final_fdf_sha256"] == state["input_fdf_sha256"]


def test_ground_state_publishes_collinear_magnetic_evidence(tmp_path: Path) -> None:
    basis, mesh, kpoints = _campaigns(tmp_path); relax, final = _templates(tmp_path)
    for path in (basis.system.fdf, relax, final):
        path.write_text(path.read_text(encoding="utf-8") + "Spin polarized\n", encoding="utf-8")
    result = GroundStateProtocol(convergence=_Convergence(), relaxation=_Relaxation()).run(
        basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final,
        runs_root=tmp_path / "magnetic-runs", overrides=_overrides(tmp_path, magnetic=True),
    )
    assert result["status"] == "COMPLETED"
    state = ContractEnvelope.from_dict(
        json.loads(Path(result["electronic_state"]).read_text(encoding="utf-8")),
        required_contract=SCIENTIFIC_ARTIFACT,
    ).payload["final_scf"]
    assert state["spin_mode"] == "polarized"
    assert state["magnetic"]["requested"]["initialization"] == {"kind": "absent"}
    assert state["magnetic"]["observed"]["spin_mode"] == "polarized"
    assert state["magnetic"]["artifact"]["artifact_type"] == "qraft.magnetic-state"
    assert "Charge.Mulliken end" in (tmp_path / "magnetic-runs" / "handoff" / "final-scf" / "input.fdf").read_text(encoding="utf-8")
    assert state["magnetic"]["artifact"]["relative_path"].startswith("stages/final-scf/work/")


def test_ground_state_publishes_noncollinear_magnetic_evidence(tmp_path: Path) -> None:
    basis, mesh, kpoints = _campaigns(tmp_path); relax, final = _templates(tmp_path)
    spin = "Spin non-colinear\n%block DM.InitSpin\n  1 + 90.0 0.0\n%endblock DM.InitSpin\n"
    for path in (basis.system.fdf, relax, final):
        path.write_text(path.read_text(encoding="utf-8") + spin, encoding="utf-8")
    protocol = GroundStateProtocol(convergence=_Convergence(), relaxation=_Relaxation())
    root = tmp_path / "noncollinear-runs"
    result = protocol.run(
        basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final,
        runs_root=root, overrides=_overrides(tmp_path, noncollinear=True),
    )
    assert result["status"] == "COMPLETED"
    state = ContractEnvelope.from_dict(
        json.loads(Path(result["electronic_state"]).read_text(encoding="utf-8")),
        required_contract=SCIENTIFIC_ARTIFACT,
    ).payload["final_scf"]
    assert state["spin_mode"] == "non-collinear"
    assert state["magnetic"]["requested"]["initialization"]["moments"][0]["theta_deg"] == "90.0"
    assert state["magnetic"]["observed"]["quantity"]["representation"] == "cartesian"
    assert state["magnetic"]["artifact"]["artifact_type"] == "qraft.magnetic-state"
    retried = protocol.run(basis, mesh, kpoints, relaxation_fdf=relax, final_scf_fdf=final, runs_root=root, overrides=_overrides(tmp_path, noncollinear=True))
    assert retried["final_scf"]["reused"] is True
