from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from qraft.engines.siesta.effective_fdf import materialize_effective_fdf, resolve_effective_fdf
from qraft.engines.siesta.input_closure import effective_species
from qraft.protocols.single_fdf import build_scientific_identity


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


def _closure_hashes(root: Path) -> dict[str, str]:
    closure = resolve_effective_fdf(root)
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in closure.closure_files.items()}


def _absent_source(root: Path) -> Path:
    root.mkdir()
    fdf = root / "main.fdf"
    fdf.write_text(
        "SystemLabel deterministic\nNumberOfSpecies 1\n"
        "%block ChemicalSpeciesLabel\n1 6 C\n%endblock ChemicalSpeciesLabel\n",
        encoding="utf-8",
    )
    (root / "C.psf").write_text("pseudo\n", encoding="utf-8")
    return fdf


def test_absent_updates_are_byte_idempotent_and_keep_identity_stable(tmp_path: Path) -> None:
    source = _absent_source(tmp_path / "source")
    source_before = _closure_hashes(source)
    rendered_root = tmp_path / "rendered"
    updates = {"Mesh.Cutoff": (350, "Ry"), "PAO.EnergyShift": (300, "meV")}
    first = materialize_effective_fdf(source, rendered_root, scalar_updates=updates, primary_destination="input.fdf")
    shutil.copy2(source.parent / "C.psf", rendered_root / "C.psf")
    first_bytes = {path.relative_to(rendered_root).as_posix(): path.read_bytes() for path in rendered_root.rglob("*") if path.is_file()}
    first_identity = build_scientific_identity(first.root_fdf)
    second = materialize_effective_fdf(source, rendered_root, scalar_updates=updates, primary_destination="input.fdf")
    second_bytes = {path.relative_to(rendered_root).as_posix(): path.read_bytes() for path in rendered_root.rglob("*") if path.is_file()}
    assert first_bytes == second_bytes
    assert first.file_sha256 == second.file_sha256 and first.closure_sha256 == second.closure_sha256
    assert first_identity == build_scientific_identity(second.root_fdf)
    assert second.root_fdf.read_text(encoding="utf-8").count("Mesh.Cutoff 350 Ry") == 1
    assert second.root_fdf.read_text(encoding="utf-8").count("PAO.EnergyShift 300 meV") == 1
    assert _closure_hashes(source) == source_before


def test_tampered_render_is_rejected_without_overwriting_or_partial_writes(tmp_path: Path) -> None:
    source = _absent_source(tmp_path / "source")
    rendered_root = tmp_path / "rendered"
    materialize_effective_fdf(source, rendered_root, scalar_updates={"Mesh.Cutoff": (350, "Ry")})
    target = rendered_root / "main.fdf"
    target.write_text("tampered\n", encoding="utf-8")
    before = {path.relative_to(rendered_root).as_posix(): path.read_bytes() for path in rendered_root.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="immutable"):
        materialize_effective_fdf(source, rendered_root, scalar_updates={"Mesh.Cutoff": (350, "Ry")})
    after = {path.relative_to(rendered_root).as_posix(): path.read_bytes() for path in rendered_root.rglob("*") if path.is_file()}
    assert after == before


def test_destination_collisions_fail_before_creating_output(tmp_path: Path) -> None:
    include_root = tmp_path / "include"; include_root.mkdir()
    main = include_root / "main.fdf"
    main.write_text("%include input.fdf\n", encoding="utf-8")
    (include_root / "input.fdf").write_text("Mesh.Cutoff 100 Ry\n", encoding="utf-8")
    include_destination = tmp_path / "include-rendered"
    with pytest.raises(ValueError, match="destination collision"):
        materialize_effective_fdf(main, include_destination, primary_destination="input.fdf")
    assert not include_destination.exists()

    redirect_root = tmp_path / "redirect"; redirect_root.mkdir()
    redirected = redirect_root / "main.fdf"
    redirected.write_text("Mesh.Cutoff < input.fdf\n", encoding="utf-8")
    (redirect_root / "input.fdf").write_text("100 Ry\n", encoding="utf-8")
    redirect_destination = tmp_path / "redirect-rendered"
    with pytest.raises(ValueError, match="destination collision"):
        materialize_effective_fdf(redirected, redirect_destination, primary_destination="input.fdf")
    assert not redirect_destination.exists()


def test_noncolliding_primary_rename_preserves_topology(tmp_path: Path) -> None:
    source_root = tmp_path / "source"; source_root.mkdir()
    main = source_root / "main.fdf"
    main.write_text("%include defaults.fdf\n", encoding="utf-8")
    (source_root / "defaults.fdf").write_text("Mesh.Cutoff 100 Ry\n", encoding="utf-8")
    rendered = materialize_effective_fdf(main, tmp_path / "rendered", primary_destination="input.fdf", scalar_updates={"Mesh.Cutoff": (350, "Ry")})
    assert rendered.root_fdf.name == "input.fdf"
    assert (tmp_path / "rendered" / "defaults.fdf").is_file()
    assert rendered.effective.scalar("Mesh.Cutoff").value == "350"
