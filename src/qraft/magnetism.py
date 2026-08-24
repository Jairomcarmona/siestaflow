"""Engine-neutral, collinear magnetic intent for M8-A.

This module deliberately models only the scalar spin channel accepted by
M8-A.  Non-collinear angles, SOC, spirals, and Hubbard physics have no
representation here and must therefore fail at a higher-level input boundary.
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
