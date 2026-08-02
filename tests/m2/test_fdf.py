from pathlib import Path

import pytest

from siestaflow.engines.siesta.fdf_parser import FDFParser
from siestaflow.engines.siesta.input_validator import SiestaInputValidator
from siestaflow.engines.siesta.models import FDFInclude, FDFUnknown


def test_round_trip_preserves_comments_blocks_includes_unknown_and_windows_eol():
    source = "# c\r\n\r\nSystemLabel Test ! inline\r\n%include other.fdf\r\n%block Demo\r\n  1 2 3\r\n%endblock Demo\r\n@unknown raw\r\n"
    document = FDFParser().parse(source)
    assert document.render() == source
    assert document.newline_style == "\r\n"
    assert any(isinstance(node, FDFInclude) for node in document.nodes)
    assert any(isinstance(node, FDFUnknown) for node in document.nodes)


def test_scalar_parser_preserves_compound_units_and_unqualified_text() -> None:
    document = FDFParser().parse(
        "MD.MaxForceTol 0.05 eV/Ang\nSystemName Water molecule\n"
    )
    force = document.scalars("MD.MaxForceTol")[0]
    name = document.scalars("SystemName")[0]
    assert (force.value, force.unit) == ("0.05", "eV/Ang")
    assert (name.value, name.unit) == ("Water molecule", None)


@pytest.mark.parametrize("source,code", [
    ("%block A\n1\n", "UNCLOSED_BLOCK"),
    ("%endblock A\n", "ORPHAN_ENDBLOCK"),
    ("%block A\n%endblock B\n", "MISMATCHED_ENDBLOCK"),
    ("A 1\nA 2\n", "DUPLICATE_LABEL"),
])
def test_controlled_malformed_diagnostics(source: str, code: str):
    document = FDFParser().parse(source)
    assert document.render() == source
    assert code in {item.code for item in document.diagnostics}


def test_snapshot_all_17_fdfs_parse_without_unclassified_crash(snapshot: Path):
    paths = sorted(path for path in snapshot.rglob("*") if path.is_file() and path.name.endswith((".fdf", ".fdf.NO_RUN", ".fdf.template")))
    assert len(paths) == 17
    for path in paths:
        document = FDFParser().parse_path(path)
        assert document.render().encode("utf-8") == path.read_bytes()
        SiestaInputValidator().validate(document)


def test_sanity_input_is_structurally_consistent(sanity_fdf: Path):
    result = SiestaInputValidator().validate(FDFParser().parse_path(sanity_fdf))
    assert result.status.value == "PASS"
    assert result.atoms == 54
    assert result.species == ("Mn", "O")


def test_atom_count_mismatch_fails(sanity_fdf: Path):
    source = sanity_fdf.read_text(encoding="utf-8").replace("NumberOfAtoms 54", "NumberOfAtoms 53")
    result = SiestaInputValidator().validate(FDFParser().parse(source))
    assert result.status.value == "FAIL"


def test_include_is_preserved_but_blocked_without_path_policy():
    result = SiestaInputValidator().validate(FDFParser().parse("%include x.fdf\n"))
    assert result.status.value == "FAIL"  # required blocks are also absent
    assert any(item.code == "UNRESOLVED_INCLUDE" and item.status.value == "BLOCKED" for item in result.findings)


def test_documented_density_matrix_restart_keyword_is_recognized(sanity_fdf: Path):
    source = sanity_fdf.read_text(encoding="utf-8").replace(
        "MD.Steps 0",
        "DM.UseSaveDM T\nMD.Steps 0",
    )
    result = SiestaInputValidator().validate(FDFParser().parse(source))

    assert not any(
        item.code == "UNKNOWN_LABEL" and item.label == "DM.UseSaveDM"
        for item in result.findings
    )


def test_cg_steps_are_recognized_as_the_explicit_relaxation_step_limit(sanity_fdf: Path):
    source = sanity_fdf.read_text(encoding="utf-8").replace(
        "MD.Steps 0", "MD.NumCGSteps 1"
    )
    result = SiestaInputValidator().validate(FDFParser().parse(source))
    assert not any(
        item.code == "UNKNOWN_LABEL" and "MD.NumCGSteps" in item.message
        for item in result.findings
    )
    assert not any(
        item.code == "UNDECLARED_GOVERNED_VALUE" and "MD.Steps" in item.message
        for item in result.findings
    )
