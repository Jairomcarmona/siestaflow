from __future__ import annotations

import json
from pathlib import Path
import tomllib

import pytest

from siestaflow.contracts import (
    VALIDATION_REPORT,
    CapabilityRegistry,
    DecisionStatus,
)
from siestaflow.engines.siesta.fdf_parser import FDFParser
from siestaflow.engines.siesta.validation_catalog import (
    SiestaValidationCatalog,
)
from siestaflow.engines.siesta.validation_profile import (
    SiestaValidationProfile,
)
from siestaflow.siesta_validation import (
    SiestaContextualValidator,
    siesta_validation_plugin,
)

from tests.validation_fixture import BASE_FDF


def _validate(
    source: str,
    profile: SiestaValidationProfile | None = None,
):
    document = FDFParser().parse(source, source="fixture.fdf")
    return SiestaContextualValidator().validate(
        document,
        profile=profile,
        subject_id="fixture",
    )


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_catalog_is_versioned_deterministic_and_plugin_resolves() -> None:
    first = SiestaValidationCatalog.load_default()
    second = SiestaValidationCatalog.load_default()

    assert first.engine_version == "5.4.2"
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
    assert {
        "siestaflow.siesta.keyword-schema",
        "siestaflow.siesta.electrostatic-context",
        "siestaflow.siesta.dftu-context",
        "siestaflow.siesta.requested-output",
    } <= {entry.descriptor.rule_id for entry in first.rules}

    descriptor, provider = siesta_validation_plugin(first)
    capability_id = descriptor.capabilities[0].capability_id
    registry = CapabilityRegistry()
    registry.register(descriptor, {capability_id: provider})
    resolved = registry.resolve(
        capability_id,
        required_outputs=(VALIDATION_REPORT,),
    )
    assert resolved.implementation.rules() == tuple(
        entry.descriptor for entry in first.rules
    )


def test_siesta_json_catalogs_are_declared_as_wheel_package_data() -> None:
    root = Path(__file__).resolve().parents[2]
    configuration = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["tool"]["setuptools"]["package-data"][
        "siestaflow.engines.siesta.data"
    ] == ["*.json"]


def test_schema_lattice_and_kgrid_errors_fail_closed() -> None:
    malformed = BASE_FDF.replace(
        "Mesh.Cutoff 350 Ry",
        "Mesh.Cutoff -2 Ry\nDFTD3.Periodic 1 1",
    ).replace(
        "  0.0 0.0 18.0",
        "  0.0 0.0 0.0",
    ).replace(
        "  0 0 1 0.0",
        "  0 0 0 0.0",
    )

    report = _validate(malformed)

    assert report.status is DecisionStatus.FAIL
    assert {
        "MESH_CUTOFF_NONPOSITIVE",
        "KEYWORD_VALUE_INVALID",
        "LATTICE_MATRIX_SINGULAR",
        "KGRID_MATRIX_SINGULAR",
    } <= _codes(report)
    assert all(finding.hint for finding in report.findings)


def test_charged_slab_and_ambiguous_d3_are_review_not_auto_rejection() -> None:
    source = BASE_FDF.replace("NetCharge 0", "NetCharge 2").replace(
        "MD.TypeOfRun CG",
        "Slab.DipoleCorrection true\nDFTD3 true\nMD.TypeOfRun CG",
    )
    profile = SiestaValidationProfile(
        profile_id="charged-slab",
        periodicity="slab",
    )

    report = _validate(source, profile)

    assert report.status is DecisionStatus.REVIEW
    assert {
        "PERIODIC_NET_CHARGE_REVIEW",
        "CHARGED_DIPOLE_CORRECTION_DISCOURAGED",
        "D3_PERIODICITY_REVIEW",
    } <= _codes(report)
    assert report.metadata["heuristics_can_fail"] is False
    assert report.metadata["execution_authorized"] is False


def test_explicit_d3_periodicity_removes_only_the_ambiguity_warning() -> None:
    source = BASE_FDF.replace(
        "MD.TypeOfRun CG",
        "DFTD3 true\nDFTD3.Periodic 1 2\nMD.TypeOfRun CG",
    )
    report = _validate(
        source,
        SiestaValidationProfile(
            profile_id="slab",
            periodicity="slab",
        ),
    )

    assert "D3_PERIODICITY_REVIEW" not in _codes(report)


def test_dftu_linear_response_is_classified_and_invalid_setup_blocks() -> None:
    no_projector = BASE_FDF.replace(
        "MD.TypeOfRun CG",
        "DFTU.PotentialShift true\nMD.TypeOfRun CG",
    )
    blocked = _validate(no_projector)
    assert blocked.status is DecisionStatus.BLOCKED
    assert "DFTU_POTENTIAL_SHIFT_WITHOUT_PROJECTOR" in _codes(blocked)

    with_projector = BASE_FDF.replace(
        "MD.TypeOfRun CG",
        """\
DFTU.ProjectorGenerationMethod 2
DFTU.PotentialShift true
%block DFTU.Proj
  C 1
  n=2 0 4.0 0.2
%endblock DFTU.Proj
MD.TypeOfRun CG""",
    )
    classified = _validate(with_projector)
    assert classified.status is DecisionStatus.REVIEW
    assert "DFTU_LINEAR_RESPONSE_MODE_ACTIVE" in _codes(classified)
    assert "DFTU_PROJECTOR_HEADER_INVALID" not in _codes(classified)


def test_bader_requirement_and_cost_limits_remain_explicit_policy() -> None:
    profile = SiestaValidationProfile(
        profile_id="final-density",
        periodicity="bulk",
        required_outputs=("bader",),
        review_limits={
            "max_kpoints": 4,
            "max_atoms_times_kpoints": 8,
        },
    )
    missing = _validate(BASE_FDF, profile)
    assert missing.status is DecisionStatus.BLOCKED
    assert "BADER_OUTPUT_NOT_ENABLED" in _codes(missing)
    assert "KPOINT_COUNT_EXCEEDS_PROJECT_REVIEW_LIMIT" in _codes(missing)
    assert "ATOM_KPOINT_PROXY_EXCEEDS_PROJECT_REVIEW_LIMIT" in _codes(missing)

    low_mesh = BASE_FDF.replace("Mesh.Cutoff 350 Ry", "Mesh.Cutoff 250 Ry").replace(
        "MD.TypeOfRun CG",
        "SaveBaderCharge true\nMD.TypeOfRun CG",
    )
    reviewed = _validate(low_mesh, profile)
    assert reviewed.status is DecisionStatus.REVIEW
    assert "BADER_OUTPUT_NOT_ENABLED" not in _codes(reviewed)
    assert "BADER_MESH_CUTOFF_REVIEW" in _codes(reviewed)


def test_profile_loader_rejects_unknown_or_nonpositive_policy(tmp_path: Path) -> None:
    valid_path = tmp_path / "profile.json"
    valid_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "profile_id": "bulk-final",
                "periodicity": "bulk",
                "required_outputs": ["bader"],
                "review_limits": {"max_kpoints": 100},
            }
        ),
        encoding="utf-8",
    )
    profile = SiestaValidationProfile.load(valid_path)
    assert profile.profile_id == "bulk-final"
    assert len(profile.sha256) == 64

    valid_path.write_text(
        json.dumps(
            {
                "profile_id": "bad",
                "periodicity": "bulk",
                "review_limits": {"max_kpoints": 0},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="positive integer"):
        SiestaValidationProfile.load(valid_path)
