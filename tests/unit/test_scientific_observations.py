from __future__ import annotations

import json
from pathlib import Path

import pytest

from siestaflow.scientific_convergence import MeshObservation
from siestaflow.scientific_kgrid import KGridObservation
from siestaflow.scientific_observations import produce_observation


FDF = """SystemName Water molecule
SystemLabel h2o
NumberOfAtoms 3
NumberOfSpecies 2
Spin non-polarized
Mesh.Cutoff 300 Ry
%block kgrid.MonkhorstPack
  1 0 0 0.0
  0 1 0 0.0
  0 0 1 0.0
%endblock kgrid.MonkhorstPack
%block ChemicalSpeciesLabel
 1 8 O
 2 1 H
%endblock ChemicalSpeciesLabel
%block AtomicCoordinatesAndAtomicSpecies
 0.000 0.000 0.000 1
 0.757 0.586 0.000 2
-0.757 0.586 0.000 2
%endblock AtomicCoordinatesAndAtomicSpecies
"""

# Verbatim structural records from local SIESTA 5.4.2 serial H2O execution.
STDOUT = """redata: Mesh Cutoff = 300.0000 Ry
InitMesh: MESH = 90 x 72 x 72 = 466560
siesta: E_KS(eV) = -466.1045
SCF cycle converged after 12 iterations
>> End of run
Job completed
"""
FORCES = """-34.2580483982
 -0.000049005 -0.000000000 -0.000000000
  0.000000000 -0.000022814 -0.000000000
  0.000000000  0.000000000 -0.000000441
           3
  1     8      -0.000000000      -0.044217616       0.000000000 O
  2     1       0.034483725       0.022088843      -0.000000000 H
  2     1      -0.034483725       0.022088843      -0.000000000 H
"""


def _artifacts(tmp_path: Path) -> dict[str, Path]:
    paths = {name: tmp_path / name for name in ("h2o.fdf", "stdout.txt", "FORCE_STRESS", "pseudo.json")}
    paths["h2o.fdf"].write_text(FDF, encoding="utf-8")
    paths["stdout.txt"].write_text(STDOUT, encoding="utf-8")
    paths["FORCE_STRESS"].write_text(FORCES, encoding="utf-8")
    paths["pseudo.json"].write_text(json.dumps({"entries": ["O.psf", "H.psf"]}), encoding="utf-8")
    return paths


def test_real_siesta_artifacts_produce_strict_mesh_observation(tmp_path: Path) -> None:
    paths = _artifacts(tmp_path)
    observed = produce_observation(axis="mesh", observation_id="mesh-300", fdf=paths["h2o.fdf"], stdout=paths["stdout.txt"], force_stress=paths["FORCE_STRESS"], pseudopotential_manifest=paths["pseudo.json"])
    parsed = MeshObservation.from_mapping(observed)
    assert str(parsed.actual_cutoff_ry) == "300.0"
    assert parsed.mesh_dimensions == (90, 72, 72)
    assert str(parsed.forces_ev_per_ang[1][0]) == "0.034483725"
    assert parsed.scf_converged is True


def test_same_real_artifacts_produce_strict_kgrid_observation(tmp_path: Path) -> None:
    paths = _artifacts(tmp_path)
    observed = produce_observation(axis="kgrid", observation_id="k111", fdf=paths["h2o.fdf"], stdout=paths["stdout.txt"], force_stress=paths["FORCE_STRESS"], pseudopotential_manifest=paths["pseudo.json"])
    parsed = KGridObservation.from_mapping(observed)
    assert parsed.requested_grid.dimensions == (1, 1, 1)
    assert parsed.used_grid == parsed.requested_grid


def test_incomplete_real_output_is_rejected(tmp_path: Path) -> None:
    paths = _artifacts(tmp_path)
    paths["stdout.txt"].write_text("siesta: E_KS(eV) = -1\nJob completed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="InitMesh"):
        produce_observation(axis="mesh", observation_id="bad", fdf=paths["h2o.fdf"], stdout=paths["stdout.txt"], force_stress=paths["FORCE_STRESS"], pseudopotential_manifest=paths["pseudo.json"])


def test_spin_default_requires_completed_output_evidence(tmp_path: Path) -> None:
    paths = _artifacts(tmp_path)
    paths["h2o.fdf"].write_text(FDF.replace("Spin non-polarized\n", ""), encoding="utf-8")
    paths["stdout.txt"].write_text("Number of spin components = 1\n" + STDOUT, encoding="utf-8")
    observed = produce_observation(axis="mesh", observation_id="default-spin", fdf=paths["h2o.fdf"], stdout=paths["stdout.txt"], force_stress=paths["FORCE_STRESS"], pseudopotential_manifest=paths["pseudo.json"])
    assert observed["magnetic_signature"] == "non-polarized"
