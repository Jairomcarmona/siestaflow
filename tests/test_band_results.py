from pathlib import Path

import pytest

from siestaflow.band_results import parse_bands


def test_parse_bands_accepts_wrapped_eigenvalues(tmp_path: Path) -> None:
    source = tmp_path / "sample.bands"
    source.write_text("""0.5
0.0 1.0
-2.0 3.0
2 1 2
0.0 -1.0 1.0
0.5 -0.5
2.0
2
0.0 'G'
0.5 'X'
""", encoding="utf-8")

    parsed = parse_bands(source)

    assert (parsed.fermi_energy_eV, parsed.bands, parsed.spins, parsed.k_points) == (0.5, 2, 1, 2)
    assert parsed.rows == ((0.0, 1, 1, 1, -1.0), (0.0, 1, 1, 2, 1.0), (0.5, 2, 1, 1, -0.5), (0.5, 2, 1, 2, 2.0))


@pytest.mark.parametrize("text", ["0\n", "0\n0 1\n-1 1\n2 1 2\n0 -1\n", "0\n0 1\n-1 1\n2 1 1\n0 -1 1\n"])
def test_parse_bands_rejects_truncated_layout(tmp_path: Path, text: str) -> None:
    source = tmp_path / "bad.bands"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        parse_bands(source)
