"""Fixed-cell SIESTA relaxation capability and geometry normalization."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

from ...contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from ...core import TechnicalValidation
from ...models import DecisionStatus
from .adapter import SiestaEngineAdapter
from .input_closure import resolve_scientific_input_closure
from .models import ArtifactDescriptor, FDFBlock, FDFDocument, FDFInclude, FDFScalar, InputValidationResult, normalize_label


_BOHR_TO_ANG = 0.529177210903
_RY_PER_BOHR_TO_EV_PER_ANG = 13.605693122994 / _BOHR_TO_ANG
_GEOMETRY_TYPE = "qraft.geometry"
_LEGACY_FORCE = re.compile(r"max(?:imum)?\s+force\s*[:=]\s*([-+0-9.Ee]+)\s*([A-Za-zÅ/]+)", re.I)
_FORCE_HEADER = re.compile(r"^\s*(?:siesta:\s*)?atomic\s+forces\s*\(([^)]+)\)\s*:\s*$", re.I)
_FORCE_MAX = re.compile(r"^\s*max\s+([-+0-9.Ee]+)(?:\s+(constrained))?\s*$", re.I)


def _scalar(document: FDFDocument, name: str) -> FDFScalar | None:
    return next((item for item in document.scalars() if normalize_label(item.label) == normalize_label(name)), None)


def _block(document: FDFDocument, name: str) -> FDFBlock | None:
    return next((item for item in document.blocks() if normalize_label(item.name) == normalize_label(name)), None)


def _float(value: str, field: str) -> float:
    try:
        result = float(value.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(result):
        raise ValueError(f"invalid {field}")
    return result


def _unit_factor(unit: str | None, *, force: bool = False) -> float:
    if force and not unit:
        raise ValueError("force unit is required")
    normalized = (unit or "Ang").replace("Å", "Ang").casefold()
    factors = ({"ev/ang": 1.0, "ry/bohr": _RY_PER_BOHR_TO_EV_PER_ANG}
               if force else {"ang": 1.0, "bohr": _BOHR_TO_ANG})
    if normalized not in factors:
        raise ValueError(f"unsupported {'force' if force else 'length'} unit: {unit}")
    return factors[normalized]


def _matvec(cell: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(vector[index] * cell[index][axis] for index in range(3)) for axis in range(3)]


def geometry_from_fdf(path: Path) -> dict[str, Any]:
    from .fdf_parser import FDFParser

    document = FDFParser().parse_path(path)
    lattice = _block(document, "LatticeVectors")
    coordinates = _block(document, "AtomicCoordinatesAndAtomicSpecies")
    if lattice is None or coordinates is None or not lattice.closed or not coordinates.closed:
        raise ValueError("M5 requires LatticeVectors and AtomicCoordinatesAndAtomicSpecies")
    constant = _scalar(document, "LatticeConstant")
    scale = _unit_factor(constant.unit if constant else "Ang") * (_float(constant.value, "LatticeConstant") if constant else 1.0)
    rows = [line.split() for line in lattice.body_lines if line.strip()]
    if len(rows) != 3 or any(len(row) < 3 for row in rows):
        raise ValueError("LatticeVectors must contain three vectors")
    cell = [[_float(row[index], "lattice vector") * scale for index in range(3)] for row in rows]
    fmt = (_scalar(document, "AtomicCoordinatesFormat").value if _scalar(document, "AtomicCoordinatesFormat") else "Bohr").casefold()
    atoms = []
    for position, line in enumerate(coordinates.body_lines, 1):
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 4:
            raise ValueError("invalid atomic coordinate row")
        vector = [_float(fields[index], "coordinate") for index in range(3)]
        if fmt in {"ang", "notscaledcartesianang"}:
            cartesian = vector
        elif fmt in {"bohr", "notscaledcartesianbohr"}:
            cartesian = [item * _BOHR_TO_ANG for item in vector]
        elif fmt in {"fractional", "scaledbylatticevectors"}:
            cartesian = _matvec(cell, vector)
        elif fmt in {"latticeconstant", "scaledcartesian"}:
            cartesian = [item * scale for item in vector]
        else:
            raise ValueError(f"unsupported AtomicCoordinatesFormat for M5: {fmt}")
        atoms.append({"index": position, "species_index": int(fields[3]), "coordinates": cartesian})
    declared = _scalar(document, "NumberOfAtoms")
    if declared is not None and int(declared.value) != len(atoms):
        raise ValueError("NumberOfAtoms does not match coordinate count")
    return {"cell": cell, "atoms": atoms, "source_fdf_sha256": document.original_sha256}


def geometry_envelope(*, artifact_id: str, geometry: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
    return ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="qraft.siesta.relax", payload={
        "schema_version": "1.0", "artifact_id": artifact_id, "artifact_type": _GEOMETRY_TYPE,
        "authority": "PROVISIONAL", "representation": "cartesian", "length_unit": "Ang",
        "cell": geometry["cell"], "atoms": geometry["atoms"], "provenance": dict(provenance),
    }).to_dict()


def parse_struct_out(path: Path) -> dict[str, Any]:
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 4 or any(len(line) < 3 for line in lines[:3]):
        raise ValueError("invalid STRUCT_OUT cell")
    cell = [[_float(line[index], "STRUCT_OUT cell") for index in range(3)] for line in lines[:3]]
    try:
        count = int(lines[3][0])
    except (IndexError, ValueError) as exc:
        raise ValueError("invalid STRUCT_OUT atom count") from exc
    if len(lines) != count + 4:
        raise ValueError("STRUCT_OUT atom count mismatch")
    atoms = []
    for index, line in enumerate(lines[4:], 1):
        if len(line) < 5:
            raise ValueError("invalid STRUCT_OUT atom row")
        fractional = [_float(line[column], "STRUCT_OUT coordinate") for column in range(2, 5)]
        atoms.append({"index": index, "species_index": int(line[0]), "coordinates": _matvec(cell, fractional)})
    return {"cell": cell, "atoms": atoms}


def _force_from_text(text: str) -> float | None:
    """Read only the final structurally valid SIESTA force section."""

    lines = text.splitlines()
    headers = [(index, match) for index, line in enumerate(lines) if (match := _FORCE_HEADER.match(line))]
    if headers:
        start, header = headers[-1]
        factor = _unit_factor(header.group(1).strip(), force=True)
        end = next((index for index in range(start + 1, len(lines)) if _FORCE_HEADER.match(lines[index])), len(lines))
        maxima = [
            (match, _float(match.group(1), "maximum force"))
            for line in lines[start + 1:end]
            if (match := _FORCE_MAX.match(line))
        ]
        if not maxima:
            return None
        constrained = [value for match, value in maxima if match.group(2)]
        return (constrained[-1] if constrained else maxima[-1][1]) * factor
    matches = list(_LEGACY_FORCE.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    return _float(match.group(1), "maximum force") * _unit_factor(match.group(2), force=True)


def _fdf_logical(value: str) -> bool:
    token = value.strip().casefold()
    if token in {"", "t", "true", ".true.", "yes"}:
        return True
    if token in {"f", "false", ".false.", "no"}:
        return False
    raise ValueError(f"invalid FDF logical value: {value}")


def validate_relaxation(document: FDFDocument) -> float:
    run_type = _scalar(document, "MD.TypeOfRun")
    if run_type is None or run_type.value.strip().upper() not in {"CG", "BROYDEN", "FIRE"}:
        raise ValueError("M5 requires MD.TypeOfRun CG, Broyden, or FIRE")
    variable = _scalar(document, "MD.VariableCell")
    if variable is not None and _fdf_logical(variable.value):
        raise ValueError("M5 V1 rejects variable-cell relaxation")
    steps = _scalar(document, "MD.Steps")
    if steps is None or int(steps.value) <= 0:
        raise ValueError("M5 requires positive MD.Steps")
    tolerance = _scalar(document, "MD.MaxForceTol")
    if tolerance is None or _float(tolerance.value, "MD.MaxForceTol") <= 0:
        raise ValueError("M5 requires explicit positive MD.MaxForceTol")
    return _float(tolerance.value, "MD.MaxForceTol") * _unit_factor(tolerance.unit, force=True)


@dataclass(frozen=True)
class RelaxationParsed:
    base: Any
    max_force_ev_per_ang: float | None


class SiestaRelaxationCapability:
    """Plugin-owned fixed-cell semantics layered over the standard adapter."""

    def __init__(self) -> None:
        self.base = SiestaEngineAdapter()

    inspect_input = lambda self, path: self.base.inspect_input(path)
    select_primary_input = lambda self, **kwargs: self.base.select_primary_input(**kwargs)
    mutable_input_names = lambda self, **kwargs: self.base.mutable_input_names(**kwargs)
    validate_consumed_inputs = lambda self, parsed, **kwargs: self.base.validate_consumed_inputs(parsed.base, **kwargs)
    prepare_task = lambda self, inspected, workspace, **kwargs: self.base.prepare_task(inspected, workspace, **kwargs)
    build_command = lambda self, input_path, **kwargs: self.base.build_command(input_path, **kwargs)

    def validate_input(self, inspected: FDFDocument, **kwargs: Any):
        validate_relaxation(inspected)
        validation = self.base.validate_input(inspected, **kwargs)
        if not any(isinstance(node, FDFInclude) for node in inspected.nodes):
            return validation
        inputs = {str(name): Path(path).resolve() for name, path in dict(kwargs.get("inputs", {})).items()}
        closure = resolve_scientific_input_closure(
            Path(inspected.source), pseudo_manifest=inputs.get("pseudo-manifest")
        )
        missing = [entry.destination for entry in closure.entries if entry.source.resolve() not in set(inputs.values())]
        if missing:
            raise ValueError("canonical SIESTA input closure is incomplete: " + ", ".join(missing))
        findings = tuple(item for item in validation.findings if item.code != "UNRESOLVED_INCLUDE")
        rank = {DecisionStatus.PASS: 0, DecisionStatus.REVIEW: 1, DecisionStatus.BLOCKED: 2, DecisionStatus.FAIL: 3}
        status = max((item.status for item in findings), key=lambda item: rank[item], default=DecisionStatus.PASS)
        return InputValidationResult(status, findings, validation.atoms, validation.species, validation.system_id)

    def parse_output(self, lines: Iterable[str], **kwargs: Any) -> RelaxationParsed:
        raw = tuple(lines)
        return RelaxationParsed(self.base.parse_output(raw, **kwargs), _force_from_text("".join(raw)))

    def classify_result(self, parsed: RelaxationParsed, **kwargs: Any):
        technical = self.base.classify_result(parsed.base, **kwargs)
        if technical.status == "PASS" and parsed.max_force_ev_per_ang is None:
            return TechnicalValidation("FAIL", "RELAXATION_FORCE_EVIDENCE_MISSING", ("maximum force with units missing",), asdict(parsed.base))
        return technical

    def discover_artifacts(self, workspace: Path, **kwargs: Any):
        settings = dict(kwargs.get("settings", {}))
        document = self.base.inspect_input(workspace / "input.fdf")
        label = _scalar(document, "SystemLabel")
        struct = workspace / f"{label.value.strip() if label else 'siesta'}.STRUCT_OUT"
        found = list(self.base.discover_artifacts(workspace, **kwargs))
        if not struct.is_file():
            return tuple(found)
        force = _force_from_text((workspace / "stdout.txt").read_text(encoding="utf-8", errors="replace"))
        if force is None:
            return tuple(found)
        geometry = parse_struct_out(struct)
        initial = dict(settings["input_geometry"])
        envelope = geometry_envelope(artifact_id="relaxed-geometry", geometry=geometry, provenance={
            "input_geometry_sha256": initial["content_sha256"], "struct_out_sha256": __import__("hashlib").sha256(struct.read_bytes()).hexdigest(),
            "task_id": kwargs["task_id"], "attempt_id": kwargs["attempt_id"], "capability_id": "qraft.siesta.relax", "force_ev_per_ang": force,
        })
        output = workspace / "relaxed-geometry.json"
        output.write_text(json.dumps(envelope, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        for path, kind in ((struct, "STRUCT_OUT"), (output, "qraft.geometry")):
            found.append(ArtifactDescriptor(str(path), kind, path.stat().st_size, __import__("hashlib").sha256(path.read_bytes()).hexdigest(), kwargs["task_id"], kwargs["attempt_id"]))
        return tuple(found)
