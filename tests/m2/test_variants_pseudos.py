import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qraft.authorization import AuthorizationEngine
from qraft.engines.siesta.fdf_variants import FDFVariantGenerator, VariantAuthorization
from qraft.engines.siesta.pseudopotentials import PseudopotentialEntry, PseudopotentialManifest, PseudopotentialVerifier


def _authorization(base: str, parameter: str, values: tuple[str, ...]):
    envelope = AuthorizationEngine.issue(
        authorization_id="AUTH_TEST", campaign_id="CAMPAIGN_TEST",
        allowed_task_types=("SIESTA_SYNTHETIC_MESH",), generic_targets=("M1_U0_FM",),
        forbidden_operations=("REAL_SIESTA",), stop_on_review=True, issued_by="pytest",
        issued_at=datetime.now(timezone.utc).isoformat(), expires_at="2099-01-01T00:00:00+00:00",
    )
    return VariantAuthorization.issue(envelope, base_fdf_sha256=hashlib.sha256(base.encode()).hexdigest(), allowed_parameter=parameter, allowed_values=values, synthetic_only=True)


def test_mesh_series_changes_one_authorized_variable(sanity_fdf: Path):
    base = sanity_fdf.read_text(encoding="utf-8")
    values = ("175 Ry", "275 Ry", "425 Ry")
    auth = _authorization(base, "Mesh.Cutoff", values)
    variants = FDFVariantGenerator().generate_series(base, auth)
    assert [item.value for item in variants] == list(values)
    assert all(set(item.semantic_diff["changed_parameters"]) <= {"meshcutoff"} for item in variants)
    assert sum(item.semantic_diff["baseline"] for item in variants) == 0


def test_kgrid_changes_one_authorized_variable(sanity_fdf: Path):
    base = sanity_fdf.read_text(encoding="utf-8")
    values = ("2x3x1", "5x4x2")
    auth = _authorization(base, "kgrid.MonkhorstPack", values)
    variants = FDFVariantGenerator().generate_series(base, auth)
    assert len(variants) == len(values)
    assert all(set(item.semantic_diff["changed_parameters"]) <= {"kgridmonkhorstpack"} for item in variants)
    assert sum(item.semantic_diff["baseline"] for item in variants) == 0


@pytest.mark.parametrize("mutation", [
    lambda text: text.replace("NumberOfAtoms 54", "NumberOfAtoms 53"),
    lambda text: text.replace("NetCharge 0", "NetCharge 1"),
])
def test_geometry_or_charge_change_is_rejected(sanity_fdf: Path, mutation):
    base = sanity_fdf.read_text(encoding="utf-8")
    changed = mutation(base).replace("Mesh.Cutoff 250 Ry", "Mesh.Cutoff 300 Ry")
    with pytest.raises(PermissionError):
        FDFVariantGenerator().verify_single_change(base, changed, "Mesh.Cutoff")


def test_unauthorized_parameter_and_value_are_blocked(sanity_fdf: Path):
    base = sanity_fdf.read_text(encoding="utf-8")
    with pytest.raises(PermissionError):
        FDFVariantGenerator().generate(base, _authorization(base, "NetCharge", ("1",)), "1")
    with pytest.raises(PermissionError):
        FDFVariantGenerator().generate(base, _authorization(base, "Mesh.Cutoff", ("250 Ry",)), "300 Ry")


def _entry(path: Path, *, species="Mn", digest=None, fmt="psml"):
    return PseudopotentialEntry(species, f"{species}.{fmt}", fmt, digest or hashlib.sha256(path.read_bytes()).hexdigest(), "test", "VDW", "scalar", {}, "AUTHORIZED_LOCAL_TEST", "PRESENT", str(path))


def test_pseudo_manifest_correct_missing_hash_duplicate_and_format(tmp_path: Path):
    mn = tmp_path / "Mn.psml"
    oxygen = tmp_path / "O.psml"
    mn.write_text("synthetic Mn", encoding="utf-8")
    oxygen.write_text("synthetic O", encoding="utf-8")
    verifier = PseudopotentialVerifier()
    good = PseudopotentialManifest((_entry(mn), _entry(oxygen, species="O")))
    assert verifier.verify(good, ("Mn", "O")).status.value == "PASS"
    assert verifier.verify(PseudopotentialManifest((_entry(mn),)), ("Mn", "O")).status.value == "BLOCKED"
    assert verifier.verify(PseudopotentialManifest((_entry(mn, digest="0" * 64),)), ("Mn",)).status.value == "FAIL"
    assert verifier.verify(PseudopotentialManifest((_entry(mn), _entry(mn))), ("Mn",)).status.value == "FAIL"
    assert verifier.verify(PseudopotentialManifest((_entry(mn, fmt="upf"),)), ("Mn",)).status.value == "FAIL"


def test_external_not_packaged_remains_blocked():
    entry = PseudopotentialEntry("Mn", "Mn.psml", "psml", "0" * 64, "audit", None, None, {}, "EXTERNAL_NOT_PACKAGED", "EXTERNAL_NOT_PACKAGED", None)
    result = PseudopotentialVerifier().verify(PseudopotentialManifest((entry,)), ("Mn",))
    assert result.status.value == "BLOCKED"
