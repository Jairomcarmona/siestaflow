"""WF-SURFACE read-only analysis for slab work functions."""
from __future__ import annotations

import math

from ..engines.siesta.fdf_parser import FDFParser


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _norm(vector):
    return math.sqrt(_dot(vector, vector))


def a3_perpendicular(cell, tol_deg):
    def angle(left, right):
        cosine = _dot(left, right) / (_norm(left) * _norm(right))
        return math.degrees(math.acos(cosine))

    alpha = angle(cell[1], cell[2])
    beta = angle(cell[0], cell[2])
    return {
        "alpha_deg": alpha,
        "beta_deg": beta,
        "perpendicular": abs(alpha - 90) <= tol_deg and abs(beta - 90) <= tol_deg,
    }


def _sample(profile, cell_c_A, z_A):
    count = len(profile)
    step = cell_c_A / count
    position = (z_A / step) % count
    index = math.floor(position)
    fraction = position - index
    return profile[index] * (1 - fraction) + profile[(index + 1) % count] * fraction


def _mean_over(profile, cell_c_A, start_A, end_A):
    count = len(profile)
    step = cell_c_A / count
    first = math.floor(start_A / step) + 1
    last = math.ceil(end_A / step) - 1
    points = [start_A]
    points.extend(index * step for index in range(first, last + 1))
    points.append(end_A)
    area = sum(
        0.5 * (_sample(profile, cell_c_A, left) + _sample(profile, cell_c_A, right)) * (right - left)
        for left, right in zip(points, points[1:])
    )
    return area / (end_A - start_A)


def _vacuum_interval(atoms_z_A, cell_c_A):
    atoms = sorted((value % cell_c_A) for value in atoms_z_A)
    best_gap = -1.0
    top = next_atom = 0.0
    for index, atom in enumerate(atoms):
        following = atoms[index + 1] if index + 1 < len(atoms) else atoms[0] + cell_c_A
        gap = following - atom
        if gap > best_gap:
            best_gap, top, next_atom = gap, atom, following
    return top, next_atom


def _plateau_plus(profile, cell_c_A, top_A, next_A, policy):
    end_A = next_A - policy["margin_A"]
    width_A = policy["window_A"]
    windows = []
    index = 0
    while True:
        start_A = top_A + policy["margin_A"] + index * policy["step_A"]
        if start_A + width_A > end_A + 1e-9:
            break
        values = [_sample(profile, cell_c_A, start_A + offset * width_A / 8) for offset in range(9)]
        positions = [offset * width_A / 8 for offset in range(9)]
        mean_x = sum(positions) / 9
        mean_y = sum(values) / 9
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(positions, values))
        denominator = sum((x - mean_x) ** 2 for x in positions)
        slope = numerator / denominator
        value_range_meV = (max(values) - min(values)) * 1000
        windows.append({
            "start": start_A,
            "flat": abs(slope) <= policy["slope_max_eV_per_A"] and value_range_meV <= policy["range_max_meV"],
            "mean": _mean_over(profile, cell_c_A, start_A, start_A + width_A),
        })
        index += 1

    if not windows:
        return None, "VACUUM_TOO_SMALL"
    any_flat = False
    index = 0
    while index < len(windows):
        if not windows[index]["flat"]:
            index += 1
            continue
        any_flat = True
        last = index
        while last + 1 < len(windows) and windows[last + 1]["flat"]:
            last += 1
        start_A = windows[index]["start"]
        end_A = windows[last]["start"] + width_A
        if end_A - start_A >= policy["width_min_A"] - 1e-9:
            means = [window["mean"] for window in windows[index:last + 1]]
            if (max(means) - min(means)) * 1000 > policy["stability_meV"]:
                return None, "PLATEAU_UNSTABLE"
            return {"from": start_A, "to": end_A, "mean": _mean_over(profile, cell_c_A, start_A, end_A)}, None
        index = last + 1
    return None, "PLATEAU_TOO_NARROW" if any_flat else "PLATEAU_NOT_FOUND"


def evaluate_surface(run, policy):
    sides = ("+z", "-z")

    def fail(reason):
        return {
            "verdict": "NOT_ESTABLISHED",
            "reasons": [reason],
            "faces": [
                {"side": side, "status": "NOT_ESTABLISHED", "reason": reason, "phi_eV": None, "plateau": None}
                for side in sides
            ],
        }

    if not a3_perpendicular(run["cell"], policy["perpendicular_tol_deg"])["perpendicular"]:
        return fail("A3_NOT_PERPENDICULAR")
    if run["scf_converged"] is not True:
        return fail("SCF_NOT_CONVERGED")
    if run["fermi_eV"] is None:
        return fail("FERMI_MISSING")
    if run["potential"] != policy["potential"] and not (run["potential"] == "VT" and policy["allow_vt"]):
        return fail("POTENTIAL_NOT_PERMITTED")
    dipole_mode = run["dipole_correction"]
    if isinstance(dipole_mode, str) and dipole_mode.casefold() in {"false", "none"} and not run["faces_equivalent"]:
        return fail("DIPOLE_UNCOMPENSATED_ASYMMETRIC")

    cell_c_A = run["cell"][2][2]
    top_A, next_A = _vacuum_interval(run["atoms_z_A"], cell_c_A)
    if next_A - top_A - 2 * policy["margin_A"] < policy["width_min_A"]:
        return fail("VACUUM_TOO_SMALL")
    plus, plus_reason = _plateau_plus(run["profile_eV"], cell_c_A, top_A, next_A, policy)
    profile = run["profile_eV"]
    count = len(profile)
    mirrored = [profile[(count - index) % count] for index in range(count)]
    minus, minus_reason = _plateau_plus(mirrored, cell_c_A, cell_c_A - next_A, cell_c_A - top_A, policy)

    def face(side, plateau, reason):
        if plateau is None:
            return {"side": side, "status": "NOT_ESTABLISHED", "reason": reason, "phi_eV": None, "plateau": None}
        start_A, end_A, mean_eV = plateau["from"], plateau["to"], plateau["mean"]
        measured = {"from_A": start_A, "to_A": end_A, "mean_eV": mean_eV, "width_A": end_A - start_A}
        if side == "-z":
            measured["from_A"], measured["to_A"] = cell_c_A - end_A, cell_c_A - start_A
        return {
            "side": side,
            "status": "ESTABLISHED",
            "reason": None,
            "phi_eV": mean_eV - run["fermi_eV"],
            "plateau": measured,
        }

    faces = [face("+z", plus, plus_reason), face("-z", minus, minus_reason)]
    reasons = sorted({item["reason"] for item in faces if item["reason"]})
    return {
        "verdict": "ESTABLISHED" if all(item["status"] == "ESTABLISHED" for item in faces) else "NOT_ESTABLISHED",
        "reasons": reasons,
        "faces": faces,
    }


def macroscopic_average(profile, cell_c_A, period_A, centers_A):
    return [_mean_over(profile, cell_c_A, center - period_A / 2, center + period_A / 2) for center in centers_A]


def fermi_comparable(cell_a, cell_b, tolerance_A):
    same = all(
        abs(cell_a[row][column] - cell_b[row][column]) <= tolerance_A
        for row in range(len(cell_a))
        for column in range(len(cell_a[row]))
    )
    return {"comparable": same, "reason": None if same else "CELLS_DIFFER"}


def phi_convergence(points, tolerance_meV):
    if len(points) < 3:
        return {"verdict": "INSUFFICIENT_POINTS", "deltas_meV": [], "last_delta_meV": None}
    deltas = [(current["phi_eV"] - previous["phi_eV"]) * 1000 for previous, current in zip(points, points[1:])]
    last_two = deltas[-2:]
    return {
        "verdict": "CONVERGED" if all(abs(delta) <= tolerance_meV for delta in last_two) else "NOT_CONVERGED",
        "deltas_meV": deltas,
        "last_delta_meV": deltas[-1],
    }


class SurfaceProtocol:
    """Read-only WF-SURFACE analysis and declared SIESTA slab values."""

    def analyze(self, run, *, policy):
        return evaluate_surface(run, policy)

    def a3_perpendicular(self, cell, *, tol_deg):
        return a3_perpendicular(cell, tol_deg)

    def dipole_correction(self, fdf_text):
        document = FDFParser().parse(fdf_text)
        values = document.scalars("Slab.DipoleCorrection")
        if not values:
            return {"accepted": True, "value": None, "effective": "NONE", "error": None}
        if len(values) > 1:
            return {"accepted": False, "value": None, "effective": None, "error": "LABEL_DUPLICATED"}
        tokens = values[0].value.split()
        value = tokens[0] if len(tokens) == 1 else ""
        normalized = value.casefold()
        effective = {"true": "CHARGE", "charge": "CHARGE", "vacuum": "VACUUM", "false": "NONE", "none": "NONE"}.get(normalized)
        if effective is None:
            return {"accepted": False, "value": None, "effective": None, "error": "KEYWORD_VALUE_INVALID"}
        return {"accepted": True, "value": value, "effective": effective, "error": None}

    def macroscopic_average(self, profile, *, cell_c_A, period_A, centers_A):
        return macroscopic_average(profile, cell_c_A, period_A, centers_A)

    def fermi_comparable(self, cell_a, cell_b, *, tolerance_A):
        return fermi_comparable(cell_a, cell_b, tolerance_A)

    def phi_convergence(self, points, *, tolerance_meV):
        return phi_convergence(points, tolerance_meV)
