from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from siestaflow.errors import AlreadyExistsError
from siestaflow.project_packages import ProjectPackageLoader
from siestaflow.project_scaffold import (
    ProjectInitRequest,
    ProjectScaffolder,
)


def valid_sources(root: Path) -> tuple[Path, Path, Path]:
    fdf = root / "seed.fdf"
    fdf.write_text(
        """SystemLabel test
NumberOfAtoms 2
NumberOfSpecies 2
%block ChemicalSpeciesLabel
1 20 Ca
2 8 O
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10 0 0
0 10 0
0 0 10
%endblock LatticeVectors
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
1 0 0 2
%endblock AtomicCoordinatesAndAtomicSpecies
NetCharge 0
Spin non-polarized
MD.TypeOfRun CG
MD.Steps 0
""",
        encoding="utf-8",
    )
    structure = root / "seed.xyz"
    structure.write_text(
        "2\ntechnical test\nCa 0 0 0\nO 1 0 0\n",
        encoding="utf-8",
    )
    pseudo = root / "manifest.yaml"
    pseudo.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "entries": [
                    {
                        "species": species,
                        "filename": f"{species}.psml",
                        "format": "psml",
                        "sha256": character * 64,
                        "source": "external",
                        "xc_family": None,
                        "relativity": None,
                        "distribution_status": "EXTERNAL_NOT_PACKAGED",
                        "location_status": "EXTERNAL_NOT_PACKAGED",
                    }
                    for species, character in (("Ca", "a"), ("O", "b"))
                ],
            }
        ),
        encoding="utf-8",
    )
    return fdf, structure, pseudo


def request(tmp_path: Path, *, dry_run: bool = False) -> ProjectInitRequest:
    fdf, structure, pseudo = valid_sources(tmp_path)
    return ProjectInitRequest(
        root=tmp_path / "project",
        project_id="calcium_surface",
        title="Calcium surface preparation",
        system_id="ca_o_seed",
        fdf=fdf,
        structure=structure,
        pseudopotential_manifest=pseudo,
        dry_run=dry_run,
    )


def test_project_init_creates_valid_preparation_only_package(tmp_path: Path):
    init = request(tmp_path)
    source_hash = hashlib.sha256(init.fdf.read_bytes()).hexdigest()
    result = ProjectScaffolder().initialize(init)

    assert result.status == "PROJECT_INITIALIZED_WITH_REVIEW"
    assert result.changed is True
    assert result.execution_authorized is False
    assert ProjectPackageLoader().validate(init.root).valid
    assert hashlib.sha256(
        (init.root / "systems/ca_o_seed.fdf").read_bytes()
    ).hexdigest() == source_hash
    project = json.loads(
        (init.root / "project.yaml").read_text(encoding="utf-8")
    )
    assert project["metadata"]["scientific_defaults_assigned"] is False


def test_project_init_dry_run_has_zero_filesystem_effects(tmp_path: Path):
    init = request(tmp_path, dry_run=True)
    result = ProjectScaffolder().initialize(init)

    assert result.status == "PROJECT_INIT_PREVIEW"
    assert result.changed is False
    assert not init.root.exists()


def test_project_init_is_idempotent_for_identical_sources(tmp_path: Path):
    init = request(tmp_path)
    first = ProjectScaffolder().initialize(init)
    second = ProjectScaffolder().initialize(init)

    assert first.changed is True
    assert second.status == "PROJECT_ALREADY_INITIALIZED"
    assert second.changed is False


def test_project_init_refuses_existing_mismatched_project(tmp_path: Path):
    init = request(tmp_path)
    ProjectScaffolder().initialize(init)
    init.fdf.write_text(
        init.fdf.read_text(encoding="utf-8") + "# changed\n",
        encoding="utf-8",
    )

    with pytest.raises(AlreadyExistsError):
        ProjectScaffolder().initialize(init)


def test_project_init_blocks_missing_pseudopotential_species(tmp_path: Path):
    init = request(tmp_path)
    data = json.loads(init.pseudopotential_manifest.read_text(encoding="utf-8"))
    data["entries"] = data["entries"][:1]
    init.pseudopotential_manifest.write_text(
        json.dumps(data),
        encoding="utf-8",
    )
    result = ProjectScaffolder().initialize(init)

    assert result.status == "PROJECT_INIT_BLOCKED"
    assert result.changed is False
    assert not init.root.exists()
    assert "PSEUDOPOTENTIAL_DECLARATION_MISSING" in {
        finding.code for finding in result.findings
    }
