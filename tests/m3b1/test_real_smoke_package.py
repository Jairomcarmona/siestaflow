from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from qraft.real_smoke import RealSiestaSmokePackager, RealSmokeSpec
from qraft.slurm_renderer import SlurmProfile


REPO = Path(__file__).resolve().parents[2]
CONTEXT = REPO.parent / "context" / "scientific_project_snapshot"
PROJECT = REPO / "examples/reference_projects/graphene_surf_gr5x5"
UPSTREAM_GEOMETRY = CONTEXT / "structures/parents/SURF_Gr5x5_clean_v01.xyz"
UPSTREAM_SEED = CONTEXT / "fdf/references/SURF_Gr5x5_clean_v01.fdf"
UPSTREAM_PSEUDO = Path(r"C:\Users\Jairo\Downloads\nc-sr-05_pbe_stringent_psml\nc-sr-05_pbe_stringent_psml\C.psml")
GEOMETRY = PROJECT / "systems/SURF_Gr5x5_clean_v01.xyz"
SEED = PROJECT / "systems/SURF_Gr5x5_clean_v01.seed.fdf"
PSEUDO = PROJECT / "pseudopotentials/C.psml"


def spec() -> RealSmokeSpec:
    return RealSmokeSpec(
        package_id="M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE",
        system_id="SURF_Gr5x5_clean_v01",
        geometry_path=GEOMETRY,
        seed_fdf_path=SEED,
        pseudopotential_path=PSEUDO,
        element="C",
        atomic_number=6,
        pseudopotential_provenance="PseudoDojo nc-sr-05 PBE stringent PSML; ONCVPSP metadata audited by T04A2/T06F",
        pseudopotential_license="CC-BY-4.0",
        redistribution_status="PERMITTED_WITH_ATTRIBUTION",
        profile=SlurmProfile(
            name="observed-remote-smoke-profile", verified_for_siesta=True,
            partition="q1h-20p", account="vini", qos="normal",
            nodes=1, ntasks=1, cpus_per_task=1, memory=None,
            walltime="00:02:00", signal="B:USR1@60",
            launcher_command="bash",
        ),
    )


def test_geometry_and_pseudopotential_are_real_and_hash_bound():
    assert GEOMETRY.read_bytes() == UPSTREAM_GEOMETRY.read_bytes()
    assert SEED.read_bytes() == UPSTREAM_SEED.read_bytes()
    assert PSEUDO.read_bytes() == UPSTREAM_PSEUDO.read_bytes()
    built = RealSiestaSmokePackager(spec()).build_files()
    manifest = json.loads(built["package_manifest.json"])
    geometry = manifest["geometry"]
    assert geometry["atoms"] == 50 and geometry["elements"] == {"C": 50}
    assert geometry["source_sha256"] == geometry["packaged_sha256"]
    assert built["geometry/SURF_Gr5x5_clean_v01.xyz"] == GEOMETRY.read_bytes()
    assert geometry["identity_status"] == "GEOMETRY_BYTE_IDENTICAL"
    assert all(len(geometry[name]) == 64 for name in ("coordinate_semantic_hash", "lattice_semantic_hash", "atom_order_hash"))
    pseudo = manifest["pseudopotential"]
    assert pseudo["source_sha256"] == pseudo["packaged_sha256"] == hashlib.sha256(PSEUDO.read_bytes()).hexdigest()
    assert pseudo["element"] == "C" and pseudo["atomic_number"] == 6
    assert pseudo["redistribution_status"] == "PERMITTED_WITH_ATTRIBUTION"


def test_fdf_is_rendered_and_validated_through_siesta_adapter():
    built = RealSiestaSmokePackager(spec()).build_files()
    fdf = built["input/smoke.fdf"].decode()
    manifest = json.loads(built["package_manifest.json"])
    assert "MD.Steps 0" in fdf and "MD.Steps 300" not in fdf
    assert "NumberOfAtoms 50" in fdf and "NumberOfSpecies 1" in fdf
    assert manifest["calculation"]["calculation_type"] == "single_point"
    assert manifest["calculation"]["geometry_optimization"] is False
    assert manifest["calculation"]["scientific_calculation_performed"] is False
    assert manifest["calculation"]["scientific_interpretation_allowed"] is False
    assert manifest["fdf"]["validator_status"] in {"PASS", "REVIEW"}


def test_package_contains_no_preselected_slurm_and_no_campaign(tmp_path: Path):
    plan = RealSiestaSmokePackager(spec()).package(tmp_path)
    root = Path(plan.destination)
    manifest = json.loads((root / "package_manifest.json").read_text())
    assert manifest["calculation"]["campaign"] is False
    slurms = list(root.rglob("*.slurm"))
    assert slurms == []
    assert (root / "prepare_smoke_job.py").is_file()
    assert manifest["runtime_gate"]["generated_slurm_distributed"] is False
    assert manifest["scheduler_profile"]["verified_for_siesta"] is False
    assert not any(path.suffix.lower() in {".psf", ".psml"} and path.name != "C.psml" for path in root.rglob("*"))
    verify = subprocess.run([sys.executable, str(root / "verify_package.py")], cwd=root, capture_output=True, text=True)
    assert verify.returncode == 0, verify.stderr
    assert "M3B1_PACKAGE_VERIFIED" in verify.stdout


def test_static_verifier_ignores_only_declared_mutable_runtime_trees(tmp_path: Path):
    plan = RealSiestaSmokePackager(spec()).package(tmp_path)
    root = Path(plan.destination)
    for name in ("evidence/login_discovery/summary.json", "results/siesta.out", "work/run.marker"):
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("runtime evidence\n")
    verify = subprocess.run([sys.executable, str(root / "verify_package.py")], cwd=root, capture_output=True, text=True)
    assert verify.returncode == 0, verify.stderr


def test_zip_is_deterministic_self_contained_and_independently_verifiable(tmp_path: Path):
    first = RealSiestaSmokePackager(spec()).package(tmp_path / "one")
    second = RealSiestaSmokePackager(spec()).package(tmp_path / "two")
    assert Path(first.zip_path).read_bytes() == Path(second.zip_path).read_bytes()
    with zipfile.ZipFile(first.zip_path) as archive:
        names = {entry.filename for entry in archive.infolist()}
        root = spec().package_id + "/"
        assert root + "pseudopotentials/C.psml" in names
        assert root + "geometry/SURF_Gr5x5_clean_v01.xyz" in names
        assert root + "input/smoke.fdf" in names
        assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in names)
