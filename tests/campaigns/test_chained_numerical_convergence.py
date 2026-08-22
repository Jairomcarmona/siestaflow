from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from qraft.campaign_spec import CampaignSpec
from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.protocols.chained_convergence import ChainedConvergenceProtocol


FDF = """SystemName F03 test
SystemLabel f03
NumberOfAtoms 1
NumberOfSpecies 1
Mesh.Cutoff 111 Ry
PAO.BasisSize SZ
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0.0 0.0 0.0 1
%endblock AtomicCoordinatesAndAtomicSpecies
%block kgrid.MonkhorstPack
1 0 0 0.0
0 1 0 0.0
0 0 1 0.0
%endblock kgrid.MonkhorstPack
"""


def _campaign(root: Path, campaign_id: str, parameter: dict, extras: dict | None = None) -> CampaignSpec:
    raw = {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "engine": "siesta",
        "protocol": "convergence",
        "system": {"fdf": "system.fdf"},
        "parameters": {**(extras or {}), **parameter},
        "criterion": {
            "metric": "energy_per_atom", "delta": 0.001,
            "unit": "eV", "consecutive": 2,
        },
    }
    return CampaignSpec.from_mapping(raw, source=root / f"{campaign_id}.yaml")


def _templates(root: Path) -> tuple[CampaignSpec, CampaignSpec, CampaignSpec]:
    (root / "system.fdf").write_text(FDF, encoding="utf-8")
    (root / "C.psf").write_text("pseudo\n", encoding="utf-8")
    basis = _campaign(root, "basis-stage", {
        "basis_size": {"mode": "scan", "values": ["SZ", "DZ", "DZP"]},
    })
    mesh = _campaign(root, "mesh-stage", {
        "mesh_cutoff": {"mode": "scan", "values": [200, 250, 300], "unit": "Ry"},
    }, {"basis_size": {"mode": "fixed", "value": "SZ"}})
    kpoints = _campaign(root, "kpoints-stage", {
        "kpoints": {"mode": "scan", "grids": [[1, 1, 1], [2, 2, 2], [3, 3, 3]]},
    }, {
        "basis_size": {"mode": "fixed", "value": "SZ"},
        "mesh_cutoff": {"mode": "fixed", "value": 200, "unit": "Ry"},
    })
    return basis, mesh, kpoints


def _overrides(root: Path) -> dict:
    fake = root / "fake_siesta.py"
    fake.write_text(
        "import re,sys\ntext=open(sys.argv[1], encoding='utf-8').read()\n"
        "stage='basis' if 'stages/basis/' in sys.argv[1].replace('\\\\','/') else ('mesh' if 'stages/mesh/' in sys.argv[1].replace('\\\\','/') else 'kpoints')\n"
        "basis=re.search(r'PAO\\.BasisSize\\s+(\\S+)', text, re.I).group(1)\n"
        "mesh=float(re.search(r'Mesh\\.Cutoff\\s+([0-9.]+)', text, re.I).group(1))\n"
        "grid=int(re.search(r'%block kgrid\\.MonkhorstPack\\s+([0-9]+)', text, re.I).group(1))\n"
        "energy=({'SZ':-10.0,'DZ':-10.0005,'DZP':-10.0009}[basis] if stage == 'basis' else "
        "({200.0:-20.0,250.0:-20.0005,300.0:-20.0009}[mesh] if stage == 'mesh' else "
        "{1:-30.0,2:-30.0005,3:-30.0009}[grid]))\n"
        "print('Siesta started')\nprint('SCF cycle 1')\nprint('SCF converged')\n"
        "print(f'siesta: E_KS(eV) = {energy}')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    wrapper = root / ("fake-siesta.cmd" if os.name == "nt" else "fake-siesta")
    if os.name == "nt":
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{fake}" %1\r\n', encoding="utf-8")
    else:
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$1"\n', encoding="utf-8")
        wrapper.chmod(0o755)
    return {"partition": "local", "launcher": "direct", "executable": str(wrapper)}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_chained_numerical_convergence_handoff_recovery_and_guards(tmp_path: Path) -> None:
    basis, mesh, kpoints = _templates(tmp_path)
    root = tmp_path / "runs"
    protocol = ChainedConvergenceProtocol()
    first = protocol.run(basis, mesh, kpoints, runs_root=root, overrides=_overrides(tmp_path))
    assert first["status"] == "COMPLETED"
    assert first["stages"]["basis"]["selected_point"] == "DZP"
    assert first["stages"]["mesh"]["selected_point"] == 300
    assert first["stages"]["kpoints"]["selected_point"] == (3, 3, 3)

    handoff = root / "handoff"
    basis_selection = handoff / "basis-selection.json"
    mesh_selection = handoff / "mesh-selection.json"
    kpoint_selection = handoff / "kpoints-selection.json"
    for path, stage, parameter in (
        (basis_selection, "basis", "basis_size"),
        (mesh_selection, "mesh", "mesh_cutoff"),
        (kpoint_selection, "kpoints", "kpoints"),
    ):
        envelope = ContractEnvelope.from_dict(json.loads(path.read_text(encoding="utf-8")), required_contract=SCIENTIFIC_ARTIFACT)
        assert envelope.payload["artifact_type"] == "siestaflow.numerical-selection"
        assert envelope.payload["authority"] == "PROVISIONAL"
        assert envelope.payload["stage"] == stage and envelope.payload["parameter"] == parameter

    basis_hash, mesh_hash, profile_hash = _sha(basis_selection), _sha(mesh_selection), _sha(root / "numerical-profile.json")
    chain = json.loads((root / "chain-result.json").read_text(encoding="utf-8"))
    assert {(item["parameter"], item["downstream_stage"], item["selection_artifact_sha256"]) for item in chain["handoff"]} >= {
        ("basis_size", "mesh", basis_hash), ("basis_size", "kpoints", basis_hash),
        ("mesh_cutoff", "kpoints", mesh_hash),
    }
    profile = ContractEnvelope.from_dict(json.loads((root / "numerical-profile.json").read_text(encoding="utf-8")), required_contract=SCIENTIFIC_ARTIFACT)
    assert profile.payload["artifact_type"] == "siestaflow.numerical-profile"
    assert profile.payload["selections"]["basis_size"]["selection_artifact_sha256"] == basis_hash
    assert profile.payload["selections"]["mesh_cutoff"]["selection_artifact_sha256"] == mesh_hash

    for fdf in (root / "stages" / "mesh" / "rendered").glob("point_*/input.fdf"):
        assert "PAO.BasisSize DZP" in fdf.read_text(encoding="utf-8")
    for fdf in (root / "stages" / "kpoints" / "rendered").glob("point_*/input.fdf"):
        text = fdf.read_text(encoding="utf-8")
        assert "PAO.BasisSize DZP" in text and "Mesh.Cutoff 300 Ry" in text

    second = protocol.run(basis, mesh, kpoints, runs_root=root, overrides=_overrides(tmp_path))
    assert all(point["reused"] for stage in second["stages"].values() for point in stage["points"])
    assert (_sha(basis_selection), _sha(mesh_selection), _sha(root / "numerical-profile.json")) == (basis_hash, mesh_hash, profile_hash)

    basis_selection.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable artifact content mismatch"):
        protocol.run(basis, mesh, kpoints, runs_root=root, overrides=_overrides(tmp_path))


def test_nonconverged_basis_blocks_downstream_stages(tmp_path: Path) -> None:
    basis, mesh, kpoints = _templates(tmp_path)
    nonconverged = replace(basis, criterion=replace(basis.criterion, delta=0.00001))
    root = tmp_path / "blocked"
    result = ChainedConvergenceProtocol().run(
        nonconverged, mesh, kpoints, runs_root=root, overrides=_overrides(tmp_path)
    )
    assert result["status"] == "BLOCKED" and result["blocking_stage"] == "basis"
    assert not (root / "stages" / "mesh").exists()
    assert not (root / "stages" / "kpoints").exists()
    assert not (root / "numerical-profile.json").exists()
