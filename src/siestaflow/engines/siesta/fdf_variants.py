"""Single-variable, hash-bound FDF technical variants."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from ...authorization import AuthorizationEngine
from ...models import AuthorizationEnvelope
from .fdf_parser import FDFParser
from .fdf_registry import FDFRegistry
from .models import FDFBlock, FDFScalar, normalize_label


@dataclass(frozen=True)
class VariantAuthorization:
    envelope: AuthorizationEnvelope
    base_fdf_sha256: str
    allowed_parameter: str
    allowed_values: tuple[str, ...]
    synthetic_only: bool
    content_hash: str

    @classmethod
    def issue(
        cls,
        envelope: AuthorizationEnvelope,
        *,
        base_fdf_sha256: str,
        allowed_parameter: str,
        allowed_values: tuple[str, ...],
        synthetic_only: bool,
    ) -> "VariantAuthorization":
        payload = {
            "authorization_id": envelope.authorization_id,
            "base_fdf_sha256": base_fdf_sha256,
            "allowed_parameter": normalize_label(allowed_parameter),
            "allowed_values": list(allowed_values),
            "synthetic_only": synthetic_only,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return cls(envelope, base_fdf_sha256, allowed_parameter, allowed_values, synthetic_only, digest)

    def verify(self) -> None:
        AuthorizationEngine().verify(self.envelope)
        expected = self.issue(
            self.envelope, base_fdf_sha256=self.base_fdf_sha256,
            allowed_parameter=self.allowed_parameter, allowed_values=self.allowed_values,
            synthetic_only=self.synthetic_only,
        ).content_hash
        if expected != self.content_hash:
            raise PermissionError("variant authorization content hash mismatch")


@dataclass(frozen=True)
class FDFVariant:
    parameter: str
    value: str
    text: str
    sha256: str
    textual_diff: str
    semantic_diff: dict[str, Any]
    manifest: dict[str, Any]
    provenance: dict[str, Any]


class FDFVariantGenerator:
    def __init__(self, registry: FDFRegistry | None = None) -> None:
        self.registry = registry or FDFRegistry.load_default()
        self.parser = FDFParser()

    def generate(self, base_text: str, authorization: VariantAuthorization, value: str) -> FDFVariant:
        authorization.verify()
        actual_hash = hashlib.sha256(base_text.encode("utf-8", errors="surrogateescape")).hexdigest()
        if actual_hash != authorization.base_fdf_sha256:
            raise PermissionError("base FDF hash differs from authorization")
        self.registry.require_mutable(authorization.allowed_parameter)
        if value not in authorization.allowed_values:
            raise PermissionError(f"value is not authorized: {value}")
        parameter = authorization.allowed_parameter
        if normalize_label(parameter) == normalize_label("Mesh.Cutoff"):
            match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s+([A-Za-z][A-Za-z0-9_-]*)", value.strip())
            if not match or float(match.group(1)) <= 0:
                raise ValueError("Mesh.Cutoff must be an authorized positive number and unit")
            variant_text = self._replace_scalar(base_text, parameter, value)
        elif normalize_label(parameter) == normalize_label("kgrid.MonkhorstPack"):
            if not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*x[1-9][0-9]*", value):
                raise ValueError("k-grid must be an authorized NxNxN positive integer triplet")
            variant_text = self._replace_kgrid(base_text, value)
        else:
            raise PermissionError(f"parameter has no controlled variant renderer: {parameter}")
        changed = self.verify_single_change(base_text, variant_text, parameter)
        diff = "".join(difflib.unified_diff(
            base_text.splitlines(keepends=True), variant_text.splitlines(keepends=True),
            fromfile="base.fdf", tofile=f"{normalize_label(parameter)}_{value}.fdf",
        ))
        digest = hashlib.sha256(variant_text.encode("utf-8", errors="surrogateescape")).hexdigest()
        manifest = {
            "base_sha256": actual_hash, "variant_sha256": digest,
            "allowed_parameter": parameter, "allowed_value": value,
            "authorization_hash": authorization.content_hash, "single_variable": True,
            "synthetic_only": authorization.synthetic_only,
        }
        return FDFVariant(parameter, value, variant_text, digest, diff, changed, manifest, {
            "authorization_id": authorization.envelope.authorization_id,
            "generator": "SIESTAFLOW_M2_CONTROLLED_VARIANT",
        })

    def generate_series(self, base_text: str, authorization: VariantAuthorization) -> tuple[FDFVariant, ...]:
        return tuple(self.generate(base_text, authorization, value) for value in authorization.allowed_values)

    def verify_single_change(self, base_text: str, variant_text: str, allowed_parameter: str) -> dict[str, Any]:
        base = _semantic_map(self.parser.parse(base_text))
        variant = _semantic_map(self.parser.parse(variant_text))
        keys = set(base) | set(variant)
        changed = sorted(key for key in keys if base.get(key) != variant.get(key))
        allowed = normalize_label(allowed_parameter)
        # An authorized value may equal the base.  That is an explicit
        # zero-diff baseline, not a second semantic change.
        if changed not in ([], [allowed]):
            raise PermissionError(f"variant changed unauthorized parameters: {changed}")
        return {
            "changed_parameters": changed,
            "authorized_parameter": allowed,
            "baseline": not changed,
            "before": base[allowed],
            "after": variant[allowed],
        }

    def _replace_scalar(self, text: str, parameter: str, value: str) -> str:
        document = self.parser.parse(text)
        nodes = document.scalars(parameter)
        if len(nodes) != 1:
            raise ValueError(f"expected exactly one {parameter} scalar")
        node = nodes[0]
        eol = "\r\n" if node.raw.endswith("\r\n") else "\n" if node.raw.endswith("\n") else ""
        indent = node.raw[: len(node.raw) - len(node.raw.lstrip())]
        replacement = f"{indent}{node.label} {value}{eol}"
        return _replace_node(document, node, replacement)

    def _replace_kgrid(self, text: str, value: str) -> str:
        document = self.parser.parse(text)
        blocks = document.blocks("kgrid.MonkhorstPack")
        if len(blocks) != 1 or not blocks[0].closed:
            raise ValueError("expected exactly one closed kgrid.MonkhorstPack block")
        block = blocks[0]
        dims = tuple(int(item) for item in value.split("x"))
        eol = "\r\n" if block.header.endswith("\r\n") else "\n"
        indent = "  "
        body = (
            f"{indent}{dims[0]} 0 0 0.0{eol}",
            f"{indent}0 {dims[1]} 0 0.0{eol}",
            f"{indent}0 0 {dims[2]} 0.0{eol}",
        )
        replacement = block.header + "".join(body) + (block.footer or f"%endblock kgrid.MonkhorstPack{eol}")
        return _replace_node(document, block, replacement)


def _replace_node(document, target, replacement: str) -> str:
    return "".join(replacement if node is target else node.raw for node in document.nodes)


def _semantic_map(document) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for node in document.nodes:
        if isinstance(node, FDFScalar):
            result.setdefault(normalize_label(node.label), (node.value, node.unit))
        elif isinstance(node, FDFBlock):
            body = tuple(line.strip() for line in node.body_lines if line.strip() and not line.lstrip().startswith(("#", "!", ";")))
            result.setdefault(normalize_label(node.name), body)
    return result
