"""WF-SURFACE implementation against byte-preserved accepted vectors."""
import hashlib
import json
from pathlib import Path

import pytest

from qraft.api import SurfaceProtocol, scientific_policy_document
from qraft.engines.siesta.effective_fdf import resolve_effective_fdf
from qraft.engines.siesta.fdf_registry import FDFRegistry
from qraft.engines.siesta.fdf_parser import FDFParser
from qraft.engines.siesta.preflight import scalar_value
from qraft.siesta_validation import SiestaContextualValidator


FIXTURES = Path(__file__).parents[1] / "fixtures/scientific_protocols/surface"
DATA_PATH = FIXTURES / "surface.cases.json"
DATA = json.loads(DATA_PATH.read_text(encoding="utf-8"))
POLICY = scientific_policy_document("qraft.surface.policy@1")


def _close(actual, expected, tolerance):
    if expected is None or isinstance(expected, (bool, str)):
        assert actual == expected
    elif isinstance(expected, (int, float)):
        assert actual == pytest.approx(expected, rel=tolerance["rel"], abs=tolerance["abs"])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            _close(left, right, tolerance)
    else:
        assert set(actual) == set(expected)
        for key, value in expected.items():
            _close(actual[key], value, tolerance)


def test_surface_fixture_digest_and_source_are_pinned():
    digest = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    assert digest == "91d4af8bc8ee5947708412f54614f5ed7ee56520e3493263180db5e228b64608"
    assert "f78abf21c097bfc04fdcfa265e7514eb5619597a" in readme
    assert digest in readme
    assert len(DATA["cases"]) == 33


def test_surface_policy_document_matches_accepted_vector_policy():
    expected = next(case["policy"] for case in DATA["cases"] if case.get("policy"))
    assert POLICY == expected
    assert set(POLICY) == {
        "potential", "allow_vt", "window_A", "step_A", "margin_A", "width_min_A",
        "slope_max_eV_per_A", "range_max_meV", "stability_meV", "perpendicular_tol_deg",
        "convergence_meV",
    }


def test_dipole_registry_is_a_five_value_enum():
    entry = FDFRegistry.load_default().get("Slab.DipoleCorrection")
    assert entry is not None
    assert entry.value_type == "enum"
    assert entry.enum_values == ("true", "false", "charge", "vacuum", "none")
    assert entry.repeat_policy == "reject"


def test_dipole_value_is_preserved_while_interpreting_case_insensitively():
    result = SurfaceProtocol().dipole_correction("Slab.DipoleCorrection VaCuUm\n")
    assert result == {
        "accepted": True,
        "value": "VaCuUm",
        "effective": "VACUUM",
        "error": None,
    }


@pytest.mark.parametrize("dipole", ["false", "FALSE", "none", "NoNe"])
def test_uncompensated_asymmetric_slab_rejects_case_insensitive_no_correction(dipole):
    case = next(item for item in DATA["cases"] if item["id"] == "surf-synth-asym")
    run = {**case["run"], "dipole_correction": dipole}
    result = SurfaceProtocol().analyze(run, policy=case["policy"])
    assert result["verdict"] == "NOT_ESTABLISHED"
    assert result["reasons"] == ["DIPOLE_UNCOMPENSATED_ASYMMETRIC"]


def test_surface_sweep_labels_are_registered_with_documented_units():
    registry = FDFRegistry.load_default()
    total_potential = registry.get("SaveTotalPotential")
    temperature = registry.get("ElectronicTemperature")
    assert total_potential is not None
    assert total_potential.value_type == "boolean"
    assert temperature is not None
    assert temperature.unit_policy == "temperature_or_energy"


@pytest.mark.parametrize(
    ("temperature", "expected_error", "expected_unit"),
    [("300 K", None, "K"), ("25 meV", None, "Ry"), ("300 Ang", "UNIT_DIMENSION_MISMATCH", None)],
)
def test_surface_sweep_temperature_units_are_checked_by_dimension(
    temperature, expected_error, expected_unit, tmp_path
):
    path = tmp_path / "surface.fdf"
    path.write_text(
        """SystemLabel surface
NumberOfSpecies 1
NumberOfAtoms 1
NetCharge 0
Spin non-polarized
MD.TypeOfRun CG
MD.Steps 0
ElectronicTemperature {temperature}
SaveTotalPotential true
%block ChemicalSpeciesLabel
 1 13 Al
%endblock ChemicalSpeciesLabel
%block AtomicCoordinatesAndAtomicSpecies
 0 0 0 1
%endblock AtomicCoordinatesAndAtomicSpecies
%block LatticeVectors
 2 0 0
 0 2 0
 0 0 8
%endblock LatticeVectors
""".format(temperature=temperature),
        encoding="utf-8",
    )
    report = SiestaContextualValidator().validate_path(path)
    codes = {finding.code for finding in report.findings}
    if expected_error is None:
        assert not codes.intersection({"UNIT_UNKNOWN", "UNIT_DIMENSION_MISMATCH"})
    else:
        assert expected_error in codes
    assert "KEYWORD_NOT_REGISTERED" not in codes
    if expected_unit is not None:
        parsed = scalar_value(
            resolve_effective_fdf(path),
            "ElectronicTemperature",
            {"type": "physical", "dimension": "temperature_or_energy", "canonical_unit": "Ry"},
        )
        assert parsed["unit"] == expected_unit
        if expected_unit == "K":
            assert parsed["value"] == 300
        else:
            assert parsed["value"] == pytest.approx(25 * 7.349864435e-05)


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda item: item["id"])
def test_surface_protocol_vectors(case, tmp_path):
    protocol = SurfaceProtocol()
    kind = case["kind"]
    if kind == "perpendicular":
        actual = protocol.a3_perpendicular(case["cell"], tol_deg=case["tol_deg"])
    elif kind == "run":
        actual = protocol.analyze(case["run"], policy=case["policy"])
    elif kind == "dipole_label":
        actual = protocol.dipole_correction(case["fdf"])
        path = tmp_path / "input.fdf"
        path.write_text(case["fdf"], encoding="utf-8")
        report = SiestaContextualValidator().validate_path(path)
        findings = [item for item in report.findings if "Slab.DipoleCorrection" in item.message]
        error = case["expect"]["error"]
        if error is None:
            assert not any(item.code in {"KEYWORD_VALUE_INVALID", "LABEL_DUPLICATED"} for item in findings)
        else:
            assert any(item.code == error for item in findings)
    elif kind == "macro":
        actual = protocol.macroscopic_average(
            case["profile_eV"], cell_c_A=case["cell_c_A"],
            period_A=case["period_A"], centers_A=case["centers_A"],
        )
    elif kind == "fermi_comparable":
        actual = protocol.fermi_comparable(case["cell_a"], case["cell_b"], tolerance_A=case["tol_A"])
    elif kind == "convergence":
        actual = protocol.phi_convergence(case["points"], tolerance_meV=case["tol_meV"])
    else:
        raise AssertionError(f"unhandled surface vector kind: {kind}")
    _close(actual, case["expect"], DATA["arithmetic_tolerance"])


def test_charged_slab_with_active_dipole_mode_requests_review():
    document = FDFParser().parse("NetCharge 1\nSlab.DipoleCorrection vacuum\n")
    report = SiestaContextualValidator().validate(document)
    assert any(
        item.code == "CHARGED_DIPOLE_CORRECTION_DISCOURAGED"
        for item in report.findings
    )
