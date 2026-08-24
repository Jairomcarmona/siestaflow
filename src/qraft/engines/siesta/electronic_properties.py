"""M7 SIESTA electronic-property semantics owned above the generic runtime.

This module deliberately contains no scheduler, attempt, or recovery logic.
It renders the three post-SCF branches, validates their inputs and raw files,
and supplies thin capability wrappers around :class:`SiestaEngineAdapter`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ...contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from ...core import TechnicalValidation
from ...models import DecisionStatus
from .adapter import SiestaEngineAdapter
from .effective_fdf import MaterializedEffectiveFDF, resolve_effective_fdf
from .ground_state import system_label
from .input_closure import resolve_scientific_input_closure
from .models import ArtifactDescriptor, FDFDocument, FDFInclude, InputValidationResult, normalize_label


PROPERTY_TYPES = {"bands": "qraft.bands", "dos": "qraft.dos", "pdos": "qraft.pdos"}
PROPERTY_CAPABILITIES = {
    "bands": "qraft.siesta.bands",
    "dos": "qraft.siesta.dos",
    "pdos": "qraft.siesta.pdos",
}
PROPERTY_SUFFIXES = {"bands": ".bands", "dos": ".DOS", "pdos": ".PDOS"}
_PARENT_FORBIDDEN = ("BandLines", "BandPoints", "ProjectedDensityOfStates", "PDOS.kgrid_Monkhorst_Pack")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _render_number(value: object) -> str:
    rendered = format(_number(value, "numeric value"), ".16g")
    return f"{rendered}.0" if "." not in rendered and "e" not in rendered.casefold() else rendered


@dataclass(frozen=True)
class BandPathVertex:
    coordinates: tuple[float, float, float]
    points_from_previous: int
    label: str

    def __post_init__(self) -> None:
        coords = tuple(_number(item, "band-path coordinate") for item in self.coordinates)
        if len(coords) != 3:
            raise ValueError("band-path vertices require three coordinates")
        if isinstance(self.points_from_previous, bool) or not isinstance(self.points_from_previous, int) or self.points_from_previous < 1:
            raise ValueError("points_from_previous must be a positive integer")
        label = str(self.label).strip()
        if not label or any(character.isspace() for character in label):
            raise ValueError("band-path labels must be non-empty single tokens")
        object.__setattr__(self, "coordinates", coords)
        object.__setattr__(self, "points_from_previous", int(self.points_from_previous))
        object.__setattr__(self, "label", label)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BandPathVertex":
        coordinates = value.get("coordinates")
        if not isinstance(coordinates, Sequence) or isinstance(coordinates, (str, bytes)):
            raise ValueError("band-path vertex coordinates are required")
        return cls(tuple(coordinates), value.get("points_from_previous"), str(value.get("label", "")))  # type: ignore[arg-type]

    def canonical(self) -> dict[str, object]:
        return {"coordinates": [_render_number(item) for item in self.coordinates], "points_from_previous": self.points_from_previous, "label": self.label}


@dataclass(frozen=True)
class BandPathSpec:
    scale: str
    vertices: tuple[BandPathVertex, ...]

    def __post_init__(self) -> None:
        if str(self.scale).strip() != "ReciprocalLatticeVectors":
            raise ValueError("M7 V1 supports only ReciprocalLatticeVectors band paths")
        vertices = tuple(item if isinstance(item, BandPathVertex) else BandPathVertex.from_mapping(item) for item in self.vertices)
        if len(vertices) < 2:
            raise ValueError("band paths require at least two ordered vertices")
        if vertices[0].points_from_previous != 1:
            raise ValueError("the first SIESTA BandLines vertex requires exactly 1 point")
        object.__setattr__(self, "scale", "ReciprocalLatticeVectors")
        object.__setattr__(self, "vertices", vertices)

    def canonical(self) -> dict[str, object]:
        return {"scale": self.scale, "vertices": [item.canonical() for item in self.vertices]}

    @property
    def sha256(self) -> str:
        return _canonical_sha(self.canonical())

    def render_block(self) -> str:
        return "\n".join(
            f"  {vertex.points_from_previous} {' '.join(_render_number(item) for item in vertex.coordinates)} {vertex.label}"
            for vertex in self.vertices
        )


@dataclass(frozen=True)
class DosSpec:
    energy_reference: str
    energy_min: float
    energy_max: float
    broadening: float
    energy_points: int
    energy_unit: str
    pdos_kgrid: tuple[tuple[int, int, int, float], tuple[int, int, int, float], tuple[int, int, int, float]]

    def __post_init__(self) -> None:
        reference = str(self.energy_reference).strip().upper()
        if reference not in {"EF", "ABSOLUTE"}:
            raise ValueError("energy_reference must be EF or absolute")
        low = _number(self.energy_min, "energy_min")
        high = _number(self.energy_max, "energy_max")
        broadening = _number(self.broadening, "broadening")
        if low >= high or broadening <= 0:
            raise ValueError("DOS window requires min < max and positive broadening")
        if isinstance(self.energy_points, bool) or not isinstance(self.energy_points, int) or self.energy_points < 2:
            raise ValueError("energy_points must be an integer of at least two")
        unit = str(self.energy_unit).strip()
        if unit.casefold() not in {"ev", "ry"}:
            raise ValueError("M7 DOS energy_unit must be eV or Ry")
        rows = tuple(tuple(row) for row in self.pdos_kgrid)
        if len(rows) != 3:
            raise ValueError("PDOS k-grid requires exactly three rows")
        validated: list[tuple[int, int, int, float]] = []
        for index, row in enumerate(rows):
            if len(row) != 4:
                raise ValueError("PDOS k-grid rows require four fields")
            first, second, third, shift = row
            integers = (first, second, third)
            if any(isinstance(item, bool) or int(item) != item for item in integers) or not any(int(item) > 0 for item in integers):
                raise ValueError(f"invalid PDOS k-grid row {index + 1}")
            value = _number(shift, "PDOS k-grid shift")
            validated.append((int(first), int(second), int(third), value))
        object.__setattr__(self, "energy_reference", reference)
        object.__setattr__(self, "energy_min", low)
        object.__setattr__(self, "energy_max", high)
        object.__setattr__(self, "broadening", broadening)
        object.__setattr__(self, "energy_points", int(self.energy_points))
        object.__setattr__(self, "energy_unit", "eV" if unit.casefold() == "ev" else "Ry")
        object.__setattr__(self, "pdos_kgrid", tuple(validated))

    def canonical(self) -> dict[str, object]:
        return {
            "energy_reference": self.energy_reference,
            "energy_min": _render_number(self.energy_min), "energy_max": _render_number(self.energy_max),
            "broadening": _render_number(self.broadening), "energy_points": self.energy_points,
            "energy_unit": self.energy_unit,
            "pdos_kgrid": [[*row[:3], _render_number(row[3])] for row in self.pdos_kgrid],
        }

    @property
    def sha256(self) -> str:
        return _canonical_sha(self.canonical())

    def render_pdos_blocks(self) -> dict[str, str]:
        # This is the native SIESTA projected-DOS input form.  The reference is
        # recorded in provenance; SIESTA's numerical range is rendered verbatim.
        return {
            "ProjectedDensityOfStates": "  ".join((
                *(("EF",) if self.energy_reference == "EF" else ()),
                _render_number(self.energy_min), _render_number(self.energy_max),
                _render_number(self.broadening), str(self.energy_points), self.energy_unit,
            )),
            "PDOS.kgrid_Monkhorst_Pack": "\n".join(f"  {a} {b} {c} {_render_number(shift)}" for a, b, c, shift in self.pdos_kgrid),
        }


@dataclass(frozen=True)
class PdosSpec(DosSpec):
    """Separate V1 PDOS spec, intentionally sharing only numerical shape."""


PropertySpec = BandPathSpec | DosSpec | PdosSpec


def validate_property_neutral_parent(path: Path) -> None:
    effective = resolve_effective_fdf(path)
    present = [name for name in _PARENT_FORBIDDEN if effective.occurrence(name) is not None]
    if present:
        raise ValueError("M7 parent final-SCF closure contains property directives: " + ", ".join(present))


def render_property_fdf(parent_fdf: Path, destination_root: Path, *, property_name: str, spec: PropertySpec, primary_destination: str = "input.fdf") -> MaterializedEffectiveFDF:
    """Render one immutable post-SCF branch from the verified final-SCF closure."""

    if property_name not in PROPERTY_TYPES:
        raise ValueError(f"unsupported M7 property: {property_name}")
    validate_property_neutral_parent(parent_fdf)
    scalars: dict[str, tuple[object, str | None]] = {"DM.UseSaveDM": ("true", None)}
    blocks: dict[str, str] = {}
    if property_name == "bands":
        if not isinstance(spec, BandPathSpec):
            raise ValueError("bands requires BandPathSpec")
        scalars["BandLinesScale"] = (spec.scale, None)
        blocks["BandLines"] = spec.render_block()
    else:
        if not isinstance(spec, DosSpec):
            raise ValueError(f"{property_name} requires a DOS-shaped spec")
        blocks.update(spec.render_pdos_blocks())
    from .effective_fdf import materialize_effective_fdf
    rendered = materialize_effective_fdf(parent_fdf, destination_root, scalar_updates=scalars, block_updates=blocks, primary_destination=primary_destination)
    validate_property_branch(rendered.root_fdf, property_name)
    return rendered


def validate_property_branch(path: Path, property_name: str) -> None:
    effective = resolve_effective_fdf(path)
    dm = effective.scalar("DM.UseSaveDM")
    if dm is None or dm.value.strip().casefold() not in {"true", "t", ".true.", "yes"}:
        raise ValueError("M7 property branches require DM.UseSaveDM true")
    if property_name == "bands":
        scale, block = effective.scalar("BandLinesScale"), effective.block("BandLines")
        if scale is None or scale.value.strip() != "ReciprocalLatticeVectors" or block is None or not block.closed:
            raise ValueError("bands branch requires BandLinesScale and a closed BandLines block")
        if effective.block("ProjectedDensityOfStates") is not None or effective.block("PDOS.kgrid_Monkhorst_Pack") is not None:
            raise ValueError("bands branch must not contain DOS/PDOS directives")
    elif property_name in {"dos", "pdos"}:
        if effective.block("ProjectedDensityOfStates") is None or effective.block("PDOS.kgrid_Monkhorst_Pack") is None:
            raise ValueError("DOS and PDOS branches require native projected-DOS blocks")
        if effective.block("BandLines") is not None or effective.block("BandPoints") is not None:
            raise ValueError("DOS/PDOS branches must not contain band directives")
    else:
        raise ValueError(f"unsupported M7 property: {property_name}")


def _numeric_rows(path: Path, *, minimum_columns: int) -> list[list[float]]:
    rows: list[list[float]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!", ";")):
            continue
        try:
            values = [float(item.replace("D", "E").replace("d", "e")) for item in line.split()]
        except ValueError as exc:
            raise ValueError(f"non-numeric property output row: {line}") from exc
        if len(values) < minimum_columns or not all(math.isfinite(item) for item in values):
            raise ValueError("property output contains invalid numeric data")
        rows.append(values)
    if not rows:
        raise ValueError("property output is empty")
    return rows


_INTEGER = re.compile(r"^[+-]?\d+$")


def _finite_token(value: str, field: str) -> float:
    try:
        result = float(value.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(result):
        raise ValueError(f"invalid {field}")
    return result


def _integer_token(value: str, field: str, *, positive: bool = False) -> int:
    if not _INTEGER.fullmatch(value):
        raise ValueError(f"invalid integer {field}")
    result = int(value)
    if positive and result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def parse_bands(path: Path) -> dict[str, Any]:
    """Parse the structured native SIESTA ``.bands`` stream, including wraps."""

    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.lstrip().startswith(("#", "!", ";"))]
    if len(lines) < 5:
        raise ValueError("bands output is truncated")
    headers = [line.split() for line in lines[:4]]
    if len(headers[0]) != 1 or len(headers[1]) != 2 or len(headers[2]) != 2 or len(headers[3]) != 3:
        raise ValueError("invalid SIESTA bands header")
    fermi = _finite_token(headers[0][0], "bands Fermi energy")
    kmin, kmax = (_finite_token(value, "bands k range") for value in headers[1])
    emin, emax = (_finite_token(value, "bands energy range") for value in headers[2])
    nbands, nspin, nkpoints = (_integer_token(value, name, positive=True) for value, name in zip(headers[3], ("number of bands", "number of spins", "number of k points")))
    if nspin not in {1, 2}:
        raise ValueError("M7 supports only one or two SIESTA spin channels")
    payload_tokens = " ".join(lines[4:]).split()
    expected = nkpoints * (1 + nbands * nspin)
    if len(payload_tokens) < expected + 1:
        raise ValueError("bands k-point/eigenvalue payload is truncated")
    values = [_finite_token(token, "bands k-point/eigenvalue payload") for token in payload_tokens[:expected]]
    trailing = payload_tokens[expected:]
    nk_lines = _integer_token(trailing[0], "number of k lines")
    if nk_lines < 0 or len(trailing[1:]) != nk_lines * 2:
        raise ValueError("bands line-label section is truncated or malformed")
    labels: list[str] = []
    for index in range(nk_lines):
        _finite_token(trailing[1 + 2 * index], "bands line abscissa")
        label = trailing[2 + 2 * index].strip()
        if not label:
            raise ValueError("bands line label is missing")
        labels.append(label)
    return {
        "fermi_energy": fermi, "kmin": kmin, "kmax": kmax, "energy_min": emin, "energy_max": emax,
        "bands": nbands, "spins": nspin, "kpoints": nkpoints, "line_labels": tuple(labels),
        "finite_eigenvalues": expected - nkpoints,
    }


def parse_dos(path: Path, *, expected_points: int | None = None) -> dict[str, Any]:
    rows = _numeric_rows(path, minimum_columns=2)
    energies = [row[0] for row in rows]
    if any(right <= left for left, right in zip(energies, energies[1:])):
        raise ValueError("DOS energy grid is not strictly monotonic")
    if any(value < -1e-10 for row in rows for value in row[1:]):
        raise ValueError("DOS contains materially negative values")
    if expected_points is not None and abs(len(rows) - expected_points) > max(2, int(expected_points * 0.05)):
        raise ValueError("DOS row count is inconsistent with the requested sampling")
    return {"rows": len(rows), "energy_min": energies[0], "energy_max": energies[-1]}


def _xml_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _xml_numbers(text: str | None, field: str) -> list[float]:
    tokens = (text or "").split()
    if not tokens:
        raise ValueError(f"PDOS {field} is missing")
    return [_finite_token(token, f"PDOS {field}") for token in tokens]


def parse_pdos(path: Path, *, expected_points: int | None = None) -> dict[str, Any]:
    """Validate native SIESTA XML-structured projected density output."""

    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ValueError("PDOS XML is malformed or truncated") from exc
    if "pdos" not in _xml_name(root):
        raise ValueError("PDOS XML root is invalid")
    energies: list[float] | None = None
    projected: list[list[float]] = []
    for element in root.iter():
        name = _xml_name(element)
        if name in {"energy_values", "energy-grid", "energygrid"}:
            energies = _xml_numbers(element.text, "energy grid")
        elif name in {"data", "projected", "projection", "orbital"}:
            text = element.text or ""
            if text.strip():
                projected.append(_xml_numbers(text, "orbital payload"))
    if energies is None or len(energies) < 2:
        raise ValueError("PDOS energy grid is missing or truncated")
    if any(right <= left for left, right in zip(energies, energies[1:])):
        raise ValueError("PDOS energy grid is not strictly monotonic")
    if expected_points is not None and len(energies) != expected_points:
        raise ValueError("PDOS energy grid length is inconsistent with the requested sampling")
    if not projected:
        raise ValueError("PDOS orbital/projected payload is missing")
    if any(len(values) % len(energies) for values in projected):
        raise ValueError("PDOS orbital payload is inconsistent with the energy grid")
    return {"rows": len(energies), "orbitals": len(projected), "energy_min": energies[0], "energy_max": energies[-1]}


def validate_property_output(path: Path, property_name: str, *, expected_points: int | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required {property_name} output is missing")
    if property_name == "bands":
        return parse_bands(path)
    if property_name == "dos":
        return parse_dos(path, expected_points=expected_points)
    if property_name == "pdos":
        return parse_pdos(path, expected_points=expected_points)
    raise ValueError(f"unsupported M7 property: {property_name}")


def property_artifact_envelope(*, property_name: str, artifact_id: str, parent: Mapping[str, Any], spec: PropertySpec, scientific_identity_sha256: str, rendered_fdf_sha256: str, raw_output: Path, task_id: str, attempt_id: str, validation: Mapping[str, Any]) -> dict[str, Any]:
    """Create a plugin-owned, path-free scientific artifact envelope."""

    payload = {
        "schema_version": "1.0", "artifact_id": artifact_id,
        "artifact_type": PROPERTY_TYPES[property_name], "authority": "PROVISIONAL", "engine": "siesta",
        "parent_electronic_state": dict(parent), "producer": {
            "capability_id": PROPERTY_CAPABILITIES[property_name], "task_id": task_id,
            "attempt_id": attempt_id, "scientific_identity_sha256": scientific_identity_sha256,
        },
        "property": {"name": property_name, "spec": spec.canonical(), "spec_sha256": spec.sha256},
        "rendered_fdf_sha256": rendered_fdf_sha256,
        "raw_output": {"filename": raw_output.name, "sha256": sha256_path(raw_output)},
        "validation": dict(validation),
    }
    return ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer=PROPERTY_CAPABILITIES[property_name], payload=payload).to_dict()


class SiestaPropertyCapability:
    """Shared engine mechanics with property-specific input/output semantics."""

    property_name: str

    def __init__(self, property_name: str) -> None:
        if property_name not in PROPERTY_TYPES:
            raise ValueError(f"unsupported M7 property: {property_name}")
        self.property_name = property_name
        self.base = SiestaEngineAdapter()
        self._workspaces: dict[tuple[str, str], Path] = {}

    inspect_input = lambda self, path: self.base.inspect_input(path)
    select_primary_input = lambda self, **kwargs: self.base.select_primary_input(**kwargs)
    build_command = lambda self, input_path, **kwargs: self.base.build_command(input_path, **kwargs)

    def mutable_input_names(self, **kwargs: Any) -> tuple[str, ...]:
        bindings = dict(kwargs.get("bindings", {}))
        return tuple(sorted(name for name, binding in bindings.items() if Path(str(getattr(binding, "destination", ""))).suffix.casefold() == ".dm"))

    def validate_consumed_inputs(self, parsed: Any, **kwargs: Any):
        return self.base.validate_consumed_inputs(parsed, **kwargs)

    def validate_input(self, inspected: FDFDocument, **kwargs: Any) -> InputValidationResult:
        validate_property_branch(Path(inspected.source), self.property_name)
        validation = self.base.validate_input(inspected, **kwargs)
        if not any(isinstance(node, FDFInclude) for node in inspected.nodes):
            return validation
        inputs = {Path(path).resolve() for path in dict(kwargs.get("inputs", {})).values()}
        closure = resolve_scientific_input_closure(Path(inspected.source))
        missing = [entry.destination for entry in closure.entries if entry.source.resolve() not in inputs]
        if missing:
            raise ValueError("canonical SIESTA property input closure is incomplete: " + ", ".join(missing))
        findings = tuple(item for item in validation.findings if item.code != "UNRESOLVED_INCLUDE")
        rank = {DecisionStatus.PASS: 0, DecisionStatus.REVIEW: 1, DecisionStatus.BLOCKED: 2, DecisionStatus.FAIL: 3}
        status = max((item.status for item in findings), key=lambda item: rank[item], default=DecisionStatus.PASS)
        return InputValidationResult(status, findings, validation.atoms, validation.species, validation.system_id)

    def prepare_task(self, inspected: FDFDocument, workspace: Path, **kwargs: Any):
        prepared = self.base.prepare_task(inspected, workspace, **kwargs)
        self._workspaces[(str(kwargs["task_id"]), str(kwargs["attempt_id"]))] = workspace
        return prepared

    def parse_output(self, lines: Iterable[str], **kwargs: Any):
        return self.base.parse_output(lines, **kwargs)

    def classify_result(self, parsed: Any, **kwargs: Any) -> TechnicalValidation:
        technical = self.base.classify_result(parsed, **kwargs)
        outcome = kwargs.get("outcome")
        key = (str(getattr(outcome, "task_id", "")), str(getattr(outcome, "attempt_id", "")))
        workspace = self._workspaces.get(key)
        if technical.status != "PASS" or workspace is None:
            return technical
        try:
            expected = kwargs.get("settings", {}).get("expected_points")
            validate_property_output(workspace / f"{system_label(workspace / 'input.fdf')}{PROPERTY_SUFFIXES[self.property_name]}", self.property_name, expected_points=int(expected) if expected is not None else None)
        except (OSError, ValueError) as exc:
            return TechnicalValidation("FAIL", "PROPERTY_OUTPUT_INVALID", (str(exc),), technical.parser_summary)
        return technical

    def discover_artifacts(self, workspace: Path, **kwargs: Any) -> tuple[ArtifactDescriptor, ...]:
        return tuple(self.base.discover_artifacts(workspace, **kwargs))


class SiestaBandsCapability(SiestaPropertyCapability):
    def __init__(self) -> None:
        super().__init__("bands")


class SiestaDosCapability(SiestaPropertyCapability):
    def __init__(self) -> None:
        super().__init__("dos")


class SiestaPdosCapability(SiestaPropertyCapability):
    def __init__(self) -> None:
        super().__init__("pdos")
