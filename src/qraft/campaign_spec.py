"""Typed scientific campaign contracts, independent of HPC placement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

import yaml


ScientificScalar = str | int | float | bool
ScientificValue = ScientificScalar | tuple[int, ...]


class ParameterMode(str, Enum):
    FIXED = "fixed"
    SCAN = "scan"
    INHERIT = "inherit"
    AUTO_SUGGEST = "auto-suggest"
    DISABLED = "disabled"


class ParameterScope(str, Enum):
    GLOBAL = "global"
    SPECIES = "species"
    ATOM = "atom"
    STAGE = "stage"


class PreflightSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    ADVICE = "ADVICE"


@dataclass(frozen=True)
class ScanRange:
    start: float
    stop: float
    step: float

    def __post_init__(self) -> None:
        if self.step == 0:
            raise ValueError("scan range step cannot be zero")
        if (self.stop - self.start) * self.step < 0:
            raise ValueError("scan range step moves away from stop")

    def values(self) -> tuple[float, ...]:
        start, stop, step = map(Decimal, map(str, (self.start, self.stop, self.step)))
        values: list[float] = []
        current = start
        compare = (lambda value: value <= stop) if step > 0 else (lambda value: value >= stop)
        while compare(current):
            values.append(float(current))
            if len(values) > 10000:
                raise ValueError("scan range exceeds 10000 points")
            current += step
        return tuple(values)


@dataclass(frozen=True)
class InheritanceSource:
    evidence: str
    value: ScientificValue
    evidence_sha256: str | None = None
    compatible_identity: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence.strip():
            raise ValueError("inherit requires evidence provenance")
        if self.evidence_sha256 is not None and (
            len(self.evidence_sha256) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in self.evidence_sha256)
        ):
            raise ValueError("inherit evidence_sha256 must be a SHA-256 digest")


@dataclass(frozen=True)
class ParameterSpec:
    mode: ParameterMode
    value: ScientificValue | None = None
    values: tuple[ScientificValue, ...] = ()
    scan_range: ScanRange | None = None
    unit: str | None = None
    scope: ParameterScope = ParameterScope.GLOBAL
    metric: str | None = None
    tolerance: float | None = None
    severity: PreflightSeverity = PreflightSeverity.ERROR
    inheritance: InheritanceSource | None = None
    suggestion: str | None = None

    def __post_init__(self) -> None:
        if self.unit is not None and not self.unit.strip():
            raise ValueError("parameter unit must be non-empty")
        if self.tolerance is not None and self.tolerance < 0:
            raise ValueError("parameter tolerance must be nonnegative")
        declared = sum((self.value is not None, bool(self.values), self.scan_range is not None))
        if self.mode is ParameterMode.FIXED and (self.value is None or declared != 1):
            raise ValueError("fixed parameter requires only value")
        if self.mode is ParameterMode.SCAN:
            if declared != 1 or self.value is not None:
                raise ValueError("scan parameter requires exactly one of values or range")
            if len(self.resolved_values()) < 2:
                raise ValueError("scan parameter requires at least two points")
        if self.mode is ParameterMode.INHERIT and (self.inheritance is None or declared):
            raise ValueError("inherit requires only a provenance record")
        if self.mode is ParameterMode.AUTO_SUGGEST and declared:
            raise ValueError("auto-suggest cannot contain an executable value")
        if self.mode is ParameterMode.DISABLED and (declared or self.inheritance is not None):
            raise ValueError("disabled parameter cannot contain values")

    def resolved_values(self) -> tuple[ScientificValue, ...]:
        if self.mode is ParameterMode.FIXED:
            return (self.value,) if self.value is not None else ()
        if self.mode is ParameterMode.SCAN:
            return self.values or (() if self.scan_range is None else self.scan_range.values())
        if self.mode is ParameterMode.INHERIT:
            return (self.inheritance.value,) if self.inheritance else ()
        return ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ParameterSpec":
        data = dict(raw)
        allowed = {
            "mode", "value", "values", "grids", "range", "start", "stop", "step",
            "unit", "scope", "metric", "tolerance", "preflight", "inherit",
            "source", "suggestion",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown ParameterSpec fields: {', '.join(unknown)}")
        try:
            mode = ParameterMode(str(data.get("mode", "")).casefold())
        except ValueError as exc:
            raise ValueError(f"unsupported parameter mode: {data.get('mode')}") from exc
        values_raw = data.get("values", data.get("grids", ())) or ()
        if not isinstance(values_raw, (list, tuple)):
            raise ValueError("parameter values must be a list")
        values = tuple(_value(item) for item in values_raw)
        range_raw = data.get("range")
        if range_raw is None and any(key in data for key in ("start", "stop", "step")):
            range_raw = {key: data.get(key) for key in ("start", "stop", "step")}
        scan_range = None
        if range_raw is not None:
            if not isinstance(range_raw, Mapping) or set(range_raw) != {"start", "stop", "step"}:
                raise ValueError("range requires exactly start, stop and step")
            scan_range = ScanRange(*(float(range_raw[key]) for key in ("start", "stop", "step")))
        preflight = data.get("preflight", {}) or {}
        if not isinstance(preflight, Mapping):
            raise ValueError("parameter preflight must be a mapping")
        severity = PreflightSeverity(str(preflight.get("severity", "error")).upper())
        inherit_raw = data.get("inherit", data.get("source"))
        inheritance = None
        if inherit_raw is not None:
            if not isinstance(inherit_raw, Mapping):
                raise ValueError("inherit must be a mapping")
            inheritance = InheritanceSource(
                evidence=str(inherit_raw.get("evidence", "")),
                value=_value(inherit_raw.get("value")),
                evidence_sha256=(str(inherit_raw["sha256"]) if inherit_raw.get("sha256") else None),
                compatible_identity=(str(inherit_raw["compatible_identity"]) if inherit_raw.get("compatible_identity") else None),
            )
        return cls(
            mode=mode,
            value=_value(data["value"]) if "value" in data else None,
            values=values,
            scan_range=scan_range,
            unit=str(data["unit"]) if data.get("unit") is not None else None,
            scope=ParameterScope(str(data.get("scope", "global")).casefold()),
            metric=str(data["metric"]) if data.get("metric") is not None else None,
            tolerance=float(data["tolerance"]) if data.get("tolerance") is not None else None,
            severity=severity,
            inheritance=inheritance,
            suggestion=str(data["suggestion"]) if data.get("suggestion") is not None else None,
        )


@dataclass(frozen=True)
class ConvergenceCriterion:
    metric: str
    delta: float
    unit: str
    consecutive: int = 1

    def __post_init__(self) -> None:
        if self.metric not in {"energy", "energy_per_atom"}:
            raise ValueError(f"unsupported convergence metric: {self.metric}")
        if self.delta <= 0:
            raise ValueError("convergence delta must be positive")
        if self.consecutive <= 0:
            raise ValueError("consecutive must be positive")
        normalized = self.unit.casefold().replace(" ", "")
        allowed = {"ev"} if self.metric == "energy" else {"ev", "ev/atom"}
        if normalized not in allowed:
            raise ValueError(f"{self.metric} criterion requires unit eV or eV/atom")


@dataclass(frozen=True)
class SystemSpec:
    fdf: Path
    pseudo_manifest: Path | None = None
    structure: Path | None = None


@dataclass(frozen=True)
class EngineOption:
    name: str
    value: ScientificValue
    unit: str | None = None


@dataclass(frozen=True)
class ScientificSection:
    name: str
    parameters: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True)
class RelaxationSpec:
    """Explicit public request for the post-convergence fixed-cell relaxation."""

    run_type: str
    steps: int
    max_force: float
    unit: str

    def __post_init__(self) -> None:
        if self.run_type.upper() not in {"CG", "BROYDEN", "FIRE"}:
            raise ValueError("relaxation type must be CG, Broyden, or FIRE")
        if isinstance(self.steps, bool) or self.steps <= 0:
            raise ValueError("relaxation steps must be positive")
        if isinstance(self.max_force, bool) or self.max_force <= 0:
            raise ValueError("relaxation max_force must be positive")
        if not self.unit.strip():
            raise ValueError("relaxation unit must be non-empty")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RelaxationSpec | None":
        data = dict(raw)
        enabled = data.pop("enabled", None)
        if enabled is False:
            if data:
                raise ValueError("disabled relaxation cannot declare controls")
            return None
        if enabled is not True:
            return None
        allowed = {"type", "steps", "max_force", "unit"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError("unknown relaxation controls: " + ", ".join(unknown))
        missing = sorted(allowed - set(data))
        if missing:
            raise ValueError("relaxation requires: " + ", ".join(missing))
        return cls(
            run_type=str(data["type"]),
            steps=int(data["steps"]),
            max_force=float(data["max_force"]),
            unit=str(data["unit"]),
        )


@dataclass(frozen=True)
class CampaignSpec:
    campaign_id: str
    system: SystemSpec
    parameters: Mapping[str, ParameterSpec]
    criterion: ConvergenceCriterion
    protocol: str = "convergence"
    engine: str = "siesta"
    required_outputs: tuple[str, ...] = ()
    engine_options: tuple[EngineOption, ...] = ()
    sections: tuple[ScientificSection, ...] = ()
    relaxation: RelaxationSpec | None = None
    source: Path | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError(f"unsupported CampaignSpec schema: {self.schema_version}")
        if not self.campaign_id.strip() or not self.campaign_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("campaign_id must be a portable identifier")
        if self.protocol != "convergence":
            raise ValueError(f"unsupported campaign protocol: {self.protocol}")
        if self.engine != "siesta":
            raise ValueError(f"unsupported campaign engine: {self.engine}")
        object.__setattr__(self, "parameters", dict(sorted(self.parameters.items())))
        scans = [name for name, parameter in self.parameters.items() if parameter.mode is ParameterMode.SCAN]
        if len(scans) != 1:
            raise ValueError("convergence v1 requires exactly one scanned parameter")

    @property
    def scanned_parameter(self) -> tuple[str, ParameterSpec]:
        return next((item for item in self.parameters.items() if item[1].mode is ParameterMode.SCAN))

    @property
    def fingerprint(self) -> str:
        payload = self.to_dict(include_source=False)
        payload["system"] = {
            "fdf": _fingerprint_file(self.system.fdf, self.source),
            "pseudo_manifest": _fingerprint_file(self.system.pseudo_manifest, self.source),
            "structure": _fingerprint_file(self.system.structure, self.source),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_dict(self, *, include_source: bool = True) -> dict[str, Any]:
        value = asdict(self)
        value["system"] = {
            "fdf": str(self.system.fdf),
            "pseudo_manifest": str(self.system.pseudo_manifest) if self.system.pseudo_manifest else None,
            "structure": str(self.system.structure) if self.system.structure else None,
        }
        value["parameters"] = {
            name: _primitive(parameter) for name, parameter in self.parameters.items()
        }
        value["criterion"] = _primitive(self.criterion)
        value["engine_options"] = [_primitive(item) for item in self.engine_options]
        value["sections"] = [_primitive(item) for item in self.sections]
        value["relaxation"] = _primitive(self.relaxation) if self.relaxation else None
        value["source"] = str(self.source) if include_source and self.source else None
        return value

    @classmethod
    def load(cls, path: Path) -> "CampaignSpec":
        source = path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"campaign file does not exist: {source}")
        text = source.read_text(encoding="utf-8")
        raw = json.loads(text) if source.suffix.casefold() == ".json" else yaml.safe_load(text)
        if not isinstance(raw, Mapping):
            raise ValueError("campaign document must be a mapping")
        return cls.from_mapping(raw, source=source)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, source: Path | None = None) -> "CampaignSpec":
        data = dict(raw)
        forbidden = sorted(set(data) & {"partition", "nodes", "mpi_ranks", "launcher", "walltime", "execution"})
        if forbidden:
            raise ValueError("CampaignSpec cannot contain HPC placement: " + ", ".join(forbidden))
        allowed = {
            "schema_version", "campaign_id", "engine", "protocol", "system",
            "parameters", "criterion", "required_outputs", "engine_options",
            "mesh_cutoff", "kpoints", "basis", "theory", "occupations", "scf",
            "mixer", "charge", "spin", "soc", "dftu", "optional_physics",
            "vacuum", "supercell", "constraints", "relaxation", "acceptance",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown CampaignSpec sections: {', '.join(unknown)}")
        root = source.parent if source else Path.cwd()
        system_raw = data.get("system")
        if not isinstance(system_raw, Mapping) or not system_raw.get("fdf"):
            raise ValueError("campaign system requires fdf")
        system = SystemSpec(
            fdf=_resolved(root, system_raw["fdf"]),
            pseudo_manifest=_resolved(root, system_raw["pseudo_manifest"]) if system_raw.get("pseudo_manifest") else None,
            structure=_resolved(root, system_raw["structure"]) if system_raw.get("structure") else None,
        )
        parameters_raw = data.get("parameters", {}) or {}
        if not isinstance(parameters_raw, Mapping):
            raise ValueError("campaign parameters must be a mapping")
        merged: dict[str, Any] = dict(parameters_raw)
        if "mesh_cutoff" in data:
            merged.setdefault("mesh_cutoff", data["mesh_cutoff"])
        if "kpoints" in data and isinstance(data["kpoints"], Mapping) and "mode" in data["kpoints"]:
            merged.setdefault("kpoints", data["kpoints"])
        basis = data.get("basis")
        if isinstance(basis, Mapping):
            for key, canonical in (("basis_size", "basis_size"), ("energy_shift", "basis_energy_shift")):
                if key in basis:
                    merged.setdefault(canonical, basis[key])
        parameters = {
            str(name): ParameterSpec.from_mapping(value)
            for name, value in merged.items()
            if isinstance(value, Mapping)
        }
        if len(parameters) != len(merged):
            raise ValueError("each campaign parameter must be a ParameterSpec mapping")
        criterion_raw = data.get("criterion")
        if not isinstance(criterion_raw, Mapping):
            raise ValueError("convergence campaign requires criterion")
        criterion = ConvergenceCriterion(
            metric=str(criterion_raw.get("metric", "")),
            delta=float(criterion_raw.get("delta", 0)),
            unit=str(criterion_raw.get("unit", "")),
            consecutive=int(criterion_raw.get("consecutive", 1)),
        )
        protocol_raw = data.get("protocol", "convergence")
        protocol = str(protocol_raw.get("name")) if isinstance(protocol_raw, Mapping) else str(protocol_raw)
        options_raw = data.get("engine_options", {}) or {}
        if not isinstance(options_raw, Mapping):
            raise ValueError("engine_options must be a mapping")
        siesta_options = options_raw.get("siesta", options_raw)
        if not isinstance(siesta_options, Mapping):
            raise ValueError("engine_options.siesta must be a mapping")
        options = tuple(
            EngineOption(str(name), _value(value.get("value")), str(value.get("unit")) if value.get("unit") else None)
            if isinstance(value, Mapping) else EngineOption(str(name), _value(value))
            for name, value in sorted(siesta_options.items())
        )
        section_names = (
            "theory", "basis", "kpoints", "occupations", "scf", "mixer", "charge",
            "spin", "soc", "dftu", "optional_physics", "vacuum", "supercell",
            "constraints", "relaxation", "acceptance",
        )
        sections = tuple(
            ScientificSection(name, tuple(sorted(data[name])))
            for name in section_names if isinstance(data.get(name), Mapping)
        )
        relaxation = (
            RelaxationSpec.from_mapping(data["relaxation"])
            if isinstance(data.get("relaxation"), Mapping)
            else None
        )
        return cls(
            campaign_id=str(data.get("campaign_id", "")),
            system=system,
            parameters=parameters,
            criterion=criterion,
            protocol=protocol,
            engine=str(data.get("engine", "siesta")),
            required_outputs=tuple(map(str, data.get("required_outputs", ()) or ())),
            engine_options=options,
            sections=sections,
            relaxation=relaxation,
            source=source,
            schema_version=str(data.get("schema_version", "1.0")),
        )


def is_campaign_file(path: Path) -> bool:
    if path.suffix.casefold() not in {".yaml", ".yml", ".json"} or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text) if path.suffix.casefold() == ".json" else yaml.safe_load(text)
        return isinstance(value, Mapping) and "campaign_id" in value and "protocol" in value
    except (OSError, ValueError, yaml.YAMLError):
        return False


def _resolved(root: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _value(value: object) -> ScientificValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, (list, tuple)) and value and all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        return tuple(value)
    raise ValueError(f"unsupported scientific parameter value: {value!r}")


def _primitive(value: object) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_primitive(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    return value


def _fingerprint_file(path: Path | None, source: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    rendered = path.name
    if source is not None:
        try:
            rendered = path.resolve().relative_to(source.parent.resolve()).as_posix()
        except ValueError:
            rendered = path.name
    return {
        "path": rendered,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "MISSING",
    }
