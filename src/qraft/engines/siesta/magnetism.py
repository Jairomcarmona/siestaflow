"""SIESTA 5.4 collinear-spin adaptation and fail-closed evidence parsing."""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Any

from ...contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from ...magnetism import (
    CollinearMomentToken,
    CollinearSpinMoment,
    CollinearSpinSpec,
    NonCollinearSpinMoment,
    NonCollinearSpinSpec,
    SpinOrbitSpec,
)
from .effective_fdf import MaterializedEffectiveFDF, materialize_effective_fdf, resolve_effective_fdf
from .input_closure import effective_species, resolve_pseudopotentials
from .models import normalize_label


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_OUT_OF_SCOPE_DIRECTIVES = {"noncollinearspin", "spinorbit", "spinspiral", "soc"}
_NONCOLLINEAR_FORBIDDEN_DIRECTIVES = {"spinfix", "spintotal", "spinspiral", "spinorbit", "spinpolarized", "soc", "noncollinearspin"}
_SOC_FORBIDDEN_DIRECTIVES = {
    "spinfix", "spintotal", "spinspiral", "spinspiralscale", "spinorbitstrength",
    "spinorbit", "spinpolarized", "noncollinearspin", "soc",
}


class PseudoRelativity(str, Enum):
    """Conservative, engine-local PSML evidence classification."""

    FULLY_RELATIVISTIC = "FULLY_RELATIVISTIC"
    SCALAR_RELATIVISTIC = "SCALAR_RELATIVISTIC"
    UNKNOWN = "UNKNOWN"


def _xml_local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def classify_psml_relativity(path: Path) -> tuple[PseudoRelativity, tuple[str, ...]]:
    """Classify only explicit PSML relativistic metadata/projector semantics.

    The classifier intentionally never considers file names, species labels or
    functional names.  A malformed document is an error; a valid document
    without unequivocal fully-relativistic evidence is ``UNKNOWN``.
    """

    if path.suffix.casefold() != ".psml":
        return PseudoRelativity.UNKNOWN, ("non-PSML pseudopotential",)
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise ValueError(f"PSML pseudopotential is malformed: {path.name}") from exc
    full_markers: list[str] = []
    scalar_markers: list[str] = []
    for element in root.iter():
        name = _xml_local_name(element)
        attributes = {key.rsplit("}", 1)[-1].casefold(): str(value).casefold() for key, value in element.attrib.items()}
        for key in ("relativity", "relativistic", "relativistic_type", "spin_orbit", "spinorbit"):
            value = attributes.get(key, "").replace("_", "-").replace(" ", "-")
            if value in {"full", "fully-relativistic", "spin-orbit", "spinorbit", "dirac"}:
                full_markers.append(f"{name}@{key}={value}")
            elif value in {"scalar", "scalar-relativistic"}:
                scalar_markers.append(f"{name}@{key}={value}")
        projector_set = attributes.get("set", "").replace("_", "-").replace(" ", "-")
        if name == "nonlocal-projectors" and projector_set in {"spin-orbit", "spinorbit", "lj"}:
            full_markers.append(f"{name}@set={projector_set}")
        elif name == "nonlocal-projectors" and projector_set in {"scalar", "scalar-relativistic"}:
            scalar_markers.append(f"{name}@set={projector_set}")
        # In PSML, explicit l/j projector channels are direct full-relativity
        # evidence.  Requiring both prevents an unrelated metadata ``j``
        # attribute from upgrading a pseudo accidentally.
        if ("projector" in name or name == "proj" or "semilocal" in name) and {"l", "j"}.issubset(attributes):
            full_markers.append(f"{name}@l,j-projector")
    # Fully-relativistic PSML commonly carries scalar-reference channels in
    # addition to its explicit ``spin_orbit``/``lj`` projector sets.  The full
    # evidence is therefore decisive; scalar evidence alone remains blocked.
    if full_markers:
        return PseudoRelativity.FULLY_RELATIVISTIC, tuple(sorted(set(full_markers)))
    if scalar_markers:
        return PseudoRelativity.SCALAR_RELATIVISTIC, tuple(sorted(set(scalar_markers)))
    return PseudoRelativity.UNKNOWN, ("no explicit full-relativity PSML metadata or l/j projector",)


def soc_pseudopotential_evidence(path: Path, *, pseudo_manifest: Path | None = None) -> dict[str, dict[str, object]]:
    """Return hash-bound, relative-path-free SOC pseudo evidence or fail closed."""

    effective = resolve_effective_fdf(path)
    pseudos = resolve_pseudopotentials(effective.source_root, effective_species(effective), pseudo_manifest)
    evidence: dict[str, dict[str, object]] = {}
    for species, pseudo in sorted(pseudos.items()):
        compatibility, markers = classify_psml_relativity(pseudo)
        if compatibility is not PseudoRelativity.FULLY_RELATIVISTIC:
            raise ValueError(
                f"M8-C Spin spin-orbit requires a fully relativistic PSML pseudopotential for {species}; "
                f"found {compatibility.value}"
            )
        evidence[species] = {
            "sha256": hashlib.sha256(pseudo.read_bytes()).hexdigest(),
            "format": "PSML",
            "compatibility": compatibility.value,
            "evidence": list(markers),
        }
    return evidence


def validate_magnetic_input(path: Path, *, pseudo_manifest: Path | None = None) -> CollinearSpinSpec | NonCollinearSpinSpec | SpinOrbitSpec | None:
    """Validate supported magnetic intent and mandatory SOC pseudo evidence.

    This is intentionally usable by both M6 and the canonical Single-FDF
    protocol.  It contains no execution policy and does not reinterpret a
    non-SOC pseudo.
    """

    spin = magnetic_spin_from_fdf(path)
    if getattr(spin, "spin_mode", None) == "spin-orbit":
        soc_pseudopotential_evidence(path, pseudo_manifest=pseudo_manifest)
    return spin


def _number(value: str, field: str) -> float:
    try:
        result = float(value.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"{field} is not finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} is not finite")
    return 0.0 if result == 0.0 else result


def _render_number(value: float) -> str:
    rendered = format(value, ".16g")
    return f"{rendered}.0" if "." not in rendered and "e" not in rendered.casefold() else rendered


def _logical(value: str, field: str) -> bool:
    token = value.strip().casefold()
    if token in {"t", "true", ".true.", "yes", "1"}:
        return True
    if token in {"f", "false", ".false.", "no", "0"}:
        return False
    raise ValueError(f"{field} must be a logical value")


def _atom_count(path: Path) -> int:
    scalar = resolve_effective_fdf(path).scalar("NumberOfAtoms")
    if scalar is None:
        raise ValueError("M8-A requires explicit NumberOfAtoms")
    try:
        count = int(scalar.value)
    except ValueError as exc:
        raise ValueError("NumberOfAtoms must be an integer") from exc
    if count <= 0:
        raise ValueError("NumberOfAtoms must be positive")
    return count


def _m8_directives(path: Path) -> bool:
    view = resolve_effective_fdf(path)
    return any(view.occurrence(label) is not None for label in ("Spin", "DM.InitSpin", "Spin.Fix", "Spin.Total"))


def collinear_spin_from_fdf(path: Path) -> CollinearSpinSpec | None:
    """Parse only M8-A collinear directives from a resolved scientific FDF.

    ``None`` means a legacy non-magnetic FDF.  Any partial or out-of-scope
    magnetic directive is rejected rather than being normalized away.
    """

    view = resolve_effective_fdf(path)
    spin = view.scalar("Spin")
    directives = _m8_directives(path)
    if spin is None:
        if directives:
            raise ValueError("M8-A magnetic directives require Spin polarized")
        return None
    for label, occurrence in view.occurrences.items():
        if label in _OUT_OF_SCOPE_DIRECTIVES or label.startswith("dftu") or label.startswith("hubbard"):
            raise ValueError(f"M8-A rejects out-of-scope magnetic directive: {occurrence.label}")
    mode = "".join(character.casefold() for character in spin.value if character.isalnum())
    if mode in {"none", "nonpolarized", "unpolarized"}:
        if view.block("DM.InitSpin") is not None or view.scalar("Spin.Fix") is not None or view.scalar("Spin.Total") is not None:
            raise ValueError("M8-A collinear directives require Spin polarized")
        return None
    if mode != "polarized":
        raise ValueError("M8-A supports only Spin polarized; non-collinear and SOC are out of scope")
    block = view.block("DM.InitSpin")
    moments: tuple[CollinearSpinMoment, ...] | None
    if block is None:
        moments = None
    else:
        if not block.closed:
            raise ValueError("DM.InitSpin block is unclosed")
        parsed: list[CollinearSpinMoment] = []
        for line in block.body_lines:
            raw = line.split("#", 1)[0].strip()
            if not raw:
                continue
            fields = raw.split()
            if len(fields) != 2:
                raise ValueError("DM.InitSpin supports only atom index and collinear moment")
            try:
                atom = int(fields[0])
            except ValueError as exc:
                raise ValueError("DM.InitSpin atom index is invalid") from exc
            value: float | str = fields[1]
            if fields[1] not in {"+", "-"}:
                value = _number(fields[1], "DM.InitSpin moment")
            parsed.append(CollinearSpinMoment(atom, value))
        moments = tuple(parsed)
    fix = view.scalar("Spin.Fix")
    fixed = _logical(fix.value, "Spin.Fix") if fix is not None else False
    total = view.scalar("Spin.Total")
    total_spin = _number(total.value, "Spin.Total") if total is not None else None
    spec = CollinearSpinSpec(moments, fixed, total_spin)
    spec.validate_atom_count(_atom_count(path))
    return spec


def _ensure_no_parent_conflict(path: Path, spec: CollinearSpinSpec) -> None:
    if not _m8_directives(path):
        return
    existing = collinear_spin_from_fdf(path)
    if existing is None or existing.canonical() != spec.canonical():
        raise ValueError("parent FDF magnetic directives conflict with the requested M8-A CollinearSpinSpec")


def _ensure_mulliken_end_compatible(path: Path) -> None:
    existing = resolve_effective_fdf(path).scalar("Charge.Mulliken")
    if existing is not None and existing.value.strip().casefold() != "end":
        raise ValueError("M8-A magnetic evidence requires Charge.Mulliken end")


def collinear_spin_updates(spec: CollinearSpinSpec, *, atom_count: int) -> tuple[dict[str, tuple[object, str | None]], dict[str, str]]:
    """Convert neutral M8-A intent into the modern SIESTA 5.4 FDF spelling."""

    spec.validate_atom_count(atom_count)
    # ``end`` is the modern SIESTA spelling used by the validated local FDF
    # corpus. It gives the final SCF an auditable atomic-population section;
    # the obsolete WriteMullikenPop knob is never introduced by M8-A.
    scalars: dict[str, tuple[object, str | None]] = {
        "Spin": ("polarized", None),
        "Charge.Mulliken": ("end", None),
    }
    blocks: dict[str, str] = {}
    if spec.initial_moments is not None:
        blocks["DM.InitSpin"] = "\n".join(f"  {item.atom_index} {item.rendered}" for item in spec.initial_moments)
    if spec.fix_total_spin:
        scalars["Spin.Fix"] = ("true", None)
    if spec.total_spin is not None:
        scalars["Spin.Total"] = (_render_number(spec.total_spin), None)
    return scalars, blocks


def materialize_collinear_spin_fdf(source: Path, destination_root: Path, spec: CollinearSpinSpec, *, primary_destination: str | None = None) -> MaterializedEffectiveFDF:
    """Use the established effective-FDF materializer; never a second renderer."""

    _ensure_no_parent_conflict(source, spec)
    _ensure_mulliken_end_compatible(source)
    scalars, blocks = collinear_spin_updates(spec, atom_count=_atom_count(source))
    return materialize_effective_fdf(source, destination_root, scalar_updates=scalars, block_updates=blocks, primary_destination=primary_destination)


def materialize_collinear_magnetic_evidence_fdf(source: Path, destination_root: Path, *, primary_destination: str | None = None) -> MaterializedEffectiveFDF | None:
    """Add required final-SCF Mulliken evidence to a polarized M8-A FDF."""

    if collinear_spin_from_fdf(source) is None:
        return None
    _ensure_mulliken_end_compatible(source)
    return materialize_effective_fdf(
        source,
        destination_root,
        scalar_updates={"Charge.Mulliken": ("end", None)},
        primary_destination=primary_destination,
    )


def _reject_m8b_scope(view: object) -> None:
    """Reject only directives that M8-B must never reinterpret or inherit."""

    occurrences = getattr(view, "occurrences")
    for label, occurrence in occurrences.items():
        if label in _NONCOLLINEAR_FORBIDDEN_DIRECTIVES or label.startswith("dftu") or label.startswith("hubbard"):
            raise ValueError(f"M8-B rejects out-of-scope magnetic directive: {occurrence.label}")


def noncollinear_spin_from_fdf(path: Path) -> NonCollinearSpinSpec | None:
    """Parse only the modern SIESTA 5.4 non-collinear input spelling.

    The parser retains absent versus empty initialization and explicit angles
    exactly, so FDF materialization and identity continue to bind the original
    scientific intent rather than an algebraically equivalent spin vector.
    """

    view = resolve_effective_fdf(path)
    spin = view.scalar("Spin")
    if spin is None:
        return None
    mode = "".join(character.casefold() for character in spin.value if character.isalnum())
    if mode != "noncolinear":
        return None
    _reject_m8b_scope(view)
    time_reversal = view.scalar("TimeReversalSymmetryForKpoints")
    if time_reversal is not None and _logical(time_reversal.value, "TimeReversalSymmetryForKpoints"):
        raise ValueError("M8-B rejects TimeReversalSymmetryForKpoints true for non-collinear spin")
    block = view.block("DM.InitSpin")
    moments: tuple[NonCollinearSpinMoment, ...] | None
    if block is None:
        moments = None
    else:
        if not block.closed:
            raise ValueError("DM.InitSpin block is unclosed")
        parsed: list[NonCollinearSpinMoment] = []
        for line in block.body_lines:
            raw = line.split("#", 1)[0].strip()
            if not raw:
                continue
            fields = raw.split()
            if len(fields) not in {2, 4}:
                raise ValueError("M8-B DM.InitSpin rows require atom polarization or atom polarization theta phi")
            try:
                atom = int(fields[0])
            except ValueError as exc:
                raise ValueError("DM.InitSpin atom index is invalid") from exc
            polarization: float | CollinearMomentToken
            if fields[1] in {"+", "-"}:
                polarization = CollinearMomentToken(fields[1])
            else:
                polarization = _number(fields[1], "DM.InitSpin polarization")
            if len(fields) == 2:
                parsed.append(NonCollinearSpinMoment(atom, polarization))
            else:
                parsed.append(NonCollinearSpinMoment(
                    atom, polarization,
                    _number(fields[2], "DM.InitSpin theta_deg"),
                    _number(fields[3], "DM.InitSpin phi_deg"),
                ))
        moments = tuple(parsed)
    spec = NonCollinearSpinSpec(moments)
    spec.validate_atom_count(_atom_count(path))
    return spec


def _reject_m8c_scope(view: object) -> None:
    """Reject controls that M8-C V1 must never silently reinterpret."""

    occurrences = getattr(view, "occurrences")
    for label, occurrence in occurrences.items():
        if label in _SOC_FORBIDDEN_DIRECTIVES or label.startswith("dftu") or label.startswith("hubbard"):
            raise ValueError(f"M8-C rejects out-of-scope SOC directive: {occurrence.label}")
    # Effective-FDF first-definition semantics are correct for SIESTA input,
    # but a later, ignored ``Spin spin-orbit+onsite`` must not disappear from
    # QRAFT's governed SOC request.  Inspect the complete closure for these
    # controls and for duplicate Spin declarations before rendering/execution.
    spin_scalars = []
    for document in getattr(view, "documents").values():
        for scalar in document.scalars():
            label = normalize_label(scalar.label)
            if label in _SOC_FORBIDDEN_DIRECTIVES or label.startswith("dftu") or label.startswith("hubbard"):
                raise ValueError(f"M8-C rejects out-of-scope SOC directive: {scalar.label}")
            if label == "spin":
                spin_scalars.append(scalar)
    if spin_scalars:
        if len(spin_scalars) != 1:
            raise ValueError("M8-C requires exactly one Spin spin-orbit declaration")
        mode = "".join(character.casefold() for character in spin_scalars[0].value if character.isalnum())
        if mode != "spinorbit":
            raise ValueError("M8-C supports full Spin spin-orbit only")


def _directional_moments_from_block(path: Path, *, milestone: str) -> tuple[NonCollinearSpinMoment, ...] | None:
    view = resolve_effective_fdf(path)
    block = view.block("DM.InitSpin")
    if block is None:
        return None
    if not block.closed:
        raise ValueError("DM.InitSpin block is unclosed")
    parsed: list[NonCollinearSpinMoment] = []
    for line in block.body_lines:
        raw = line.split("#", 1)[0].strip()
        if not raw:
            continue
        fields = raw.split()
        if len(fields) not in {2, 4}:
            raise ValueError(f"{milestone} DM.InitSpin rows require atom polarization or atom polarization theta phi")
        try:
            atom = int(fields[0])
        except ValueError as exc:
            raise ValueError("DM.InitSpin atom index is invalid") from exc
        polarization: float | CollinearMomentToken
        if fields[1] in {"+", "-"}:
            polarization = CollinearMomentToken(fields[1])
        else:
            polarization = _number(fields[1], "DM.InitSpin polarization")
        if len(fields) == 2:
            parsed.append(NonCollinearSpinMoment(atom, polarization))
        else:
            parsed.append(NonCollinearSpinMoment(
                atom, polarization,
                _number(fields[2], "DM.InitSpin theta_deg"),
                _number(fields[3], "DM.InitSpin phi_deg"),
            ))
    return tuple(parsed)


def spin_orbit_from_fdf(path: Path) -> SpinOrbitSpec | None:
    """Parse only canonical full ``Spin spin-orbit`` input, fail closed."""

    view = resolve_effective_fdf(path)
    spin = view.scalar("Spin")
    if spin is None:
        return None
    mode = "".join(character.casefold() for character in spin.value if character.isalnum())
    if mode != "spinorbit":
        return None
    _reject_m8c_scope(view)
    time_reversal = view.scalar("TimeReversalSymmetryForKpoints")
    if time_reversal is not None and _logical(time_reversal.value, "TimeReversalSymmetryForKpoints"):
        raise ValueError("M8-C rejects TimeReversalSymmetryForKpoints true for spin-orbit")
    spec = SpinOrbitSpec(_directional_moments_from_block(path, milestone="M8-C"))
    spec.validate_atom_count(_atom_count(path))
    return spec


def magnetic_spin_from_fdf(path: Path) -> CollinearSpinSpec | NonCollinearSpinSpec | SpinOrbitSpec | None:
    """Return one supported M8 magnetic intent without coercing spin modes."""

    view = resolve_effective_fdf(path)
    spin = view.scalar("Spin")
    if spin is None:
        if any(view.occurrence(label) is not None for label in ("DM.InitSpin", "Spin.Fix", "Spin.Total", "Spin.Spiral", "Spin.Orbit", "Spin.OrbitStrength")):
            raise ValueError("magnetic directives require an explicit supported Spin mode")
        return None
    mode = "".join(character.casefold() for character in spin.value if character.isalnum())
    if mode == "noncolinear":
        result = noncollinear_spin_from_fdf(path)
        assert result is not None
        return result
    if mode == "spinorbit":
        result = spin_orbit_from_fdf(path)
        assert result is not None
        return result
    return collinear_spin_from_fdf(path)


def noncollinear_spin_updates(spec: NonCollinearSpinSpec, *, atom_count: int) -> tuple[dict[str, tuple[object, str | None]], dict[str, str]]:
    spec.validate_atom_count(atom_count)
    scalars: dict[str, tuple[object, str | None]] = {
        "Spin": ("non-colinear", None),
        "Charge.Mulliken": ("end", None),
    }
    blocks: dict[str, str] = {}
    if spec.initial_moments is not None:
        blocks["DM.InitSpin"] = "\n".join(f"  {item.atom_index} {item.rendered}" for item in spec.initial_moments)
    return scalars, blocks


def materialize_noncollinear_spin_fdf(source: Path, destination_root: Path, spec: NonCollinearSpinSpec, *, primary_destination: str | None = None) -> MaterializedEffectiveFDF:
    """Render M8-B through the existing effective-FDF materializer only."""

    _reject_m8b_scope(resolve_effective_fdf(source))
    existing = magnetic_spin_from_fdf(source)
    if existing is not None and existing.canonical() != spec.canonical():
        raise ValueError("parent FDF magnetic directives conflict with the requested M8-B NonCollinearSpinSpec")
    _ensure_mulliken_end_compatible(source)
    scalars, blocks = noncollinear_spin_updates(spec, atom_count=_atom_count(source))
    return materialize_effective_fdf(source, destination_root, scalar_updates=scalars, block_updates=blocks, primary_destination=primary_destination)


def spin_orbit_updates(spec: SpinOrbitSpec, *, atom_count: int) -> tuple[dict[str, tuple[object, str | None]], dict[str, str]]:
    spec.validate_atom_count(atom_count)
    scalars: dict[str, tuple[object, str | None]] = {
        "Spin": ("spin-orbit", None),
        "Charge.Mulliken": ("end", None),
    }
    blocks: dict[str, str] = {}
    if spec.initial_moments is not None:
        blocks["DM.InitSpin"] = "\n".join(f"  {item.atom_index} {item.rendered}" for item in spec.initial_moments)
    return scalars, blocks


def materialize_spin_orbit_fdf(
    source: Path,
    destination_root: Path,
    spec: SpinOrbitSpec,
    *,
    pseudo_manifest: Path | None = None,
    primary_destination: str | None = None,
) -> MaterializedEffectiveFDF:
    """Render full SOC via effective-FDF after a mandatory PSML preflight."""

    _reject_m8c_scope(resolve_effective_fdf(source))
    existing = magnetic_spin_from_fdf(source)
    if existing is not None and existing.canonical() != spec.canonical():
        raise ValueError("parent FDF magnetic directives conflict with the requested M8-C SpinOrbitSpec")
    _ensure_mulliken_end_compatible(source)
    soc_pseudopotential_evidence(source, pseudo_manifest=pseudo_manifest)
    scalars, blocks = spin_orbit_updates(spec, atom_count=_atom_count(source))
    return materialize_effective_fdf(source, destination_root, scalar_updates=scalars, block_updates=blocks, primary_destination=primary_destination)


def materialize_magnetic_evidence_fdf(source: Path, destination_root: Path, *, primary_destination: str | None = None) -> MaterializedEffectiveFDF | None:
    """Materialize final-SCF Mulliken evidence for either supported M8 mode."""

    scalars = magnetic_evidence_scalar_updates(source)
    if not scalars:
        return None
    return materialize_effective_fdf(
        source,
        destination_root,
        scalar_updates=scalars,
        primary_destination=primary_destination,
    )


def magnetic_evidence_scalar_updates(source: Path) -> dict[str, tuple[object, str | None]]:
    """Return compatible final-SCF evidence updates for one materializer pass."""

    if magnetic_spin_from_fdf(source) is None:
        return {}
    _ensure_mulliken_end_compatible(source)
    return {"Charge.Mulliken": ("end", None)}


@dataclass(frozen=True)
class MagneticObservation:
    """Observed final collinear evidence, deliberately separate from request."""

    spin_mode: str
    total_moment: float | None
    atomic_moments: tuple[tuple[int, float], ...]
    parser: str = "qraft.siesta-5.4-collinear-magnetic-output-v2"

    def canonical(self) -> dict[str, object]:
        return {
            "spin_mode": self.spin_mode,
            "quantity": {
                "name": "mulliken_spin_population",
                "source": "Charge.Mulliken",
                "representation": "collinear",
                "component": "Sz",
                "unit": "electron_charge",
            },
            "total_moment": None if self.total_moment is None else _render_number(self.total_moment),
            "atomic_moments": [
                {"atom_index": index, "moment": _render_number(moment)}
                for index, moment in self.atomic_moments
            ],
            "parser": self.parser,
        }


def parse_collinear_magnetic_output(lines: Iterable[str], *, scf_converged: bool, required_atom_count: int | None = None) -> MagneticObservation:
    """Parse the documented collinear SIESTA 5.4 redata/Mulliken evidence.

    A Mulliken section, once announced, must finish with a well-formed total;
    incomplete or conflicting values are an error.  The section is optional:
    SIESTA may be configured not to emit atomic populations.
    """

    if not scf_converged:
        raise ValueError("magnetic output is not accepted before SCF convergence")
    raw = tuple(line.rstrip("\r\n") for line in lines)
    configuration = [line for line in raw if re.search(r"spin\s+configuration\s*=", line, re.I)]
    components = [line for line in raw if re.search(r"number\s+of\s+spin\s+components\s*=", line, re.I)]
    # SIESTA 5.4 writes the *FDF intent* as ``Spin polarized`` but reports
    # the runtime configuration as ``collinear``.  Both spellings are the
    # same two-component scalar-spin mode; neither authorizes non-collinear
    # or SOC output.
    if len(configuration) != 1 or not re.search(r"=\s*(?:polarized|collinear)\s*$", configuration[0], re.I):
        raise ValueError("magnetic output lacks unambiguous SIESTA Spin polarized evidence")
    if len(components) != 1 or not re.search(r"=\s*2\s*$", components[0]):
        raise ValueError("magnetic output lacks two collinear spin components")
    if any("non-collinear" in line.casefold() or "spin-orbit" in line.casefold() for line in raw):
        raise ValueError("M8-A rejects non-collinear or SOC output")

    atomic: list[tuple[int, float]] = []
    total_candidates: list[float] = []
    section = False
    section_total = False
    atomic_total = re.compile(r"^\s*(\d+)\s+Total\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")(?:\s|$)", re.I)
    # Native SIESTA 5.4 ``Charge.Mulliken end`` output has one row per atom:
    # ``index charge valence Sz species``.  Capture only the fourth numeric
    # column, never the charge or valence fields.
    atomic_row = re.compile(r"^\s*(\d+)\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")(?:\s+\S+)?\s*$", re.I)
    total_line = re.compile(r"^\s*Total\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")(?:\s|$)", re.I)
    named_total = re.compile(r"(?:total\s+(?:spin|magnetic\s+moment)|total\s+moment)\s*[:=]\s*(" + _FLOAT + r")", re.I)
    for line in raw:
        # SIESTA writes an orbital-resolved table before the atom summary.
        # Only the latter has the documented S/Sx/Sy/Sz columns and may be
        # used as M8-B evidence.
        if re.search(r"^\s*mulliken\s+atomic\s+populations\s*:\s*$", line, re.I):
            section = True
            continue
        if section:
            match = atomic_total.match(line)
            if match:
                atomic.append((int(match.group(1)), _number(match.group(3), "Mulliken atomic spin")))
                continue
            match = atomic_row.match(line)
            if match:
                atomic.append((int(match.group(1)), _number(match.group(4), "Mulliken atomic spin")))
                continue
            match = total_line.match(line)
            if match:
                total_candidates.append(_number(match.group(2), "Mulliken total spin"))
                section_total = True
                section = False
                continue
        match = named_total.search(line)
        if match:
            total_candidates.append(_number(match.group(1), "total magnetic moment"))
    if section and not section_total:
        raise ValueError("truncated Mulliken magnetic population section")
    indices = [index for index, _ in atomic]
    if len(indices) != len(set(indices)):
        raise ValueError("ambiguous duplicate Mulliken atomic magnetic moments")
    if required_atom_count is not None:
        if isinstance(required_atom_count, bool) or required_atom_count <= 0:
            raise ValueError("required Mulliken atom count must be positive")
        expected = set(range(1, required_atom_count + 1))
        if set(indices) != expected:
            raise ValueError("M8-A requires complete Mulliken atomic magnetic moments")
    if total_candidates and any(not math.isclose(total_candidates[0], value, rel_tol=0.0, abs_tol=1.0e-8) for value in total_candidates[1:]):
        raise ValueError("ambiguous conflicting total magnetic moments")
    return MagneticObservation("polarized", total_candidates[0] if total_candidates else None, tuple(sorted(atomic)))


@dataclass(frozen=True)
class NonCollinearMagneticObservation:
    """Observed vector Mulliken spin population, never inferred from request."""

    atomic_vectors: tuple[tuple[int, float, float, float, float], ...]
    total_vector: tuple[float, float, float]
    total_magnitude: float | None
    parser: str = "qraft.siesta-5.4-noncollinear-mulliken-v1"

    @property
    def spin_mode(self) -> str:
        return "non-collinear"

    def canonical(self) -> dict[str, object]:
        return {
            "spin_mode": self.spin_mode,
            "quantity": {
                "name": "mulliken_spin_population",
                "source": "Charge.Mulliken",
                "representation": "cartesian",
                "components": ["Sx", "Sy", "Sz"],
                "magnitude": "S",
                "unit": "electron_charge",
            },
            "atomic_vectors": [
                {"atom_index": index, "S": _render_number(magnitude), "Sx": _render_number(sx), "Sy": _render_number(sy), "Sz": _render_number(sz)}
                for index, magnitude, sx, sy, sz in self.atomic_vectors
            ],
            "total": {
                "Sx": _render_number(self.total_vector[0]),
                "Sy": _render_number(self.total_vector[1]),
                "Sz": _render_number(self.total_vector[2]),
                "S": None if self.total_magnitude is None else _render_number(self.total_magnitude),
            },
            "parser": self.parser,
        }


def _validate_vector_magnitude(magnitude: float, sx: float, sy: float, sz: float, *, field: str) -> None:
    # Native SIESTA 5.4.2 prints these four values to six decimal places.
    # A vector magnitude recomputed from independently rounded components can
    # differ by up to roughly 9e-7, so accept only that printing uncertainty.
    if magnitude < 0.0 or not math.isclose(magnitude, math.sqrt(sx * sx + sy * sy + sz * sz), rel_tol=1.0e-7, abs_tol=1.0e-6):
        raise ValueError(f"{field} Mulliken spin magnitude is inconsistent with Sx/Sy/Sz")


def parse_noncollinear_magnetic_output(lines: Iterable[str], *, scf_converged: bool, required_atom_count: int | None = None) -> NonCollinearMagneticObservation:
    """Fail-closed parser for a documented-vector-shaped SIESTA Mulliken table.

    It requires explicit S/Sx/Sy/Sz header evidence and maps rows by those
    columns, never by charge or valence position alone.  The real-SIESTA gate
    will confront this deliberately narrow parser with native stdout before
    accepting M8-B physics.
    """

    if not scf_converged:
        raise ValueError("magnetic output is not accepted before SCF convergence")
    raw = tuple(line.rstrip("\r\n") for line in lines)
    configuration = [line for line in raw if re.search(r"spin\s+configuration\s*=", line, re.I)]
    components = [line for line in raw if re.search(r"number\s+of\s+spin\s+components\s*=", line, re.I)]
    if len(configuration) != 1 or not re.search(r"=\s*non[ -]?col(?:inear|linear)\s*$", configuration[0], re.I):
        raise ValueError("magnetic output lacks unambiguous SIESTA Spin non-colinear evidence")
    if len(components) != 1 or not re.search(r"=\s*4\s*$", components[0]):
        raise ValueError("magnetic output lacks four non-collinear spin components")
    if any("spin-orbit" in line.casefold() or re.search(r"\bSOC\b", line, re.I) for line in raw):
        raise ValueError("M8-B rejects SOC output")

    atom_row = re.compile(r"^\s*(\d+)\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")(?:\s+\S+)?\s*$")
    total_row_with_valence = re.compile(r"^\s*Total\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", re.I)
    total_row_native = re.compile(r"^\s*Total\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", re.I)
    section = False
    header_seen = False
    atomic: list[tuple[int, float, float, float, float]] = []
    total: tuple[float, float, float, float] | None = None
    for line in raw:
        # SIESTA writes an orbital-resolved table before the atom summary.
        # Only the latter has the documented S/Sx/Sy/Sz columns and may be
        # used as M8-B evidence.
        if re.search(r"^\s*mulliken\s+atomic\s+populations\s*:\s*$", line, re.I):
            section = True
            continue
        if not section:
            continue
        compact = re.sub(r"\s+", "", line.casefold())
        # SIESTA 5.4.2 labels the magnitude column as bare ``S`` while
        # retaining ``[e]`` on Cartesian components.  Require that exact
        # documented shape rather than assuming a unit marker on all four.
        if re.search(r"\bs\b", line, re.I) and all(token in compact for token in ("sx[e]", "sy[e]", "sz[e]")):
            header_seen = True
            continue
        match = atom_row.match(line)
        if match:
            if not header_seen:
                raise ValueError("non-collinear Mulliken table lacks S/Sx/Sy/Sz header")
            index = int(match.group(1))
            magnitude, sx, sy, sz = (_number(match.group(position), "Mulliken vector component") for position in (4, 5, 6, 7))
            _validate_vector_magnitude(magnitude, sx, sy, sz, field="atomic")
            atomic.append((index, magnitude, sx, sy, sz))
            continue
        if re.match(r"^\s*\d+\s+", line):
            raise ValueError("malformed non-collinear Mulliken atomic row")
        match = total_row_with_valence.match(line)
        if match:
            if not header_seen:
                raise ValueError("non-collinear Mulliken table lacks S/Sx/Sy/Sz header")
            magnitude, sx, sy, sz = (_number(match.group(position), "Mulliken total vector component") for position in (3, 4, 5, 6))
            _validate_vector_magnitude(magnitude, sx, sy, sz, field="total")
            total = (magnitude, sx, sy, sz)
            section = False
            continue
        match = total_row_native.match(line)
        if match:
            if not header_seen:
                raise ValueError("non-collinear Mulliken table lacks S/Sx/Sy/Sz header")
            magnitude, sx, sy, sz = (_number(match.group(position), "Mulliken total vector component") for position in (2, 3, 4, 5))
            _validate_vector_magnitude(magnitude, sx, sy, sz, field="total")
            total = (magnitude, sx, sy, sz)
            section = False
            continue
        if re.match(r"^\s*Total\b", line, re.I):
            raise ValueError("malformed non-collinear Mulliken total row")
    if section:
        raise ValueError("truncated non-collinear Mulliken magnetic population section")
    if not header_seen or total is None:
        raise ValueError("non-collinear Mulliken magnetic evidence is incomplete")
    indices = [item[0] for item in atomic]
    if len(indices) != len(set(indices)):
        raise ValueError("ambiguous duplicate Mulliken atomic magnetic vectors")
    if required_atom_count is not None and set(indices) != set(range(1, required_atom_count + 1)):
        raise ValueError("M8-B requires complete Mulliken atomic magnetic vectors")
    return NonCollinearMagneticObservation(tuple(sorted(atomic)), (total[1], total[2], total[3]), total[0])


@dataclass(frozen=True)
class SpinOrbitMagneticObservation(NonCollinearMagneticObservation):
    """Full-SOC vector evidence using the same Mulliken quantity semantics."""

    parser: str = "qraft.siesta-5.4-spin-orbit-mulliken-v1"

    @property
    def spin_mode(self) -> str:
        return "spin-orbit"


def parse_spin_orbit_magnetic_output(lines: Iterable[str], *, scf_converged: bool, required_atom_count: int | None = None) -> SpinOrbitMagneticObservation:
    """Fail closed on synthetic SOC-shaped SIESTA output until real acceptance.

    The vector table is deliberately parsed with the M8-B quantity semantics,
    but SOC declaration is required independently so a non-collinear run can
    never be relabelled as a spin-orbit calculation.
    """

    if not scf_converged:
        raise ValueError("magnetic output is not accepted before SCF convergence")
    raw = tuple(line.rstrip("\r\n") for line in lines)
    configuration = [line for line in raw if re.search(r"spin\s+configuration\s*=", line, re.I)]
    components = [line for line in raw if re.search(r"number\s+of\s+spin\s+components\s*=", line, re.I)]
    if len(configuration) != 1 or not re.search(r"=\s*spin[ -]?orbit(?:\+offsite)?\s*$", configuration[0], re.I):
        raise ValueError("magnetic output lacks unambiguous SIESTA Spin spin-orbit evidence")
    offsite = bool(re.search(r"\+offsite\s*$", configuration[0], re.I))
    expected_components = 8 if offsite else 4
    if len(components) != 1 or not re.search(rf"=\s*{expected_components}\s*$", components[0]):
        raise ValueError(f"magnetic output lacks {expected_components} SOC spin components")
    if offsite and not any(
        "spin-orbit semi-local pseudopotentials" in line.casefold() or "enl(+so)" in line.casefold()
        for line in raw
    ):
        raise ValueError("spin-orbit+offsite output lacks SOC runtime evidence")
    atom_row = re.compile(r"^\s*(\d+)\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")(?:\s+\S+)?\s*$")
    total_row_with_valence = re.compile(r"^\s*Total\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", re.I)
    total_row_native = re.compile(r"^\s*Total\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", re.I)
    section = False
    header_seen = False
    atomic: list[tuple[int, float, float, float, float]] = []
    total: tuple[float, float, float, float] | None = None
    for line in raw:
        # A second table-shaped total after the accepted one is evidence of a
        # corrupted/ambiguous Mulliken section, not a value to silently use.
        # Other later SIESTA summaries do not have this five/six-number shape.
        if total is not None:
            duplicate = total_row_with_valence.match(line) or total_row_native.match(line)
            if duplicate:
                positions = (3, 4, 5, 6) if duplicate.re is total_row_with_valence else (2, 3, 4, 5)
                values = tuple(_number(duplicate.group(position), "SOC duplicate total vector component") for position in positions)
                if not all(math.isclose(left, right, rel_tol=0.0, abs_tol=1.0e-6) for left, right in zip(values, total)):
                    raise ValueError("conflicting SOC Mulliken total vectors")
                raise ValueError("ambiguous duplicate SOC Mulliken total vector")
        if re.search(r"^\s*mulliken\s+atomic\s+populations\s*:\s*$", line, re.I):
            section = True
            continue
        if not section:
            continue
        compact = re.sub(r"\s+", "", line.casefold())
        if re.search(r"\bs\b", line, re.I) and all(token in compact for token in ("sx[e]", "sy[e]", "sz[e]")):
            header_seen = True
            continue
        match = atom_row.match(line)
        if match:
            if not header_seen:
                raise ValueError("SOC Mulliken table lacks S/Sx/Sy/Sz header")
            index = int(match.group(1))
            magnitude, sx, sy, sz = (_number(match.group(position), "SOC Mulliken vector component") for position in (4, 5, 6, 7))
            _validate_vector_magnitude(magnitude, sx, sy, sz, field="SOC atomic")
            atomic.append((index, magnitude, sx, sy, sz))
            continue
        if re.match(r"^\s*\d+\s+", line):
            raise ValueError("malformed SOC Mulliken atomic row")
        match = total_row_with_valence.match(line)
        if match:
            if not header_seen:
                raise ValueError("SOC Mulliken table lacks S/Sx/Sy/Sz header")
            magnitude, sx, sy, sz = (_number(match.group(position), "SOC Mulliken total vector component") for position in (3, 4, 5, 6))
            _validate_vector_magnitude(magnitude, sx, sy, sz, field="SOC total")
            total = (magnitude, sx, sy, sz)
            section = False
            continue
        match = total_row_native.match(line)
        if match:
            if not header_seen:
                raise ValueError("SOC Mulliken table lacks S/Sx/Sy/Sz header")
            magnitude, sx, sy, sz = (_number(match.group(position), "SOC Mulliken total vector component") for position in (2, 3, 4, 5))
            _validate_vector_magnitude(magnitude, sx, sy, sz, field="SOC total")
            total = (magnitude, sx, sy, sz)
            section = False
            continue
        if re.match(r"^\s*Total\b", line, re.I):
            raise ValueError("malformed SOC Mulliken total row")
    if section:
        raise ValueError("truncated SOC Mulliken magnetic population section")
    if not header_seen or total is None:
        raise ValueError("SOC Mulliken magnetic evidence is incomplete")
    indices = [item[0] for item in atomic]
    if len(indices) != len(set(indices)):
        raise ValueError("ambiguous duplicate SOC Mulliken atomic vectors")
    if required_atom_count is not None and set(indices) != set(range(1, required_atom_count + 1)):
        raise ValueError("M8-C requires complete SOC Mulliken atomic vectors")
    return SpinOrbitMagneticObservation(tuple(sorted(atomic)), (total[1], total[2], total[3]), total[0])


def parse_magnetic_output(lines: Iterable[str], *, requested: CollinearSpinSpec | NonCollinearSpinSpec | SpinOrbitSpec, scf_converged: bool, required_atom_count: int | None = None) -> MagneticObservation | NonCollinearMagneticObservation | SpinOrbitMagneticObservation:
    if isinstance(requested, SpinOrbitSpec):
        return parse_spin_orbit_magnetic_output(lines, scf_converged=scf_converged, required_atom_count=required_atom_count)
    if isinstance(requested, NonCollinearSpinSpec):
        return parse_noncollinear_magnetic_output(lines, scf_converged=scf_converged, required_atom_count=required_atom_count)
    return parse_collinear_magnetic_output(lines, scf_converged=scf_converged, required_atom_count=required_atom_count)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def magnetic_artifact_envelope(*, parent_scientific_identity_sha256: str, requested: CollinearSpinSpec | NonCollinearSpinSpec | SpinOrbitSpec, observed: MagneticObservation | NonCollinearMagneticObservation | SpinOrbitMagneticObservation, final_fdf: Path, stdout: Path, scf_converged: bool, siesta_version: str | None, stdout_relative_path: str | None = None, soc_pseudo_evidence: Mapping[str, Mapping[str, object]] | None = None) -> dict[str, object]:
    """Machine-readable M8-A/B evidence; requested intent never claims outcome."""

    if observed.spin_mode != requested.spin_mode or not scf_converged:
        raise ValueError("a magnetic state artifact requires converged evidence matching the requested spin mode")
    source: dict[str, object] = {
        "final_fdf_sha256": _sha(final_fdf),
        "stdout_sha256": _sha(stdout),
    }
    if stdout_relative_path is not None:
        relative = Path(stdout_relative_path)
        if relative.is_absolute() or ".." in relative.parts or not str(relative):
            raise ValueError("magnetic stdout evidence path must remain relative")
        source["stdout_relative_path"] = relative.as_posix()
    if isinstance(requested, SpinOrbitSpec) and not soc_pseudo_evidence:
        raise ValueError("a spin-orbit magnetic artifact requires fully relativistic pseudo evidence")
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "artifact_id": "magnetic-state",
        "artifact_type": "qraft.magnetic-state",
        "authority": "PROVISIONAL",
        "parent_scientific_identity_sha256": parent_scientific_identity_sha256,
        "requested": requested.canonical(),
        "observed": observed.canonical(),
        "converged": True,
        "source": source,
        "siesta": {
            "version": siesta_version,
            "semantics": (
                "Spin non-colinear / DM.InitSpin polarization theta phi"
                if requested.spin_mode == "non-collinear"
                else "Spin spin-orbit / DM.InitSpin polarization theta phi"
                if requested.spin_mode == "spin-orbit"
                else "Spin polarized / DM.InitSpin collinear"
            ),
        },
    }
    if isinstance(requested, SpinOrbitSpec):
        payload["soc"] = {
            "enabled": True,
            "implementation": "full",
            "pseudopotentials": {name: dict(value) for name, value in sorted(soc_pseudo_evidence.items())},
        }
    return ContractEnvelope.create(SCIENTIFIC_ARTIFACT, producer="qraft.siesta-magnetism", payload=payload).to_dict()
