"""Pure, hashable SIESTA scientific-input closure composition."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ...contracts import ArtifactRole
from .fdf_parser import FDFParser
from .models import FDFBlock, FDFInclude


def sha_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_scientific_path(root: Path, owner: Path, target: str) -> Path:
    candidate = (owner.parent / str(target).strip().strip("\"'")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"scientific include escapes the FDF root: {target}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"included scientific file does not exist: {candidate}")
    return candidate


def collect_fdf_files(root_fdf: Path) -> tuple[Path, dict[str, Path], list[Any]]:
    """Resolve the primary FDF plus its recursive includes/redirections."""

    root_fdf = root_fdf.resolve()
    if not root_fdf.is_file():
        raise FileNotFoundError(f"FDF does not exist: {root_fdf}")
    root = root_fdf.parent
    files: dict[str, Path] = {}
    documents: list[Any] = []
    visiting: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in visiting:
            raise ValueError(f"cyclic FDF include detected at {resolved}")
        relative = resolved.relative_to(root).as_posix()
        if relative in files:
            return
        visiting.add(resolved)
        document = FDFParser().parse_path(resolved)
        files[relative] = resolved
        documents.append(document)
        targets = [
            node.target if isinstance(node, FDFInclude) else node.redirected_to
            for node in document.nodes
            if isinstance(node, FDFInclude) or (isinstance(node, FDFBlock) and node.redirected_to)
        ]
        for target in targets:
            visit(_safe_scientific_path(root, resolved, str(target)))
        visiting.remove(resolved)

    visit(root_fdf)
    return root, dict(sorted(files.items())), documents


def _block_payloads(documents: Sequence[Any], names: set[str]) -> list[str]:
    normalized = {"".join(c.lower() for c in name if c not in ".-_ ") for name in names}
    return [
        block.raw
        for document in documents
        for block in document.blocks()
        if "".join(c.lower() for c in block.name if c not in ".-_ ") in normalized
    ]


def species(documents: Sequence[Any]) -> tuple[str, ...]:
    labels: list[str] = []
    for payload in _block_payloads(documents, {"ChemicalSpeciesLabel"}):
        for line in payload.splitlines()[1:-1]:
            tokens = line.split("#", 1)[0].strip().split()
            if len(tokens) >= 3:
                labels.append(tokens[2])
    if not labels:
        raise ValueError("ChemicalSpeciesLabel must declare at least one species")
    if len({label.casefold() for label in labels}) != len(labels):
        raise ValueError("ChemicalSpeciesLabel contains duplicate species labels")
    return tuple(labels)


def resolve_pseudopotentials(root: Path, labels: Sequence[str], pseudo_manifest: Path | None) -> dict[str, Path]:
    manifest_entries: dict[str, Path] = {}
    if pseudo_manifest is not None:
        source = pseudo_manifest.resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError("pseudopotential manifest requires an entries list")
        for item in entries:
            if not isinstance(item, dict) or not str(item.get("species", "")).strip():
                raise ValueError("invalid pseudopotential manifest entry")
            value = item.get("path") or item.get("filename")
            if not value:
                raise ValueError(f"pseudopotential path missing for {item.get('species')}")
            candidate = Path(str(value))
            manifest_entries[str(item["species"]).casefold()] = (
                candidate if candidate.is_absolute() else source.parent / candidate
            ).resolve()
    resolved: dict[str, Path] = {}
    for label in labels:
        candidates = (
            [manifest_entries[label.casefold()]] if manifest_entries and label.casefold() in manifest_entries
            else [root / f"{label}.{extension}" for extension in ("psml", "psf")]
        )
        found = [candidate.resolve() for candidate in candidates if candidate.is_file()]
        if len(found) != 1:
            raise ValueError(f"exactly one psml/psf pseudopotential is required for {label}; found {len(found)}")
        resolved[label] = found[0]
    return resolved


@dataclass(frozen=True)
class ScientificInputEntry:
    name: str
    source: Path
    destination: str
    role: ArtifactRole
    media_type: str


@dataclass(frozen=True)
class ScientificInputClosure:
    source_root: Path
    fdf_files: dict[str, Path]
    pseudopotentials: dict[str, Path]
    entries: tuple[ScientificInputEntry, ...]


def resolve_scientific_input_closure(
    fdf: Path, *, pseudo_manifest: Path | None = None, primary_destination: str | None = None,
    include_pseudo_manifest: bool = False,
) -> ScientificInputClosure:
    """Return canonical, non-executing source/destination bindings for SIESTA."""

    root, files, documents = collect_fdf_files(fdf)
    root_fdf = fdf.resolve()
    pseudos = resolve_pseudopotentials(root, species(documents), pseudo_manifest)
    entries = [ScientificInputEntry("fdf", root_fdf, primary_destination or root_fdf.name, ArtifactRole.INPUT, "application/x-siesta-fdf")]
    entries.extend(
        ScientificInputEntry(f"include-{index:03d}", source, relative, ArtifactRole.INPUT, "application/x-siesta-fdf")
        for index, (relative, source) in enumerate(files.items(), start=1)
        if source.resolve() != root_fdf
    )
    entries.extend(
        ScientificInputEntry(f"pseudo-{index:03d}", source, source.name, ArtifactRole.PSEUDOPOTENTIAL, "application/x-siesta-pseudopotential")
        for index, source in enumerate(sorted(pseudos.values()), start=1)
    )
    if pseudo_manifest is not None and include_pseudo_manifest:
        manifest = pseudo_manifest.resolve()
        entries.append(ScientificInputEntry("pseudo-manifest", manifest, manifest.name, ArtifactRole.INPUT, "application/json"))
    destinations = [entry.destination for entry in entries]
    if len(destinations) != len(set(destinations)):
        raise ValueError("single-FDF canonical input destinations collide")
    source_root = Path(os.path.commonpath([str(entry.source.parent) for entry in entries]))
    return ScientificInputClosure(source_root, files, pseudos, tuple(entries))
