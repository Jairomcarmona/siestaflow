from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from qraft.contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from qraft.band_paths import (
    BandPathMode,
    BandPathPlanner,
    BandPathRequest,
    BandPathSegment,
    CrystalStructure,
    ProposalStatus,
    ProviderPath,
    SymmetryAnalysis,
)
from qraft.engines.siesta.band_paths import compile_band_path_proposal
from qraft.protocols.electronic_properties import ElectronicPropertiesProtocol, ElectronicStateSource
from qraft.protocols.single_fdf import build_scientific_identity
from qraft.symmetry import SeekPathProvider


SI = CrystalStructure(
    ((5.43, 0.0, 0.0), (0.0, 5.43, 0.0), (0.0, 0.0, 5.43)),
    ((0.0, 0.0, 0.0), (0.25, 0.25, 0.25)),
    (14, 14),
)


def _segments() -> tuple[BandPathSegment, ...]:
    return (
        BandPathSegment("G", (0.0, 0.0, 0.0), "X", (0.5, 0.0, 0.0), 20),
        BandPathSegment("X", (0.5, 0.0, 0.0), "U", (0.5, 0.25, 0.25), 10),
        BandPathSegment("K", (0.375, 0.375, 0.75), "G", (0.0, 0.0, 0.0), 14),
        BandPathSegment("G", (0.0, 0.0, 0.0), "L", (0.5, 0.5, 0.5), 18),
    )


class FakeProvider:
    provider_name = "fake-symmetry"
    provider_version = "1.0"
    spglib_version = "fake-spglib-1.0"

    def __init__(self, *, supercell: bool = False, transform: bool = False, ambiguous: bool = False) -> None:
        self.supercell, self.transform, self.ambiguous = supercell, transform, ambiguous
        self.calls: list[BandPathRequest] = []

    def generate(self, structure: CrystalStructure, request: BandPathRequest) -> ProviderPath:
        self.calls.append(request)
        number = 225 if self.ambiguous and request.symprec > 1.0e-5 else 227
        return ProviderPath(
            SymmetryAnalysis(
                number, "Fd-3m", "cF", self.supercell,
                {"primitive_atom_count": 2}, self.transform,
            ),
            _segments(),
        )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _m6_source(root: Path) -> ElectronicStateSource:
    fdf = root / "si.fdf"
    fdf.write_text(
        """SystemName silicon
SystemLabel silicon
NumberOfAtoms 2
NumberOfSpecies 1
Spin non-polarized
LatticeConstant 1 Ang
%block LatticeVectors
5.43 0 0
0 5.43 0
0 0 5.43
%endblock LatticeVectors
%block ChemicalSpeciesLabel
1 14 Si
%endblock ChemicalSpeciesLabel
AtomicCoordinatesFormat Fractional
%block AtomicCoordinatesAndAtomicSpecies
0 0 0 1
0.25 0.25 0.25 1
%endblock AtomicCoordinatesAndAtomicSpecies
""",
        encoding="utf-8",
    )
    dm = root / "silicon.DM"; dm.write_bytes(b"verified-dm")
    (root / "Si.psf").write_text("pseudo", encoding="utf-8")
    state = ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="test", payload={
        "schema_version": "1.0", "artifact_id": "state", "artifact_type": "qraft.electronic-state",
        "authority": "PROVISIONAL", "engine": "siesta", "final_scf": {
            "input_fdf_sha256": _sha(fdf), "scientific_identity_sha256": build_scientific_identity(fdf).fingerprint,
            "system_label": "silicon", "density_matrix": {"filename": dm.name, "sha256": _sha(dm)},
        },
    }).to_dict()
    state_path = root / "electronic-state.json"; state_path.write_text(json.dumps(state), encoding="utf-8")
    return ElectronicStateSource.load(state_path, final_fdf=fdf, density_matrix=dm)


def _dos_specs() -> tuple[object, object]:
    from qraft.engines.siesta.electronic_properties import DosSpec, PdosSpec
    grid = ((1, 0, 0, 0.0), (0, 1, 0, 0.0), (0, 0, 1, 0.0))
    return DosSpec("EF", -2.0, 2.0, 0.1, 4, "eV", grid), PdosSpec("EF", -2.0, 2.0, 0.1, 4, "eV", grid)


def _request(mode: BandPathMode, **changes: object) -> BandPathRequest:
    changes.setdefault("time_reversal_evidence", True)
    return BandPathRequest(mode, structure=SI, **changes)


def test_manual_is_exact_provider_free_and_disconnected() -> None:
    manual = BandPathRequest(BandPathMode.MANUAL, manual_segments=_segments())
    proposal = BandPathPlanner().propose(manual)
    spec = compile_band_path_proposal(proposal)

    assert proposal.status is ProposalStatus.READY
    assert proposal.provenance.provider is None
    assert proposal.segments == _segments()
    assert [[vertex.label for vertex in group] for group in spec.ordered_segments] == [["G", "X", "U"], ["K", "G", "L"]]
    rendered = spec.render_block().splitlines()
    assert rendered[2].endswith(" U")
    assert rendered[3].startswith("  1 ") and rendered[3].endswith(" K")
    assert " U\n  14 " not in spec.render_block()


def test_manual_coordinates_and_labels_are_not_canonicalized_away() -> None:
    segment = BandPathSegment("Γ", (0.0, 0.0, 0.0), "X", (0.5, 0.0, 0.5), 30)
    proposal = BandPathPlanner().propose(BandPathRequest(BandPathMode.MANUAL, manual_segments=(segment,)))
    assert proposal.segments[0].start_label == "Γ"
    assert proposal.segments[0].end_coordinates == (0.5, 0.0, 0.5)
    assert compile_band_path_proposal(proposal).render_block().endswith(" X")


def test_suggest_is_non_destructive_and_records_deterministic_provenance() -> None:
    provider = FakeProvider()
    request = _request(BandPathMode.SUGGEST, time_reversal="false")
    first = BandPathPlanner(provider).propose(request)
    second = BandPathPlanner(provider).propose(request)

    assert first.status is ProposalStatus.READY
    assert first.sha256 == second.sha256
    assert first.provenance.input_geometry_hash == SI.sha256
    assert first.provenance.time_reversal == "false"
    assert first.provenance.stability.value == "SYMMETRY_STABLE"
    assert len(provider.calls) == 6  # three tolerance probes per non-destructive proposal
    assert "proposal_sha256" in first.to_json()


def test_automatic_compiles_stable_primitive_si_deterministically() -> None:
    provider = FakeProvider()
    request = _request(BandPathMode.AUTOMATIC)
    first = BandPathPlanner(provider).resolve(request, compile_band_path_proposal)
    second = BandPathPlanner(provider).resolve(request, compile_band_path_proposal)

    assert first.proposal.status is ProposalStatus.READY
    assert first.proposal.sha256 == second.proposal.sha256
    assert first.band_path_spec is not None
    assert first.band_path_spec.sha256 == second.band_path_spec.sha256
    assert len(first.band_path_spec.ordered_segments) == 2


@pytest.mark.parametrize("mode, expected", [(BandPathMode.SUGGEST, ProposalStatus.REVIEW), (BandPathMode.AUTOMATIC, ProposalStatus.BLOCKED)])
def test_supercell_policy_is_review_for_suggest_and_block_for_automatic(mode: BandPathMode, expected: ProposalStatus) -> None:
    proposal = BandPathPlanner(FakeProvider(supercell=True)).propose(_request(mode))
    assert proposal.status is expected
    assert "supercell" in (proposal.reason or "")


@pytest.mark.parametrize("mode, expected", [(BandPathMode.SUGGEST, ProposalStatus.REVIEW), (BandPathMode.AUTOMATIC, ProposalStatus.BLOCKED)])
def test_symmetry_ambiguity_is_review_for_suggest_and_block_for_automatic(mode: BandPathMode, expected: ProposalStatus) -> None:
    proposal = BandPathPlanner(FakeProvider(ambiguous=True)).propose(_request(mode))
    assert proposal.status is expected
    assert proposal.provenance.stability.value == "SYMMETRY_AMBIGUOUS"


def test_automatic_blocks_structure_transform_and_missing_provider() -> None:
    transformed = BandPathPlanner(FakeProvider(transform=True)).propose(_request(BandPathMode.AUTOMATIC))
    unavailable = BandPathPlanner().propose(_request(BandPathMode.AUTOMATIC))
    assert transformed.status is ProposalStatus.BLOCKED
    assert "transformed structure" in (transformed.reason or "")
    assert unavailable.status is ProposalStatus.BLOCKED
    assert "qraft[symmetry]" in (unavailable.reason or "")


def test_time_reversal_and_scientific_parameters_are_hash_bound() -> None:
    provider = FakeProvider()
    auto = BandPathPlanner(provider).propose(_request(BandPathMode.SUGGEST, time_reversal="auto"))
    explicit = BandPathPlanner(provider).propose(_request(BandPathMode.SUGGEST, time_reversal="true"))
    denser = BandPathPlanner(provider).propose(_request(BandPathMode.SUGGEST, reference_distance=0.05))
    changed_symprec = BandPathPlanner(provider).propose(_request(BandPathMode.SUGGEST, symprec=2.0e-5))
    assert auto.provenance.time_reversal == "auto"
    assert explicit.provenance.time_reversal == "true"
    assert auto.sha256 != explicit.sha256
    assert auto.sha256 != denser.sha256
    assert auto.sha256 != changed_symprec.sha256


def test_invalid_manual_segment_and_no_accidental_bridge_fail_closed() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        BandPathSegment("G", (0, 0, 0), "X", (0.5, 0, 0), 0)
    proposal = BandPathPlanner().propose(BandPathRequest(BandPathMode.MANUAL, manual_segments=_segments()))
    spec = compile_band_path_proposal(proposal)
    assert tuple(group[-1].label for group in spec.ordered_segments) == ("U", "L")
    assert spec.ordered_segments[1][0].label == "K"


def test_automatic_uses_verified_m6_geometry_and_persists_provenance(tmp_path: Path) -> None:
    source = _m6_source(tmp_path)
    dos, pdos = _dos_specs()
    prepared = ElectronicPropertiesProtocol().prepare(
        source, bands=BandPathRequest(BandPathMode.AUTOMATIC), dos=dos, pdos=pdos,
        runs_root=tmp_path / "m7", band_path_provider=FakeProvider(),
    )
    assert prepared.band_path_resolution is not None
    assert prepared.band_path_resolution.proposal.provenance.input_geometry_hash == SI.sha256
    evidence = json.loads((prepared.source_root / "bands" / "band-path-proposal.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "READY"
    assert evidence["band_path_spec"]["segments"][1][0]["label"] == "K"


def test_automatic_rejects_geometry_that_does_not_match_verified_m6_parent(tmp_path: Path) -> None:
    source = _m6_source(tmp_path)
    dos, pdos = _dos_specs()
    incompatible = CrystalStructure(SI.cell, ((0.0, 0.0, 0.0), (0.2, 0.2, 0.2)), SI.atomic_numbers)
    with pytest.raises(ValueError, match="does not match the verified M6 final geometry"):
        ElectronicPropertiesProtocol().prepare(
            source, bands=BandPathRequest(BandPathMode.AUTOMATIC, structure=incompatible), dos=dos, pdos=pdos,
            runs_root=tmp_path / "m7", band_path_provider=FakeProvider(),
        )


def _install_real_api_shape(
    monkeypatch: pytest.MonkeyPatch,
    *,
    structure: CrystalStructure = SI,
    expected_time_reversal: bool = True,
    fail: bool = False,
) -> SimpleNamespace:
    calls: list[str] = []
    path = {
        "point_coords": {"G": [0.0, 0.0, 0.0], "X": [0.5, 0.0, 0.0], "U": [0.5, 0.25, 0.25], "K": [0.375, 0.375, 0.75]},
        "path": [("G", "X"), ("X", "U"), ("K", "G")],
        "augmented_path": True,
        "has_inversion_symmetry": False,
        "is_supercell": False,
        "spacegroup_number": 227,
        "spacegroup_international": "Fd-3m",
        "bravais_lattice": "cF",
    }
    explicit = {
        "explicit_kpoints_rel": [
            [0.0, 0.0, 0.0], [0.25, 0.0, 0.0], [0.5, 0.0, 0.0],
            [0.25, 0.125, 0.125], [0.5, 0.25, 0.25],
            [0.375, 0.375, 0.75], [0.1875, 0.1875, 0.375], [0.0, 0.0, 0.0],
        ],
        "explicit_kpoints_labels": ["G", None, "X", None, "U", "K", None, "G"],
        # SeeK-path semantics are [start, stop): X is shared, U|K is a break.
        "explicit_segments": [(0, 3), (2, 5), (5, 8)],
    }

    def get_path_orig_cell(structure: object, **kwargs: object) -> dict[str, object]:
        calls.append("path_orig")
        assert structure == ([list(row) for row in expected_structure.cell], [list(row) for row in expected_structure.fractional_positions], list(expected_structure.atomic_numbers))
        assert kwargs["with_time_reversal"] is expected_time_reversal
        return path

    def get_explicit_k_path_orig_cell(structure: object, **kwargs: object) -> dict[str, object]:
        calls.append("explicit_orig")
        assert kwargs["reference_distance"] == 0.025
        if fail:
            raise RuntimeError("installed provider failed")
        return explicit

    expected_structure = structure
    fake_seekpath = SimpleNamespace(
        __version__="2.2.1-test", get_path_orig_cell=get_path_orig_cell,
        get_explicit_k_path_orig_cell=get_explicit_k_path_orig_cell,
        get_path=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("standardizing API used")),
        get_explicit_k_path=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("standardizing API used")),
    )
    monkeypatch.setitem(sys.modules, "seekpath", fake_seekpath)
    monkeypatch.setitem(sys.modules, "spglib", SimpleNamespace(__version__="2.6.0-test"))
    return SimpleNamespace(calls=calls)


def test_seekpath_original_cell_api_preserves_real_explicit_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install_real_api_shape(monkeypatch)
    proposal = BandPathPlanner(SeekPathProvider()).propose(_request(BandPathMode.AUTOMATIC, time_reversal="true"))
    spec = compile_band_path_proposal(proposal)

    assert recorder.calls == ["path_orig", "explicit_orig"] * 3
    assert proposal.status is ProposalStatus.READY
    assert [(segment.start_label, segment.end_label) for segment in proposal.segments] == [("G", "X"), ("X", "U"), ("K", "G")]
    result = proposal.provenance.symmetry_results[1]
    assert result["path"] == [["G", "X"], ["X", "U"], ["K", "G"]]
    assert result["point_coords"]["K"] == ["0.375", "0.375", "0.75"]
    assert result["augmented_path"] is True
    assert result["has_inversion_symmetry"] is False
    assert result["explicit_segments"] == [[0, 3], [2, 5], [5, 8]]
    assert [[vertex.label for vertex in group] for group in spec.ordered_segments] == [["G", "X", "U"], ["K", "G"]]


@pytest.mark.parametrize("mode, expected", [(BandPathMode.SUGGEST, ProposalStatus.REVIEW), (BandPathMode.AUTOMATIC, ProposalStatus.BLOCKED)])
def test_time_reversal_auto_without_verified_parent_evidence_fails_closed(mode: BandPathMode, expected: ProposalStatus) -> None:
    request = BandPathRequest(mode, structure=SI, time_reversal="auto")
    proposal = BandPathPlanner(FakeProvider()).propose(request)
    assert proposal.status is expected
    assert "TIME_REVERSAL_UNRESOLVED" in (proposal.reason or "")


def test_installed_provider_failure_is_not_classified_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_real_api_shape(monkeypatch, fail=True)
    proposal = BandPathPlanner(SeekPathProvider()).propose(_request(BandPathMode.AUTOMATIC, time_reversal="true"))
    assert proposal.status is ProposalStatus.BLOCKED
    assert proposal.provenance.provider_error_code == "PROVIDER_EXECUTION_ERROR"
    assert "PROVIDER_UNAVAILABLE" not in (proposal.reason or "")


def test_original_cell_provider_does_not_use_same_atom_count_transformation_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    reoriented = CrystalStructure(
        ((0.0, 5.43, 0.0), (5.43, 0.0, 0.0), (0.0, 0.0, 5.43)),
        SI.fractional_positions, SI.atomic_numbers,
    )
    recorder = _install_real_api_shape(monkeypatch, structure=reoriented)
    result = SeekPathProvider().generate(
        reoriented, BandPathRequest(BandPathMode.AUTOMATIC, structure=reoriented, time_reversal="true"),
    )
    assert recorder.calls == ["path_orig", "explicit_orig"]
    assert result.analysis.transformation_required is False
    assert result.analysis.primitive_mapping == {"input_cell_preserved": True}


def test_explicit_false_time_reversal_reaches_seekpath(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_real_api_shape(monkeypatch, expected_time_reversal=False)
    proposal = BandPathPlanner(SeekPathProvider()).propose(_request(BandPathMode.SUGGEST, time_reversal="false"))
    assert proposal.status is ProposalStatus.READY
    assert proposal.provenance.resolved_time_reversal is False
