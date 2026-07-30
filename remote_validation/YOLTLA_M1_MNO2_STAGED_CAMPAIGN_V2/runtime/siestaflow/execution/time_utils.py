"""Strict SLURM walltime parsing and canonicalization."""

from __future__ import annotations

import re


_TIME = re.compile(r"^(?:(\d+)-)?(\d{1,3}):(\d{2}):(\d{2})$")


def parse_slurm_walltime(value: str) -> int:
    """Return seconds for HH:MM:SS, HHH:MM:SS or D-HH:MM:SS."""
    text = str(value).strip()
    match = _TIME.fullmatch(text)
    if not match:
        raise ValueError(f"invalid SLURM walltime: {value}")
    days_raw, hours_raw, minutes_raw, seconds_raw = match.groups()
    days = int(days_raw or 0)
    hours = int(hours_raw)
    minutes = int(minutes_raw)
    seconds = int(seconds_raw)
    if minutes > 59 or seconds > 59:
        raise ValueError(f"invalid SLURM walltime minute/second field: {value}")
    if days_raw is not None and hours > 23:
        raise ValueError(f"day-form walltime hours must be 00-23: {value}")
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError("SLURM walltime must be positive")
    return total


def canonical_slurm_walltime(value: str) -> str:
    total = parse_slurm_walltime(value)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}-{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


__all__ = ["canonical_slurm_walltime", "parse_slurm_walltime"]

