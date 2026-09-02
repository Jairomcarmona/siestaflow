from __future__ import annotations

import subprocess
from pathlib import Path

from qraft.runtime_compatibility import (
    COMPATIBLE,
    INCOMPATIBLE,
    UNKNOWN,
    evaluate_runtime_compatibility,
)
from qraft.runtime_evidence import observe_runtime_evidence


def test_common_authority_classifies_matching_strict_facts() -> None:
    result = evaluate_runtime_compatibility({
        "engine": {"runtime_instance": "instance-a"},
        "launcher": {"runtime_instance": "instance-a"},
        "environment": {"runtime_instance": "instance-a"},
    })
    assert result == {
        "status": COMPATIBLE,
        "matched_facts": {"runtime_instance": "instance-a"},
        "missing_facts": {},
        "contradictions": {},
    }


def test_common_authority_blocks_only_an_explicit_contradiction() -> None:
    result = evaluate_runtime_compatibility({
        "engine": {"runtime_instance": "instance-a"},
        "launcher": {"runtime_instance": "instance-b"},
        "environment": {},
    })
    assert result["status"] == INCOMPATIBLE
    assert result["contradictions"]["runtime_instance"] == {
        "engine": "instance-a", "launcher": "instance-b",
    }


def test_common_authority_preserves_incomplete_evidence_as_unknown() -> None:
    result = evaluate_runtime_compatibility({
        "engine": {"runtime_instance": "instance-a"},
        "launcher": {},
        "environment": {},
    })
    assert result["status"] == UNKNOWN
    assert result["matched_facts"] == {}
    assert result["missing_facts"] == {
        "runtime_instance": ["environment", "launcher"]
    }


def test_elf_producer_canonicalizes_path_aliases_before_comparison(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    library = runtime / "lib" / "libmpi.so.1"
    library.parent.mkdir(parents=True)
    library.write_text("library", encoding="utf-8")
    engine = tmp_path / "engine"
    launcher = tmp_path / "launcher"
    engine.write_text("engine", encoding="utf-8")
    launcher.write_text("launcher", encoding="utf-8")

    def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed = (
            library
            if Path(argv[1]).name == "engine"
            else library.parent / ".." / "lib" / library.name
        )
        return subprocess.CompletedProcess(
            argv, 0, stdout=f"libmpi.so.1 => {observed} (0x1)\n", stderr=""
        )

    components, conflicts = observe_runtime_evidence(
        str(engine), str(launcher), {"I_MPI_ROOT": str(runtime)},
        which=lambda name: name if name == "ldd" else None,
        runner=runner,
    )
    result = evaluate_runtime_compatibility(components, conflicts)
    assert result["status"] == COMPATIBLE
    assert result["matched_facts"] == {
        "mpi_runtime_instance": str(runtime.resolve())
    }


def test_elf_producer_does_not_promote_unresolved_library_paths_to_facts(
    tmp_path: Path,
) -> None:
    engine = tmp_path / "engine"
    launcher = tmp_path / "launcher"
    engine.write_text("engine", encoding="utf-8")
    launcher.write_text("launcher", encoding="utf-8")

    def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, 0, stdout="libmpi.so.1 => /unobserved/lib/libmpi.so.1 (0x1)\n",
            stderr="",
        )

    components, conflicts = observe_runtime_evidence(
        str(engine), str(launcher), {},
        which=lambda name: name if name == "ldd" else None,
        runner=runner,
    )
    assert evaluate_runtime_compatibility(components, conflicts)["status"] == UNKNOWN
