"""Focused installed-product boundary regressions."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
import tomllib

import pytest

import qraft
from qraft.cli import build_parser, public_command_surface
from qraft.protocols.single_fdf import resolve_execution_spec


def test_public_help_exposes_the_installed_product_commands() -> None:
    text = build_parser().format_help()
    compact_help = " ".join(text.split())
    for command in public_command_surface():
        assert f"    {command.name}" in text
        assert command.description in compact_help
    assert "_fdf-run" not in text
    assert "    environment" not in text


def test_mpi_never_invents_a_launcher() -> None:
    with pytest.raises(ValueError, match="MPI execution requested but no launcher"):
        resolve_execution_spec(overrides={
            "partition": "cluster", "mpi_ranks": 4, "executable": "siesta",
        })


def test_profile_and_cli_override_are_the_execution_spec_sources() -> None:
    spec, provenance = resolve_execution_spec(
        profile={
            "partition": "profile", "launcher": "openmpi", "executable": "siesta",
            "nodes": 1, "mpi_ranks": 2,
        },
        overrides={"partition": "cli", "mpi_ranks": 4},
    )
    assert spec.partition == "cli"
    assert spec.mpi_ranks == 4
    assert provenance["partition"] == provenance["mpi_ranks"] == "cli"


def test_version_is_read_from_distribution_metadata() -> None:
    assert qraft.__version__ == version("qraft")


def test_public_runtime_has_no_repo_root_lookup() -> None:
    root = Path(__file__).resolve().parents[2]
    assert "def _repo_root" not in (root / "src/qraft/cli.py").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/Jairomcarmona/siestaflow/blob/main/docs/" in readme


def test_distribution_metadata_declares_bsd_license_and_maintainers() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["license"] == "BSD-3-Clause"
    assert project["license-files"] == ["LICENSE"]
    assert project["authors"] == project["maintainers"]
    assert project["authors"][0]["name"] == "Jairo Carmona"
    assert not any(item.startswith("License ::") for item in project["classifiers"])
    assert project["urls"]["Issues"] == "https://github.com/Jairomcarmona/siestaflow/issues"
    assert (root / "LICENSE").read_text(encoding="utf-8").startswith(
        "Copyright (c) 2026 Jairo Carmona\n\n"
        "Redistribution and use in source and binary forms"
    )
