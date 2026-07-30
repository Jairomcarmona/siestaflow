"""Conservative parsing of pipe-delimited ``sacct`` evidence."""

from __future__ import annotations

from typing import Any, Iterable


TERMINAL_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL",
    "OUT_OF_MEMORY", "PREEMPTED", "BOOT_FAIL", "DEADLINE",
})


def normalize_state(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    return raw.strip().split()[0].rstrip("+").upper() or None


def parse_sacct_main_row(lines: Iterable[str], job_id: str) -> dict[str, Any]:
    records = [line.rstrip("\r\n") for line in lines if line.strip()]
    rows = [record.split("|") for record in records]
    row = next((items for items in rows if items and items[0].strip() == job_id), None)
    values = (row or []) + [""] * (10 - len(row or []))
    state = normalize_state(values[1] if row else None)
    exit_code = values[2].strip() or None if row else None
    terminal = state in TERMINAL_STATES and bool(exit_code)
    known_nonterminal = state in {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED", "RESIZING"}
    return {
        "sacct_available": bool(records),
        "main_job_row_found": row is not None,
        "terminal_evidence": terminal,
        "review_required": bool(state and not terminal and not known_nonterminal) or (bool(records) and row is None),
        "state": state,
        "exit_code": exit_code,
        "elapsed": values[3].strip() or None if row else None,
        "alloc_tres": values[4].strip() or None if row else None,
        "max_rss": values[5].strip() or None if row else None,
        "node_list": values[6].strip() or None if row else None,
        "partition": values[7].strip() or None if row else None,
        "account": values[8].strip() or None if row else None,
        "qos": values[9].strip() or None if row else None,
    }
