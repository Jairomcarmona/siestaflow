from __future__ import annotations

import hashlib
import ast
import json
from pathlib import Path

import pytest

from siestaflow.engines.siesta.pseudopotentials import PseudopotentialManifest, PseudopotentialStager
from siestaflow.project_packages import ProjectPackageLoader
from siestaflow.remote import RemotePackager, RemoteResultImporter, create_synthetic_result_bundle
from siestaflow.siesta_campaigns import SiestaCampaignFactory, simulate_definition


def _write(path: Path, value: object | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _make_project(root: Path, project_id: str, species: tuple[str, ...], values: tuple[str, ...]) -> tuple[Path, Path]:
    system_id = "system"
    campaign_id = "series"
    input_lines = [
        f"SystemName {project_id}", f"SystemLabel {project_id.lower()}",
        f"NumberOfAtoms {len(species)}", f"NumberOfSpecies {len(species)}",
        "%block ChemicalSpeciesLabel",
        *[f"  {index} {index} {name}" for index, name in enumerate(species, 1)],
        "%endblock ChemicalSpeciesLabel", "LatticeConstant 1.0 Ang",
        "%block LatticeVectors", "  6 0 0", "  0 6 0", "  0 0 6", "%endblock LatticeVectors",
        "AtomicCoordinatesFormat Ang", "%block AtomicCoordinatesAndAtomicSpecies",
        *[f"  {index - 1}.0 0.0 0.0 {index}" for index in range(1, len(species) + 1)],
        "%endblock AtomicCoordinatesAndAtomicSpecies", f"Mesh.Cutoff {values[0]}",
        "NetCharge 0", "Spin non-polarized", "MD.TypeOfRun CG", "MD.Steps 0", "",
    ]
    _write(root / "project.yaml", {
        "schema_version": "1.0", "project_id": project_id, "engine": "siesta",
        "systems": [system_id], "campaigns": [campaign_id],
        "pseudopotential_manifest": "pseudopotentials/manifest.yaml",
    })
    _write(root / "systems" / f"{system_id}.yaml", {
        "system_id": system_id, "structure": "structures/system.xyz", "species": list(species),
        "input_template": "systems/system.fdf",
    })
    _write(root / "systems" / "system.fdf", "\n".join(input_lines))
    _write(root / "structures" / "system.xyz", f"{len(species)}\nsynthetic\n" + "\n".join(f"{name} 0 0 0" for name in species) + "\n")
    pseudo_source = root.parent / f"{project_id}_pseudos"
    entries = []
    for name in species:
        path = pseudo_source / f"{name}.psml"
        _write(path, f"<psml>synthetic {name}</psml>\n")
        entries.append({
            "species": name, "filename": path.name, "format": "psml",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source": "test",
            "xc_family": None, "relativity": None, "distribution_status": "EXTERNAL_NOT_PACKAGED",
            "location_status": "EXTERNAL_NOT_PACKAGED",
        })
    _write(root / "pseudopotentials" / "manifest.yaml", {"schema_version": "1.0", "entries": entries})
    _write(root / "campaigns" / f"{campaign_id}.yaml", {
        "schema_version": "1.0", "campaign_id": campaign_id, "system_id": system_id, "task_type": "SYNTHETIC_PARAMETER",
        "parameter": "Mesh.Cutoff", "values": list(values), "authorization": "authorizations/local.yaml",
        "policy": "policies/local.yaml", "mode": "sequential", "synthetic_only": True,
    })
    _write(root / "authorizations" / "local.yaml", {
        "authorization_id": f"AUTH_{project_id}", "allowed_task_types": ["SYNTHETIC_PARAMETER"],
        "targets": [system_id], "forbidden_operations": ["REAL_ENGINE", "SBATCH", "SSH"],
    })
    _write(root / "policies" / "local.yaml", {"schema_version": "1.0", "execution": "synthetic_only"})
    _write(root / "expected_contracts" / "local.yaml", {"expected_decision": "PASS"})
    return root, pseudo_source


@pytest.mark.parametrize(
    "project_id,species,values",
    [
        ("ALPHA_XY", ("X", "Y"), ("175 Ry", "265 Ry")),
        ("BETA_ABC", ("A", "B", "C"), ("140 Ry", "220 Ry", "410 Ry")),
    ],
)
def test_arbitrary_projects_reach_local_end_to_end(
    tmp_path: Path, project_id: str, species: tuple[str, ...], values: tuple[str, ...],
):
    root, pseudo_source = _make_project(tmp_path / project_id, project_id, species, values)
    loader = ProjectPackageLoader()
    assert loader.validate(root).valid
    package = loader.load(root)
    definition, variants = SiestaCampaignFactory().from_package(package, "series")
    assert len(variants) == len(values)
    assert definition.metadata["species"] == list(species)

    pseudo = PseudopotentialManifest.load(package.pseudopotential_manifest)
    stage = PseudopotentialStager().stage(pseudo, pseudo_source, tmp_path / f"stage_{project_id}", policy="copy")
    assert stage.status.value == "PASS"
    assert stage.example_status == "EXAMPLE_READY"
    assert stage.manifest_path and Path(stage.manifest_path).is_file()
    assert {item.species for item in stage.entries} == set(species)

    state, launcher, slurm = simulate_definition(definition, tmp_path / f"run_{project_id}")
    assert state.final_decision.value == "PASS"
    assert len(launcher.launches) == len(values)
    assert slurm.submissions == 1

    input_path = package.root / package.system("system").input_template
    files = RemotePackager().build_files(definition, input_path, pseudopotentials=pseudo)
    assert all(item.filename in files["validation_manifest.json"] for item in pseudo.entries)
    assert not any(line.lstrip().startswith("sbatch ") for line in "\n".join(files.values()).splitlines())

    bundle = tmp_path / f"results_{project_id}"
    create_synthetic_result_bundle(bundle, "series", "Siesta started\nSCF converged\nJob completed\n")
    imported = RemoteResultImporter().import_bundle(bundle, tmp_path / f"import_{project_id}", expected_campaign_id="series")
    assert imported.status.value == "REMOTE_RESULTS_IMPORTED"
    assert imported.synthetic is True


def test_core_contains_no_reference_project_constants():
    source = Path(__file__).resolve().parents[2] / "src" / "siestaflow"
    paths = [path for path in source.rglob("*") if path.suffix in {".py", ".json", ".yaml"}]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    reference = Path(__file__).resolve().parents[2] / "examples" / "reference_projects" / "birnessite_mn_o" / "pseudopotentials" / "manifest.yaml"
    reference_hashes = tuple(item.sha256 for item in PseudopotentialManifest.load(reference).entries if item.sha256)
    forbidden = (
        "Mn.psml", "O.psml", "M1_", "MnO2", "birnessite", "birnessita", "ADSORB_", "Ca8w", "Mg6w",
        *reference_hashes, "200/250/300/350", "scientific_project_snapshot",
    )
    assert not [value for value in forbidden if value.casefold() in text.casefold()]
    literals: list[object] = []
    for path in (item for item in paths if item.suffix == ".py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        literals.extend(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant))
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)):
                values = [item.value for item in node.elts if isinstance(item, ast.Constant)]
                assert values != [200, 250, 300, 350]
                assert values != ["200 Ry", "250 Ry", "300 Ry", "350 Ry"]
    assert not ({"Mn", "O", "Ca", "Mg"} & {value for value in literals if isinstance(value, str)})
    assert not [value for value in literals if isinstance(value, str) and any(term.casefold() in value.casefold() for term in forbidden)]
