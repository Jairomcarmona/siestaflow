"""Provider-neutral crystallographic band-path planning for M7.1.

This module has no SIESTA, scheduler, or optional-symmetry-library import.
It owns the scientific policy around a provider proposal; an engine adapter
turns an approved proposal into that engine's pre-existing path model.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return 0.0 if result == 0.0 else result


def _coordinate(value: Sequence[object], field: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{field} requires three coordinates")
    return tuple(_finite(item, field) for item in value)  # type: ignore[return-value]


def _label(value: object, field: str = "band-path label") -> str:
    result = str(value).strip()
    if not result or any(item.isspace() for item in result):
        raise ValueError(f"{field} must be a non-empty single token")
    return result


def _number(value: float) -> str:
    rendered = format(value, ".16g")
    return f"{rendered}.0" if "." not in rendered and "e" not in rendered.casefold() else rendered


class BandPathMode(str, Enum):
    MANUAL = "manual"
    SUGGEST = "suggest"
    AUTOMATIC = "automatic"


class ProposalStatus(str, Enum):
    READY = "READY"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"


class SymmetryStability(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SYMMETRY_STABLE = "SYMMETRY_STABLE"
    SYMMETRY_AMBIGUOUS = "SYMMETRY_AMBIGUOUS"
    NOT_EVALUATED = "NOT_EVALUATED"


class SymmetryProviderError(RuntimeError):
    """A provider could not produce a safe crystallographic proposal."""


class SymmetryProviderUnavailable(SymmetryProviderError):
    """The optional symmetry provider is unavailable in this environment."""


class ProviderExecutionError(SymmetryProviderError):
    """An installed provider failed while performing symmetry analysis."""


class InvalidProviderResult(SymmetryProviderError):
    """A provider returned data that cannot safely be made into a proposal."""


@dataclass(frozen=True)
class CrystalStructure:
    """Neutral periodic structure in Angstrom and fractional coordinates."""

    cell: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    fractional_positions: tuple[tuple[float, float, float], ...]
    atomic_numbers: tuple[int, ...]

    def __post_init__(self) -> None:
        cell = tuple(_coordinate(row, "cell vector") for row in self.cell)
        positions = tuple(_coordinate(row, "fractional position") for row in self.fractional_positions)
        numbers = tuple(self.atomic_numbers)
        if not positions or len(positions) != len(numbers):
            raise ValueError("crystal structure requires one atomic number per position")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in numbers):
            raise ValueError("atomic numbers must be positive integers")
        determinant = (
            cell[0][0] * (cell[1][1] * cell[2][2] - cell[1][2] * cell[2][1])
            - cell[0][1] * (cell[1][0] * cell[2][2] - cell[1][2] * cell[2][0])
            + cell[0][2] * (cell[1][0] * cell[2][1] - cell[1][1] * cell[2][0])
        )
        if abs(determinant) <= 1e-12:
            raise ValueError("crystal structure cell has zero volume")
        object.__setattr__(self, "cell", cell)
        object.__setattr__(self, "fractional_positions", positions)
        object.__setattr__(self, "atomic_numbers", numbers)

    def canonical(self) -> dict[str, object]:
        return {
            "cell_angstrom": [[_number(value) for value in row] for row in self.cell],
            "fractional_positions": [[_number(value) for value in row] for row in self.fractional_positions],
            "atomic_numbers": list(self.atomic_numbers),
        }

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical())


@dataclass(frozen=True)
class BandPathSegment:
    """One requested continuous line; adjacent segments need not connect."""

    start_label: str
    start_coordinates: tuple[float, float, float]
    end_label: str
    end_coordinates: tuple[float, float, float]
    points: int

    def __post_init__(self) -> None:
        if isinstance(self.points, bool) or not isinstance(self.points, int) or self.points < 1:
            raise ValueError("band-path segment points must be a positive integer")
        object.__setattr__(self, "start_label", _label(self.start_label))
        object.__setattr__(self, "end_label", _label(self.end_label))
        object.__setattr__(self, "start_coordinates", _coordinate(self.start_coordinates, "segment start"))
        object.__setattr__(self, "end_coordinates", _coordinate(self.end_coordinates, "segment end"))

    def canonical(self) -> dict[str, object]:
        return {
            "start": {"label": self.start_label, "coordinates": [_number(item) for item in self.start_coordinates]},
            "end": {"label": self.end_label, "coordinates": [_number(item) for item in self.end_coordinates]},
            "points": self.points,
        }


@dataclass(frozen=True)
class BandPathRequest:
    """A manual, suggest, or automatic high-symmetry path request."""

    mode: BandPathMode | str
    structure: CrystalStructure | None = None
    manual_segments: tuple[BandPathSegment, ...] = ()
    scale: str = "ReciprocalLatticeVectors"
    convention: str = "hpkot"
    symprec: float = 1.0e-5
    angle_tolerance: float | None = None
    reference_distance: float = 0.025
    time_reversal: str = "auto"
    # Set only by a verified parent adapter, never inferred from omission.
    time_reversal_evidence: bool | None = None

    def __post_init__(self) -> None:
        try:
            mode = BandPathMode(self.mode)
        except ValueError as exc:
            raise ValueError("band-path mode must be manual, suggest, or automatic") from exc
        segments = tuple(self.manual_segments)
        scale = str(self.scale).strip()
        convention = str(self.convention).strip().casefold()
        if scale != "ReciprocalLatticeVectors":
            raise ValueError("M7.1 supports ReciprocalLatticeVectors paths")
        if convention != "hpkot":
            raise ValueError("M7.1 supports only the HPKOT convention")
        symprec = _finite(self.symprec, "symprec")
        reference_distance = _finite(self.reference_distance, "reference_distance")
        if symprec <= 0.0 or reference_distance <= 0.0:
            raise ValueError("symprec and reference_distance must be positive")
        angle = None if self.angle_tolerance is None else _finite(self.angle_tolerance, "angle_tolerance")
        time_reversal = str(self.time_reversal).strip().casefold()
        if time_reversal not in {"auto", "true", "false"}:
            raise ValueError("time_reversal must be auto, true, or false")
        if self.time_reversal_evidence is not None and not isinstance(self.time_reversal_evidence, bool):
            raise ValueError("time_reversal_evidence must be true, false, or absent")
        if mode is BandPathMode.MANUAL:
            if not segments:
                raise ValueError("manual paths require explicit segments")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "manual_segments", segments)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "convention", convention)
        object.__setattr__(self, "symprec", symprec)
        object.__setattr__(self, "angle_tolerance", angle)
        object.__setattr__(self, "reference_distance", reference_distance)
        object.__setattr__(self, "time_reversal", time_reversal)
        object.__setattr__(self, "time_reversal_evidence", self.time_reversal_evidence)

    @property
    def resolved_time_reversal(self) -> bool | None:
        """Resolve explicit policy, or only verified parent evidence for auto."""

        if self.time_reversal == "true":
            return True
        if self.time_reversal == "false":
            return False
        return self.time_reversal_evidence

    @property
    def tested_symprecs(self) -> tuple[float, ...]:
        return tuple(dict.fromkeys(self.symprec * multiplier for multiplier in (0.1, 1.0, 10.0)))


@dataclass(frozen=True)
class SymmetryAnalysis:
    spacegroup_number: int
    international_symbol: str
    bravais_lattice: str
    is_supercell: bool
    primitive_mapping: Mapping[str, object]
    transformation_required: bool = False
    point_coords: Mapping[str, Sequence[object]] = field(default_factory=dict)
    path: tuple[tuple[str, str], ...] = ()
    explicit_segments: tuple[tuple[int, int], ...] = ()
    augmented_path: bool | None = None
    has_inversion_symmetry: bool | None = None

    def __post_init__(self) -> None:
        if isinstance(self.spacegroup_number, bool) or not isinstance(self.spacegroup_number, int) or self.spacegroup_number < 1:
            raise ValueError("spacegroup_number must be a positive integer")
        if not str(self.international_symbol).strip() or not str(self.bravais_lattice).strip():
            raise ValueError("symmetry analysis requires space-group and Bravais metadata")
        object.__setattr__(self, "international_symbol", str(self.international_symbol).strip())
        object.__setattr__(self, "bravais_lattice", str(self.bravais_lattice).strip())
        object.__setattr__(self, "primitive_mapping", dict(self.primitive_mapping))
        points = {
            _label(label, "high-symmetry point label"): _coordinate(value, "high-symmetry point")
            for label, value in self.point_coords.items()
        }
        path = tuple((_label(start), _label(end)) for start, end in self.path)
        segments = tuple((int(start), int(stop)) for start, stop in self.explicit_segments)
        if any(start < 0 or stop <= start for start, stop in segments):
            raise ValueError("explicit_segments must contain non-empty [start, stop) ranges")
        if self.augmented_path is not None and not isinstance(self.augmented_path, bool):
            raise ValueError("augmented_path must be boolean when supplied")
        if self.has_inversion_symmetry is not None and not isinstance(self.has_inversion_symmetry, bool):
            raise ValueError("has_inversion_symmetry must be boolean when supplied")
        object.__setattr__(self, "point_coords", points)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "explicit_segments", segments)

    def canonical(self) -> dict[str, object]:
        return {
            "spacegroup_number": self.spacegroup_number,
            "international_symbol": self.international_symbol,
            "bravais_lattice": self.bravais_lattice,
            "is_supercell": self.is_supercell,
            "primitive_mapping": self.primitive_mapping,
            "transformation_required": self.transformation_required,
            "point_coords": {label: [_number(value) for value in coordinates] for label, coordinates in sorted(self.point_coords.items())},
            "path": [[start, end] for start, end in self.path],
            "explicit_segments": [[start, stop] for start, stop in self.explicit_segments],
            "augmented_path": self.augmented_path,
            "has_inversion_symmetry": self.has_inversion_symmetry,
        }


@dataclass(frozen=True)
class ProviderPath:
    analysis: SymmetryAnalysis
    segments: tuple[BandPathSegment, ...]

    def __post_init__(self) -> None:
        segments = tuple(self.segments)
        if not segments:
            raise ValueError("symmetry provider returned no band-path segments")
        object.__setattr__(self, "segments", segments)

    @property
    def topology(self) -> tuple[tuple[str, str], ...]:
        return self.analysis.path or tuple((segment.start_label, segment.end_label) for segment in self.segments)


class SymmetryPathProvider(Protocol):
    """Replaceable provider boundary; no third-party objects cross it."""

    @property
    def provider_name(self) -> str: ...

    @property
    def provider_version(self) -> str: ...

    @property
    def spglib_version(self) -> str | None: ...

    def generate(self, structure: CrystalStructure, request: BandPathRequest) -> ProviderPath: ...


@dataclass(frozen=True)
class BandPathGenerationProvenance:
    mode: BandPathMode
    provider: str | None
    provider_version: str | None
    spglib_version: str | None
    convention: str
    input_geometry_hash: str | None
    symprec: float
    angle_tolerance: float | None
    tested_symprecs: tuple[float, ...]
    symmetry_results: tuple[Mapping[str, object], ...]
    stability: SymmetryStability
    time_reversal: str
    resolved_time_reversal: bool | None
    reference_distance: float | None
    provider_error_code: str | None = None

    def canonical(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "spglib_version": self.spglib_version,
            "convention": self.convention,
            "input_geometry_hash": self.input_geometry_hash,
            "symprec": _number(self.symprec),
            "angle_tolerance": None if self.angle_tolerance is None else _number(self.angle_tolerance),
            "tested_symprecs": [_number(item) for item in self.tested_symprecs],
            "symmetry_results": [dict(item) for item in self.symmetry_results],
            "stability": self.stability.value,
            "time_reversal": self.time_reversal,
            "resolved_time_reversal": self.resolved_time_reversal,
            "reference_distance": None if self.reference_distance is None else _number(self.reference_distance),
            "provider_error_code": self.provider_error_code,
        }


@dataclass(frozen=True)
class BandPathProposal:
    status: ProposalStatus
    segments: tuple[BandPathSegment, ...]
    provenance: BandPathGenerationProvenance
    warnings: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "segments", tuple(self.segments))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        if self.status is ProposalStatus.READY and not self.segments:
            raise ValueError("a READY band-path proposal requires segments")

    def canonical(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "segments": [item.canonical() for item in self.segments],
            "provenance": self.provenance.canonical(),
            "warnings": list(self.warnings),
            "reason": self.reason,
        }

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical())

    def to_json(self) -> str:
        return json.dumps({**self.canonical(), "proposal_sha256": self.sha256}, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


@dataclass(frozen=True)
class BandPathResolution:
    proposal: BandPathProposal
    band_path_spec: object | None


def _symmetry_result(symprec: float, result: ProviderPath) -> dict[str, object]:
    return {
        "symprec": _number(symprec),
        **result.analysis.canonical(),
        "path_topology": [[start, end] for start, end in result.topology],
    }


class BandPathPlanner:
    """Apply M7.1 safety policy to a neutral symmetry-provider proposal."""

    def __init__(self, provider: SymmetryPathProvider | None = None) -> None:
        self.provider = provider

    def propose(self, request: BandPathRequest) -> BandPathProposal:
        if request.mode is BandPathMode.MANUAL:
            provenance = BandPathGenerationProvenance(
                mode=request.mode, provider=None, provider_version=None, spglib_version=None,
                convention=request.convention, input_geometry_hash=request.structure.sha256 if request.structure else None,
                symprec=request.symprec, angle_tolerance=request.angle_tolerance, tested_symprecs=(), symmetry_results=(),
                stability=SymmetryStability.NOT_APPLICABLE, time_reversal=request.time_reversal,
                resolved_time_reversal=request.resolved_time_reversal, reference_distance=None,
            )
            return BandPathProposal(ProposalStatus.READY, request.manual_segments, provenance)
        if request.structure is None:
            return self._blocked(request, f"{request.mode.value} paths require a crystal structure")
        if request.resolved_time_reversal is None:
            return self._policy_result(
                request,
                ProposalStatus.REVIEW if request.mode is BandPathMode.SUGGEST else ProposalStatus.BLOCKED,
                "TIME_REVERSAL_UNRESOLVED: verified M6 evidence does not establish time-reversal policy",
            )
        if self.provider is None:
            return self._blocked(
                request, "PROVIDER_UNAVAILABLE: install qraft[symmetry] or supply a SymmetryPathProvider",
                provider_error_code="PROVIDER_UNAVAILABLE",
            )
        assert request.structure is not None
        results: list[tuple[float, ProviderPath]] = []
        try:
            for symprec in request.tested_symprecs:
                results.append((symprec, self.provider.generate(request.structure, replace(request, symprec=symprec))))
        except SymmetryProviderUnavailable as exc:
            return self._blocked(request, f"PROVIDER_UNAVAILABLE: {exc}", results, provider_error_code="PROVIDER_UNAVAILABLE")
        except ProviderExecutionError as exc:
            return self._blocked(request, f"PROVIDER_EXECUTION_ERROR: {exc}", results, provider_error_code="PROVIDER_EXECUTION_ERROR")
        except InvalidProviderResult as exc:
            return self._blocked(request, f"INVALID_PROVIDER_RESULT: {exc}", results, provider_error_code="INVALID_PROVIDER_RESULT")
        except SymmetryProviderError as exc:
            return self._blocked(request, f"PROVIDER_EXECUTION_ERROR: {exc}", results, provider_error_code="PROVIDER_EXECUTION_ERROR")
        except (TypeError, ValueError) as exc:
            return self._blocked(request, f"symmetry provider produced invalid output: {exc}", results)
        central = next(result for symprec, result in results if symprec == request.symprec)
        signatures = {
            (
                result.analysis.spacegroup_number, result.analysis.international_symbol,
                result.analysis.bravais_lattice, result.analysis.is_supercell,
                result.analysis.has_inversion_symmetry, result.analysis.augmented_path,
                result.topology,
                tuple(sorted((label, coordinates) for label, coordinates in result.analysis.point_coords.items())),
            )
            for _, result in results
        }
        stability = SymmetryStability.SYMMETRY_STABLE if len(signatures) == 1 else SymmetryStability.SYMMETRY_AMBIGUOUS
        warnings: list[str] = []
        status = ProposalStatus.READY
        if stability is SymmetryStability.SYMMETRY_AMBIGUOUS:
            warnings.append("symmetry changes across tested symprec values")
            status = ProposalStatus.REVIEW if request.mode is BandPathMode.SUGGEST else ProposalStatus.BLOCKED
        if central.analysis.is_supercell:
            warnings.append("provider identifies the input as a supercell; primitive-cell BZ labels require review")
            status = ProposalStatus.REVIEW if request.mode is BandPathMode.SUGGEST else ProposalStatus.BLOCKED
        if central.analysis.transformation_required:
            warnings.append("provider requires a transformed structure; M6 ScientificIdentity and DM cannot be reused")
            status = ProposalStatus.REVIEW if request.mode is BandPathMode.SUGGEST else ProposalStatus.BLOCKED
        provenance = BandPathGenerationProvenance(
            mode=request.mode, provider=self.provider.provider_name, provider_version=self.provider.provider_version,
            spglib_version=self.provider.spglib_version, convention=request.convention,
            input_geometry_hash=request.structure.sha256, symprec=request.symprec,
            angle_tolerance=request.angle_tolerance,
            tested_symprecs=request.tested_symprecs,
            symmetry_results=tuple(_symmetry_result(symprec, result) for symprec, result in results),
            stability=stability, time_reversal=request.time_reversal,
            resolved_time_reversal=request.resolved_time_reversal, reference_distance=request.reference_distance,
        )
        return BandPathProposal(status, central.segments, provenance, tuple(warnings), "; ".join(warnings) or None)

    def resolve(self, request: BandPathRequest, compiler: Any) -> BandPathResolution:
        proposal = self.propose(request)
        if proposal.status is not ProposalStatus.READY:
            return BandPathResolution(proposal, None)
        return BandPathResolution(proposal, compiler(proposal, scale=request.scale))

    def _blocked(
        self,
        request: BandPathRequest,
        reason: str,
        results: Sequence[tuple[float, ProviderPath]] = (),
        provider_error_code: str | None = None,
    ) -> BandPathProposal:
        return self._policy_result(request, ProposalStatus.BLOCKED, reason, results, provider_error_code=provider_error_code)

    def _policy_result(
        self,
        request: BandPathRequest,
        status: ProposalStatus,
        reason: str,
        results: Sequence[tuple[float, ProviderPath]] = (),
        provider_error_code: str | None = None,
    ) -> BandPathProposal:
        provider = self.provider
        provenance = BandPathGenerationProvenance(
            mode=request.mode, provider=provider.provider_name if provider else None,
            provider_version=provider.provider_version if provider else None,
            spglib_version=provider.spglib_version if provider else None,
            convention=request.convention, input_geometry_hash=request.structure.sha256 if request.structure else None,
            symprec=request.symprec, angle_tolerance=request.angle_tolerance, tested_symprecs=request.tested_symprecs,
            symmetry_results=tuple(_symmetry_result(symprec, result) for symprec, result in results),
            stability=SymmetryStability.NOT_EVALUATED, time_reversal=request.time_reversal,
            resolved_time_reversal=request.resolved_time_reversal, reference_distance=request.reference_distance,
            provider_error_code=provider_error_code,
        )
        return BandPathProposal(status, (), provenance, (reason,), reason)
