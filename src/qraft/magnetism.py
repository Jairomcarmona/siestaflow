"""Engine-neutral magnetic intent for the supported M8-A/B spin channels.

The module contains collinear M8-A and non-collinear M8-B input intent only.
SOC, spirals, Hubbard physics, and execution mechanics deliberately have no
representation here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


def _number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite numeric value")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite numeric value") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite numeric value")
    return 0.0 if result == 0.0 else result


def _render_number(value: float) -> str:
    rendered = format(value, ".16g")
    return f"{rendered}.0" if "." not in rendered and "e" not in rendered.casefold() else rendered


class CollinearMomentToken(str, Enum):
    """The two SIESTA-defined maximum-polarization tokens."""

    MAXIMUM_UP = "+"
    MAXIMUM_DOWN = "-"


@dataclass(frozen=True)
class CollinearSpinMoment:
    """Requested initial spin on one one-based atomic index."""

    atom_index: int
    moment: float | CollinearMomentToken

    def __post_init__(self) -> None:
        if isinstance(self.atom_index, bool) or not isinstance(self.atom_index, int) or self.atom_index <= 0:
            raise ValueError("DM.InitSpin atom_index must be a positive integer")
        value = self.moment
        if isinstance(value, str):
            try:
                value = CollinearMomentToken(value)
            except ValueError as exc:
                raise ValueError("DM.InitSpin moment token must be '+', '-', or a finite numeric value") from exc
        if not isinstance(value, CollinearMomentToken):
            value = _number(value, "DM.InitSpin moment")
        object.__setattr__(self, "moment", value)

    @property
    def rendered(self) -> str:
        return self.moment.value if isinstance(self.moment, CollinearMomentToken) else _render_number(self.moment)

    def canonical(self) -> dict[str, object]:
        return {"atom_index": self.atom_index, "moment": self.rendered}


@dataclass(frozen=True)
class CollinearSpinSpec:
    """Immutable M8-A polarized intent.

    ``initial_moments is None`` is the physically meaningful absence of
    ``DM.InitSpin``.  ``initial_moments == ()`` is an explicit empty block and
    is intentionally distinct in canonical JSON and scientific identity.
    """

    initial_moments: tuple[CollinearSpinMoment, ...] | None = None
    fix_total_spin: bool = False
    total_spin: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.fix_total_spin, bool):
            raise ValueError("Spin.Fix must be boolean")
        moments = None if self.initial_moments is None else tuple(self.initial_moments)
        if moments is not None:
            normalized = tuple(
                item if isinstance(item, CollinearSpinMoment) else CollinearSpinMoment(**item)  # type: ignore[arg-type]
                for item in moments
            )
            indices = [item.atom_index for item in normalized]
            if len(indices) != len(set(indices)):
                raise ValueError("DM.InitSpin atom indices must be unique")
            moments = normalized
        total = None if self.total_spin is None else _number(self.total_spin, "Spin.Total")
        if total is not None and not self.fix_total_spin:
            raise ValueError("Spin.Total requires Spin.Fix true")
        object.__setattr__(self, "initial_moments", moments)
        object.__setattr__(self, "total_spin", total)

    @property
    def spin_mode(self) -> str:
        return "polarized"

    def validate_atom_count(self, atom_count: int) -> None:
        if isinstance(atom_count, bool) or not isinstance(atom_count, int) or atom_count <= 0:
            raise ValueError("NumberOfAtoms must be a positive integer for collinear spin")
        if self.initial_moments is not None and any(item.atom_index > atom_count for item in self.initial_moments):
            raise ValueError("DM.InitSpin atom_index exceeds NumberOfAtoms")

    def canonical(self) -> dict[str, object]:
        return {
            "spin_mode": self.spin_mode,
            "initialization": (
                {"kind": "absent"}
                if self.initial_moments is None
                else {"kind": "explicit", "moments": [item.canonical() for item in self.initial_moments]}
            ),
            "spin_fix": self.fix_total_spin,
            "spin_total": None if self.total_spin is None else _render_number(self.total_spin),
        }

    @property
    def sha256(self) -> str:
        encoded = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CollinearSpinSpec":
        allowed = {"initial_moments", "fix_total_spin", "total_spin"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError("M8-A does not support magnetic fields: " + ", ".join(unknown))
        raw = value.get("initial_moments")
        if raw is not None and not isinstance(raw, (list, tuple)):
            raise ValueError("initial_moments must be absent or a list")
        moments = None if raw is None else tuple(
            item if isinstance(item, CollinearSpinMoment) else CollinearSpinMoment(**item)
            for item in raw
        )
        return cls(
            initial_moments=moments,
            fix_total_spin=value.get("fix_total_spin", False),
            total_spin=value.get("total_spin"),
        )


@dataclass(frozen=True)
class NonCollinearSpinMoment:
    """One requested SIESTA non-collinear ``DM.InitSpin`` row.

    Omitted angles preserve SIESTA's implicit-z-direction semantics.  Both
    angles must otherwise be explicit; V1 intentionally does not normalize
    equivalent angular representations.
    """

    atom_index: int
    polarization: float | CollinearMomentToken
    theta_deg: float | None = None
    phi_deg: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.atom_index, bool) or not isinstance(self.atom_index, int) or self.atom_index <= 0:
            raise ValueError("DM.InitSpin atom_index must be a positive integer")
        polarization = self.polarization
        if isinstance(polarization, str):
            try:
                polarization = CollinearMomentToken(polarization)
            except ValueError as exc:
                raise ValueError("DM.InitSpin polarization must be '+', '-', or a finite numeric value") from exc
        if not isinstance(polarization, CollinearMomentToken):
            polarization = _number(polarization, "DM.InitSpin polarization")
        theta, phi = self.theta_deg, self.phi_deg
        if (theta is None) != (phi is None):
            raise ValueError("DM.InitSpin non-collinear directions require both theta_deg and phi_deg")
        if theta is not None:
            theta = _number(theta, "DM.InitSpin theta_deg")
            phi = _number(phi, "DM.InitSpin phi_deg")
        object.__setattr__(self, "polarization", polarization)
        object.__setattr__(self, "theta_deg", theta)
        object.__setattr__(self, "phi_deg", phi)

    @property
    def rendered_polarization(self) -> str:
        return self.polarization.value if isinstance(self.polarization, CollinearMomentToken) else _render_number(self.polarization)

    @property
    def rendered(self) -> str:
        if self.theta_deg is None:
            return self.rendered_polarization
        return " ".join((self.rendered_polarization, _render_number(self.theta_deg), _render_number(self.phi_deg)))

    def canonical(self) -> dict[str, object]:
        return {
            "atom_index": self.atom_index,
            "polarization": self.rendered_polarization,
            "theta_deg": None if self.theta_deg is None else _render_number(self.theta_deg),
            "phi_deg": None if self.phi_deg is None else _render_number(self.phi_deg),
            "direction": "implicit-z" if self.theta_deg is None else "explicit",
        }


@dataclass(frozen=True)
class NonCollinearSpinSpec:
    """Immutable M8-B intent for ``Spin non-colinear``.

    ``initial_moments is None`` is absence of the block; ``()`` is an explicit
    empty block.  These states remain distinct in the canonical evidence and
    thus in the already-existing FDF scientific identity.
    """

    initial_moments: tuple[NonCollinearSpinMoment, ...] | None = None

    def __post_init__(self) -> None:
        moments = None if self.initial_moments is None else tuple(self.initial_moments)
        if moments is not None:
            normalized = tuple(
                item if isinstance(item, NonCollinearSpinMoment) else NonCollinearSpinMoment(**item)  # type: ignore[arg-type]
                for item in moments
            )
            indices = [item.atom_index for item in normalized]
            if len(indices) != len(set(indices)):
                raise ValueError("DM.InitSpin atom indices must be unique")
            moments = normalized
        object.__setattr__(self, "initial_moments", moments)

    @property
    def spin_mode(self) -> str:
        return "non-collinear"

    def validate_atom_count(self, atom_count: int) -> None:
        if isinstance(atom_count, bool) or not isinstance(atom_count, int) or atom_count <= 0:
            raise ValueError("NumberOfAtoms must be a positive integer for non-collinear spin")
        if self.initial_moments is not None and any(item.atom_index > atom_count for item in self.initial_moments):
            raise ValueError("DM.InitSpin atom_index exceeds NumberOfAtoms")

    def canonical(self) -> dict[str, object]:
        return {
            "spin_mode": self.spin_mode,
            "initialization": (
                {"kind": "absent"}
                if self.initial_moments is None
                else {"kind": "explicit", "moments": [item.canonical() for item in self.initial_moments]}
            ),
        }

    @property
    def sha256(self) -> str:
        encoded = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NonCollinearSpinSpec":
        allowed = {"initial_moments"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError("M8-B does not support magnetic fields: " + ", ".join(unknown))
        raw = value.get("initial_moments")
        if raw is not None and not isinstance(raw, (list, tuple)):
            raise ValueError("initial_moments must be absent or a list")
        return cls(None if raw is None else tuple(
            item if isinstance(item, NonCollinearSpinMoment) else NonCollinearSpinMoment(**item)
            for item in raw
        ))
