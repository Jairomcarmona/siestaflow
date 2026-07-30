"""Structural validation without scientific interpretation or defaults."""

from __future__ import annotations

from ...models import DecisionStatus
from .fdf_registry import FDFRegistry
from .models import (
    FDFBlock,
    FDFDocument,
    FDFInclude,
    FDFScalar,
    InputValidationResult,
    ValidationFinding,
)
from .pseudopotentials import PseudopotentialVerificationResult


_RANK = {DecisionStatus.PASS: 0, DecisionStatus.REVIEW: 1, DecisionStatus.BLOCKED: 2, DecisionStatus.FAIL: 3}


class SiestaInputValidator:
    def __init__(self, registry: FDFRegistry | None = None) -> None:
        self.registry = registry or FDFRegistry.load_default()

    def validate(
        self,
        document: FDFDocument,
        *,
        pseudo_result: PseudopotentialVerificationResult | None = None,
        require_pseudos: bool = False,
    ) -> InputValidationResult:
        findings: list[ValidationFinding] = []
        for diagnostic in document.diagnostics:
            status = DecisionStatus.FAIL if diagnostic.severity == "ERROR" else DecisionStatus.REVIEW
            findings.append(ValidationFinding(diagnostic.code, status, diagnostic.message, (f"line:{diagnostic.span.start_line}",)))

        for node in document.nodes:
            name = node.label if isinstance(node, FDFScalar) else node.name if isinstance(node, FDFBlock) else None
            if name and self.registry.get(name) is None:
                findings.append(ValidationFinding("UNKNOWN_LABEL", DecisionStatus.REVIEW, f"unknown label preserved: {name}"))
        if any(isinstance(node, FDFInclude) for node in document.nodes):
            findings.append(ValidationFinding("UNRESOLVED_INCLUDE", DecisionStatus.BLOCKED, "include/redirection requires an explicit path policy"))

        atoms = _integer_scalar(document, "NumberOfAtoms", findings)
        species_count = _integer_scalar(document, "NumberOfSpecies", findings)
        species_block = _single_block(document, "ChemicalSpeciesLabel", findings)
        coordinates = _single_block(document, "AtomicCoordinatesAndAtomicSpecies", findings)
        lattice = _single_block(document, "LatticeVectors", findings)
        species: list[str] = []
        valid_indices: set[int] = set()
        if species_block:
            for line in _data_lines(species_block):
                tokens = line.split()
                if len(tokens) < 3:
                    findings.append(ValidationFinding("INVALID_SPECIES_ROW", DecisionStatus.FAIL, f"invalid species row: {line}"))
                    continue
                try:
                    index = int(tokens[0])
                except ValueError:
                    findings.append(ValidationFinding("INVALID_SPECIES_INDEX", DecisionStatus.FAIL, f"invalid species index: {tokens[0]}"))
                    continue
                valid_indices.add(index)
                species.append(tokens[2])
            if species_count is not None and species_count != len(species):
                findings.append(ValidationFinding("SPECIES_COUNT_MISMATCH", DecisionStatus.FAIL, f"NumberOfSpecies={species_count}, block={len(species)}"))
        atom_rows = _data_lines(coordinates) if coordinates else []
        if atoms is not None and atoms != len(atom_rows):
            findings.append(ValidationFinding("ATOM_COUNT_MISMATCH", DecisionStatus.FAIL, f"NumberOfAtoms={atoms}, coordinates={len(atom_rows)}"))
        for position, row in enumerate(atom_rows, 1):
            tokens = row.split()
            if len(tokens) < 4:
                findings.append(ValidationFinding("INVALID_COORDINATE_ROW", DecisionStatus.FAIL, f"coordinate row {position} has fewer than four fields"))
                continue
            try:
                index = int(tokens[3])
            except ValueError:
                findings.append(ValidationFinding("INVALID_COORDINATE_SPECIES", DecisionStatus.FAIL, f"coordinate row {position} has invalid species"))
                continue
            if index not in valid_indices:
                findings.append(ValidationFinding("UNKNOWN_SPECIES_INDEX", DecisionStatus.FAIL, f"coordinate row {position} uses species {index}"))

        for required, present in (("ChemicalSpeciesLabel", species_block), ("AtomicCoordinatesAndAtomicSpecies", coordinates), ("LatticeVectors", lattice)):
            if present is None:
                findings.append(ValidationFinding("MISSING_REQUIRED_BLOCK", DecisionStatus.FAIL, f"missing required block {required}"))
        for declared in ("NetCharge", "Spin", "MD.Steps", "MD.TypeOfRun"):
            if not document.scalars(declared):
                findings.append(ValidationFinding("UNDECLARED_GOVERNED_VALUE", DecisionStatus.REVIEW, f"{declared} is not explicitly declared; no default assumed"))
        _integer_scalar(document, "MD.Steps", findings)

        if pseudo_result is not None:
            findings.append(ValidationFinding("PSEUDOPOTENTIAL_AUDIT", pseudo_result.status, "pseudopotential manifest verification", pseudo_result.findings))
        elif require_pseudos:
            findings.append(ValidationFinding("PSEUDOPOTENTIAL_MANIFEST_REQUIRED", DecisionStatus.BLOCKED, "pseudopotential verification is required"))

        status = max((finding.status for finding in findings), key=lambda item: _RANK[item], default=DecisionStatus.PASS)
        system_nodes = document.scalars("SystemLabel") or document.scalars("SystemName")
        system_id = system_nodes[0].value if system_nodes else None
        return InputValidationResult(status, tuple(findings), atoms, tuple(species), system_id)


def _single_block(document: FDFDocument, name: str, findings: list[ValidationFinding]) -> FDFBlock | None:
    blocks = document.blocks(name)
    if len(blocks) > 1:
        findings.append(ValidationFinding("DUPLICATE_BLOCK", DecisionStatus.REVIEW, f"multiple blocks named {name}; first wins"))
    return blocks[0] if blocks else None


def _integer_scalar(document: FDFDocument, name: str, findings: list[ValidationFinding]) -> int | None:
    scalars = document.scalars(name)
    if not scalars:
        return None
    try:
        return int(scalars[0].value)
    except ValueError:
        findings.append(ValidationFinding("INVALID_INTEGER", DecisionStatus.FAIL, f"{name} is not an integer: {scalars[0].value}"))
        return None


def _data_lines(block: FDFBlock | None) -> list[str]:
    if block is None:
        return []
    result = []
    for line in block.body_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "!", ";")):
            result.append(stripped.split("#", 1)[0].strip())
    return result
