from pathlib import Path

import pytest

from qraft.optical_results import parse_epsimg


def test_parse_epsimg_accepts_comments_and_fortran_exponents(tmp_path: Path) -> None:
    source = tmp_path / "sample.EPSIMG"
    source.write_text("## metadata\n0.0 1.0E-2\n1.0D+00 2.5\n", encoding="utf-8")

    assert parse_epsimg(source) == ((0.0, 0.01), (1.0, 2.5))


@pytest.mark.parametrize("text", ["", "0.0 1.0 2.0\n", "1.0 1.0\n0.0 2.0\n", "bad 1.0\n"])
def test_parse_epsimg_rejects_invalid_rows(tmp_path: Path, text: str) -> None:
    source = tmp_path / "bad.EPSIMG"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        parse_epsimg(source)
