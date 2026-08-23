from __future__ import annotations

from pathlib import Path

import pytest

from qraft.engines.siesta.effective_fdf import materialize_effective_fdf, resolve_effective_fdf
from qraft.engines.siesta.input_closure import effective_species


def _oracle_first_values(root: Path) -> dict[str, str]:
    """Tiny independent lexical oracle: it intentionally does not use QRAFT parsing."""

    seen: dict[str, str] = {}

    def visit(path: Path) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "!", ";")):
                continue
            if stripped.casefold().startswith("%include "):
                visit((path.parent / stripped.split(None, 1)[1]).resolve())
                continue
            if stripped.startswith("%"):
                continue
            label, *value = stripped.split()
            seen.setdefault("".join(char.lower() for char in label if char not in ".-_ "), " ".join(value))

    visit(root)
    return seen


def test_lexical_first_win_nested_includes_and_effective_species(tmp_path: Path) -> None:
    root = tmp_path / "input.fdf"
    defaults = tmp_path / "defaults.fdf"
    species = tmp_path / "species.fdf"
    root.write_text("%include defaults.fdf\nMesh.Cutoff 350 Ry\n%include species.fdf\n", encoding="utf-8")
    defaults.write_text("Mesh.Cutoff 100 Ry\n%include nested.fdf\n", encoding="utf-8")
    (tmp_path / "nested.fdf").write_text("PAO.BasisSize DZ\n", encoding="utf-8")
    species.write_text("%block ChemicalSpeciesLabel\n1 6 C\n%endblock ChemicalSpeciesLabel\n", encoding="utf-8")

    oracle = _oracle_first_values(root)
    effective = resolve_effective_fdf(root)
    assert oracle["meshcutoff"] == "100 Ry"
    assert effective.scalar("mesh_cutoff").value == "100"
    assert effective.scalar("PAO.BasisSize").value == "DZ"
    assert effective_species(effective) == ("C",)


def test_materialization_updates_the_first_effective_redirected_values(tmp_path: Path) -> None:
    root = tmp_path / "input.fdf"
    defaults = tmp_path / "defaults.fdf"
    root.write_text("%include defaults.fdf\nMesh.Cutoff 350 Ry\n%block kgrid.MonkhorstPack < grid.dat\n", encoding="utf-8")
    defaults.write_text("Mesh.Cutoff < mesh.value\n", encoding="utf-8")
    (tmp_path / "mesh.value").write_text("100 Ry\n", encoding="utf-8")
    (tmp_path / "grid.dat").write_text("1 0 0 0.0\n0 1 0 0.0\n0 0 1 0.0\n", encoding="utf-8")

    rendered = materialize_effective_fdf(
        root, tmp_path / "rendered", primary_destination="input.fdf",
        scalar_updates={"Mesh.Cutoff": (300, "Ry")},
        block_updates={"kgrid.MonkhorstPack": "3 0 0 0.0\n0 3 0 0.0\n0 0 3 0.0"},
    )
    result = rendered.effective
    assert result.scalar("Mesh.Cutoff").value == "300"
    assert "Mesh.Cutoff 300 Ry" in (tmp_path / "rendered" / "defaults.fdf").read_text(encoding="utf-8")
    assert "< grid.dat" not in (tmp_path / "rendered" / "input.fdf").read_text(encoding="utf-8")
    assert result.block("kgrid.MonkhorstPack") is not None
    assert (tmp_path / "rendered" / "grid.dat").is_file()


def test_effective_resolution_fails_closed_for_cycles_and_root_escapes(tmp_path: Path) -> None:
    root = tmp_path / "input.fdf"
    root.write_text("%include nested.fdf\n", encoding="utf-8")
    (tmp_path / "nested.fdf").write_text("%include input.fdf\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cyclic"):
        resolve_effective_fdf(root)
    (tmp_path / "nested.fdf").write_text("%include ../outside.fdf\n", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        resolve_effective_fdf(root)
