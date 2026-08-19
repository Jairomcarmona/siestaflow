"""Focused installed-product boundary regressions."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import pytest

import qraft
from qraft.cli import build_parser
from qraft.protocols.single_fdf import resolve_execution_spec


def test_public_help_exposes_only_installed_product_commands() -> None:
    text = build_parser().format_help()
    for command in ("env", "config", "profile", "validate", "plan", "run", "status", "resume"):
        assert command in text
    for legacy in ("project", "environment", "workflow", "examples", "remote"):
        assert f"    {legacy}" not in text


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
