"""Lossless FDF tokenizer/state machine.

The parser deliberately does not resolve includes or redirections. Opening an
external path is a policy decision outside parsing.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import (
    FDFBlankLine,
    FDFBlock,
    FDFComment,
    FDFDocument,
    FDFInclude,
    FDFScalar,
    FDFUnknown,
    ParseDiagnostic,
    SourceSpan,
    normalize_label,
)


_BLOCK = re.compile(r"^\s*%block\s+([^\s<]+)(?:\s*<\s*(\S+))?", re.IGNORECASE)
_END = re.compile(r"^\s*%endblock(?:\s+([^\s#;!]+))?", re.IGNORECASE)
_INCLUDE = re.compile(r"^\s*%include\s+(.+?)\s*(?:[#;!].*)?$", re.IGNORECASE)
_REDIRECT = re.compile(r"^\s*([A-Za-z][\w.:-]*)\s*<\s*(\S+)")
_SCALAR = re.compile(r"^\s*([A-Za-z][\w.:-]*)(?:\s+(.*?))?\s*$")


class FDFParser:
    def parse_path(self, path: Path) -> FDFDocument:
        # newline='' preserves the exact source line endings.
        with path.open("r", encoding="utf-8", errors="surrogateescape", newline="") as handle:
            return self.parse(handle.read(), source=str(path))

    def parse(self, text: str, *, source: str = "<memory>") -> FDFDocument:
        lines = text.splitlines(keepends=True)
        if text and not lines:
            lines = [text]
        newline_style = "\r\n" if "\r\n" in text else "\n" if "\n" in text else ""
        nodes = []
        diagnostics: list[ParseDiagnostic] = []
        index = 0
        while index < len(lines):
            raw = lines[index]
            content = raw.rstrip("\r\n")
            span = SourceSpan(source, index + 1, index + 1)
            stripped = content.strip()
            if not stripped:
                nodes.append(FDFBlankLine(raw, span))
                index += 1
                continue
            if stripped.startswith(("#", "!", ";")):
                nodes.append(FDFComment(raw, span, stripped[1:].lstrip()))
                index += 1
                continue
            block_match = _BLOCK.match(content)
            if block_match:
                name, redirected = block_match.groups()
                if redirected:
                    nodes.append(FDFBlock(raw, span, name, raw, (), None, True, redirected))
                    index += 1
                    continue
                start = index
                body: list[str] = []
                footer: str | None = None
                closed = False
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    candidate_content = candidate.rstrip("\r\n")
                    nested = _BLOCK.match(candidate_content)
                    end_match = _END.match(candidate_content)
                    if nested:
                        diagnostics.append(ParseDiagnostic(
                            "NESTED_BLOCK", "nested %block is not supported by FDF", "ERROR",
                            SourceSpan(source, index + 1, index + 1),
                        ))
                    if end_match:
                        end_name = end_match.group(1)
                        if end_name and normalize_label(end_name) != normalize_label(name):
                            diagnostics.append(ParseDiagnostic(
                                "MISMATCHED_ENDBLOCK", f"%endblock {end_name} closes %block {name}", "ERROR",
                                SourceSpan(source, index + 1, index + 1),
                            ))
                        footer = candidate
                        closed = True
                        index += 1
                        break
                    body.append(candidate)
                    index += 1
                if not closed:
                    diagnostics.append(ParseDiagnostic(
                        "UNCLOSED_BLOCK", f"%block {name} has no %endblock", "ERROR",
                        SourceSpan(source, start + 1, max(start + 1, len(lines))),
                    ))
                combined = raw + "".join(body) + (footer or "")
                nodes.append(FDFBlock(
                    combined, SourceSpan(source, start + 1, index), name, raw,
                    tuple(body), footer, closed,
                ))
                continue
            end_match = _END.match(content)
            if end_match:
                diagnostics.append(ParseDiagnostic(
                    "ORPHAN_ENDBLOCK", "encountered %endblock outside a block", "ERROR", span,
                ))
                nodes.append(FDFUnknown(raw, span, "orphan %endblock"))
                index += 1
                continue
            include_match = _INCLUDE.match(content)
            if include_match:
                nodes.append(FDFInclude(raw, span, include_match.group(1).strip(), "%include", None))
                index += 1
                continue
            redirect_match = _REDIRECT.match(content)
            if redirect_match:
                nodes.append(FDFInclude(raw, span, redirect_match.group(2), "redirect", redirect_match.group(1)))
                index += 1
                continue
            scalar_match = _SCALAR.match(content)
            if scalar_match:
                label = scalar_match.group(1)
                tail = scalar_match.group(2) or ""
                value_part = _strip_inline_comment(tail).strip()
                tokens = value_part.split()
                unit = tokens[-1] if len(tokens) > 1 and re.fullmatch(r"[A-Za-z]+", tokens[-1]) else None
                value = " ".join(tokens[:-1]) if unit else value_part
                nodes.append(FDFScalar(raw, span, label, value, unit))
                index += 1
                continue
            nodes.append(FDFUnknown(raw, span))
            index += 1

        self._duplicate_diagnostics(nodes, diagnostics, source)
        return FDFDocument(
            source=source,
            nodes=nodes,
            diagnostics=diagnostics,
            newline_style=newline_style,
            original_sha256=hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest(),
        )

    @staticmethod
    def _duplicate_diagnostics(nodes: list[object], diagnostics: list[ParseDiagnostic], source: str) -> None:
        seen: dict[str, object] = {}
        for node in nodes:
            label = node.label if isinstance(node, FDFScalar) else node.name if isinstance(node, FDFBlock) else None
            if label is None:
                continue
            normalized = normalize_label(label)
            if normalized in seen:
                diagnostics.append(ParseDiagnostic(
                    "DUPLICATE_LABEL",
                    f"duplicate label {label}; FDF first appearance takes precedence",
                    "WARNING",
                    node.span,
                ))
            else:
                seen[normalized] = node


def _strip_inline_comment(value: str) -> str:
    for index, char in enumerate(value):
        if char in "#;!" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value
