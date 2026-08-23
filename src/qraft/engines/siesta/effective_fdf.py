"""Effective, non-executing SIESTA FDF closure semantics.

The tokenizer deliberately stays lossless.  This module is the single place
where a tree of FDF files becomes the lexical input seen by SIESTA: includes
are expanded at their position and the first spelling of a label wins.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .fdf_parser import FDFParser
from .models import FDFBlock, FDFDocument, FDFInclude, FDFScalar, normalize_label


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        return handle.read()


def _safe_path(root: Path, owner: Path, target: str) -> Path:
    candidate = (owner.parent / target.strip().strip("\"'")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"scientific include escapes the FDF root: {target}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"included scientific file does not exist: {candidate}")
    return candidate


def _scalar_redirect(label: str, target: Path, newline: str) -> FDFScalar:
    text = target.read_text(encoding="utf-8", errors="surrogateescape").strip()
    if not text or "\n" in text or "\r" in text:
        raise ValueError(f"scalar redirect must contain one value: {target}")
    parsed = FDFParser().parse(f"{label} {text}{newline}")
    scalar = next((item for item in parsed.nodes if isinstance(item, FDFScalar)), None)
    if scalar is None or normalize_label(scalar.label) != normalize_label(label):
        raise ValueError(f"invalid scalar redirect: {target}")
    return scalar


def _block_redirect(name: str, target: Path, newline: str) -> FDFBlock:
    body = target.read_text(encoding="utf-8", errors="surrogateescape")
    if body and not body.endswith(("\n", "\r")):
        body += newline
    parsed = FDFParser().parse(f"%block {name}{newline}{body}%endblock {name}{newline}")
    block = next((item for item in parsed.nodes if isinstance(item, FDFBlock)), None)
    if block is None or not block.closed:
        raise ValueError(f"invalid block redirect: {target}")
    return block


@dataclass(frozen=True)
class EffectiveOccurrence:
    label: str
    kind: str
    owner: Path
    relative_owner: str
    node_index: int
    scalar: FDFScalar | None = None
    block: FDFBlock | None = None
    redirected_from: Path | None = None

    @property
    def raw(self) -> str:
        return self.scalar.raw if self.scalar is not None else self.block.raw if self.block is not None else ""


@dataclass(frozen=True)
class EffectiveFDF:
    root_fdf: Path
    source_root: Path
    fdf_files: dict[str, Path]
    raw_dependencies: dict[str, Path]
    documents: dict[Path, FDFDocument]
    occurrences: dict[str, EffectiveOccurrence]

    def scalar(self, label: str) -> FDFScalar | None:
        occurrence = self.occurrences.get(normalize_label(label))
        return occurrence.scalar if occurrence is not None else None

    def block(self, name: str) -> FDFBlock | None:
        occurrence = self.occurrences.get(normalize_label(name))
        return occurrence.block if occurrence is not None else None

    def occurrence(self, label: str) -> EffectiveOccurrence | None:
        return self.occurrences.get(normalize_label(label))

    @property
    def closure_files(self) -> dict[str, Path]:
        return {**self.fdf_files, **self.raw_dependencies}

    @property
    def closure_sha256(self) -> str:
        payload = "\n".join(f"{name}:{_sha(path)}" for name, path in sorted(self.closure_files.items()))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_effective_fdf(root_fdf: Path) -> EffectiveFDF:
    """Resolve lexical includes and first-appearance precedence without mutation."""

    root_fdf = root_fdf.resolve()
    if not root_fdf.is_file():
        raise FileNotFoundError(f"FDF does not exist: {root_fdf}")
    source_root = root_fdf.parent
    files: dict[str, Path] = {}
    raw_dependencies: dict[str, Path] = {}
    documents: dict[Path, FDFDocument] = {}
    occurrences: dict[str, EffectiveOccurrence] = {}
    visiting: set[Path] = set()

    def record(label: str, kind: str, owner: Path, index: int, *, scalar: FDFScalar | None = None, block: FDFBlock | None = None, redirected_from: Path | None = None) -> None:
        normalized = normalize_label(label)
        if normalized in occurrences:
            return
        occurrences[normalized] = EffectiveOccurrence(
            label=label, kind=kind, owner=owner,
            relative_owner=owner.relative_to(source_root).as_posix(), node_index=index,
            scalar=scalar, block=block, redirected_from=redirected_from,
        )

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in visiting:
            raise ValueError(f"cyclic FDF include detected at {path}")
        if path in documents:
            return
        visiting.add(path)
        document = FDFParser().parse_path(path)
        documents[path] = document
        files[path.relative_to(source_root).as_posix()] = path
        newline = document.newline_style or "\n"
        for index, node in enumerate(document.nodes):
            if isinstance(node, FDFInclude):
                target = _safe_path(source_root, path, node.target)
                if node.directive == "%include":
                    visit(target)
                elif node.label:
                    raw_dependencies[target.relative_to(source_root).as_posix()] = target
                    record(node.label, "scalar", path, index,
                           scalar=_scalar_redirect(node.label, target, newline), redirected_from=target)
                else:
                    raise ValueError(f"unsupported FDF include directive: {node.directive}")
            elif isinstance(node, FDFBlock):
                if node.redirected_to:
                    target = _safe_path(source_root, path, node.redirected_to)
                    raw_dependencies[target.relative_to(source_root).as_posix()] = target
                    record(node.name, "block", path, index,
                           block=_block_redirect(node.name, target, newline), redirected_from=target)
                else:
                    record(node.name, "block", path, index, block=node)
            elif isinstance(node, FDFScalar):
                record(node.label, "scalar", path, index, scalar=node)
        visiting.remove(path)

    visit(root_fdf)
    return EffectiveFDF(root_fdf, source_root, dict(sorted(files.items())), dict(sorted(raw_dependencies.items())), documents, occurrences)


@dataclass(frozen=True)
class MaterializedEffectiveFDF:
    root_fdf: Path
    effective: EffectiveFDF
    file_sha256: dict[str, str]
    closure_sha256: str


def _render_scalar(label: str, value: object, unit: str | None) -> str:
    return f"{label} {value}{f' {unit}' if unit else ''}\n"


def _render_block(label: str, content: str) -> str:
    body = content.rstrip("\r\n")
    return f"%block {label}\n{body}\n%endblock {label}\n"


def materialize_effective_fdf(
    source: Path,
    destination_root: Path,
    *,
    scalar_updates: Mapping[str, tuple[object, str | None]] = {},
    block_updates: Mapping[str, str] = {},
    primary_destination: str | None = None,
) -> MaterializedEffectiveFDF:
    """Clone a closure then alter the first effective definition of each value.

    Direct redirects are replaced in-place by an explicit value/block.  This
    makes the bytes staged to SIESTA and the verified effective value identical.
    """

    original = resolve_effective_fdf(source)
    destination_root = destination_root.resolve()
    all_files = original.closure_files
    def destination_for(source_path: Path) -> Path:
        if source_path.resolve() == original.root_fdf and primary_destination:
            return destination_root / primary_destination
        return destination_root / source_path.relative_to(original.source_root)

    existing_differences: set[Path] = set()
    for relative, source_path in all_files.items():
        destination = destination_for(source_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and _sha(destination) != _sha(source_path):
            existing_differences.add(destination)
        if not destination.exists():
            shutil.copy2(source_path, destination)

    replacements: dict[Path, dict[int, str]] = {}
    appends: list[str] = []
    expected_scalars: dict[str, tuple[str, str | None]] = {}
    expected_blocks: dict[str, str] = {}
    for label, (value, unit) in scalar_updates.items():
        occurrence = original.occurrence(label)
        rendered = _render_scalar(label, value, unit)
        expected_scalars[normalize_label(label)] = (str(value), unit.casefold() if unit else None)
        if occurrence is None:
            appends.append(rendered)
        elif occurrence.kind != "scalar":
            raise ValueError(f"effective FDF label is a block, not a scalar: {label}")
        else:
            replacements.setdefault(occurrence.owner, {})[occurrence.node_index] = rendered
    for label, content in block_updates.items():
        occurrence = original.occurrence(label)
        rendered = _render_block(label, content)
        expected_blocks[normalize_label(label)] = rendered
        if occurrence is None:
            appends.append(rendered)
        elif occurrence.kind != "block":
            raise ValueError(f"effective FDF label is a scalar, not a block: {label}")
        else:
            replacements.setdefault(occurrence.owner, {})[occurrence.node_index] = rendered

    allowed_differences = {destination_for(owner) for owner in replacements}
    if appends:
        allowed_differences.add(destination_for(original.root_fdf))
    collisions = existing_differences - allowed_differences
    if collisions:
        raise ValueError(f"immutable effective closure collision: {sorted(map(str, collisions))[0]}")

    for owner, owner_replacements in replacements.items():
        document = original.documents[owner]
        expected = "".join(owner_replacements.get(index, node.raw) for index, node in enumerate(document.nodes))
        target = destination_for(owner)
        if target.exists() and _read_text(target) != document.render():
            if _read_text(target) != expected:
                raise ValueError(f"immutable effective FDF collision: {target}")
        target.write_text(expected, encoding="utf-8", errors="surrogateescape", newline="")
    if appends:
        root_target = destination_for(original.root_fdf)
        original_text = _read_text(root_target)
        expected = original_text.rstrip("\r\n") + "\n" + "".join(appends)
        root_target.write_text(expected, encoding="utf-8", errors="surrogateescape", newline="")

    rendered = resolve_effective_fdf(destination_for(original.root_fdf))
    for label, (value, unit) in expected_scalars.items():
        scalar = rendered.scalar(label)
        if scalar is None or scalar.value.strip() != value or (scalar.unit.casefold() if scalar.unit else None) != unit:
            raise ValueError(f"effective scalar verification failed: {label}")
    for label, expected in expected_blocks.items():
        block = rendered.block(label)
        if block is None or block.raw != expected:
            raise ValueError(f"effective block verification failed: {label}")
    hashes = {relative: _sha(path) for relative, path in rendered.closure_files.items()}
    return MaterializedEffectiveFDF(rendered.root_fdf, rendered, hashes, rendered.closure_sha256)
