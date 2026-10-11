"""ADR-017 ledger rules: stable native keys, across all controller attempts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .controller_contracts import (
    ControllerContractError, timestamp_key, validate_controller_ledger_entry,
)


_RESOURCE_CODES = frozenset({
    "HOSTS_OUTSIDE_RESERVATION", "CPU_EXCEEDED", "CONCURRENCY_EXCEEDED",
    "INTENT_AFTER_DEADLINE",
})


@dataclass(frozen=True)
class ControllerLedgerVerdict:
    code: str

    @property
    def accepted(self) -> bool:
        return self.code == "ACCEPT"

    @property
    def reason(self) -> str | None:
        if self.accepted:
            return None
        return ("CONTROLLER_RESERVATION_VIOLATED" if self.code in _RESOURCE_CODES
                else "CONTROLLER_LEDGER_INCONSISTENT")


def evaluate_controller_ledger(
    reservation: Mapping[str, Any], attempts: Sequence[Mapping[str, Any]],
) -> ControllerLedgerVerdict:
    """Return the first broken rule, in the normative conformance-vector order.

    `reservation` is the rules projection (task_id, hosts, runtime_cpus,
    max_concurrent, stop_launching_at); attempts are ordered native ledgers.
    No native identity, receipt state or evidence digest is synthesized here.
    """
    settled: set[tuple[str, str]] = set()
    finished_by_attempt: dict[str, set[tuple[str, str]]] = {}
    identity: str | None = None
    for attempt in attempts:
        opened: dict[str, tuple[tuple[str, str], int]] = {}
        closed: dict[str, tuple[tuple[str, str], bool]] = {}
        finished: set[tuple[str, str]] = set()
        launched = False
        for seq, line in enumerate(attempt["lines"], start=1):
            try:
                validate_controller_ledger_entry(line)
            except ControllerContractError:
                return ControllerLedgerVerdict("LEDGER_MALFORMED")
            if (line["seq"] != seq or line["task_id"] != reservation["task_id"]
                    or line["attempt_id"] != attempt["attempt_id"]):
                return ControllerLedgerVerdict("LEDGER_MALFORMED")
            native_identity = line["key"]["checkpoint_identity"]
            if identity is None:
                identity = native_identity
            if native_identity != identity:
                return ControllerLedgerVerdict("LEDGER_IDENTITY_CHANGED")
            key = (native_identity, line["key"]["node_id"])
            event = line["event"]
            trace = line.get("trace_id", "")
            if event == "LAUNCH_INTENT":
                if trace != f"{line['task_id']}/{line['attempt_id']}/{seq}":
                    return ControllerLedgerVerdict("LEDGER_MALFORMED")
                if timestamp_key(line["at"]) > timestamp_key(reservation["stop_launching_at"]):
                    return ControllerLedgerVerdict("INTENT_AFTER_DEADLINE")
                if any(host not in reservation["hosts"] for host in line["hosts"]):
                    return ControllerLedgerVerdict("HOSTS_OUTSIDE_RESERVATION")
                if key in settled:
                    return ControllerLedgerVerdict("DUPLICATE_SETTLED_LAUNCH")
                if any(item[0] == key for item in opened.values()):
                    return ControllerLedgerVerdict("CONCURRENT_KEY_LAUNCH")
                if len(opened) + 1 > reservation["max_concurrent"]:
                    return ControllerLedgerVerdict("CONCURRENCY_EXCEEDED")
                cpus = line["ranks"] * line["cpus_per_rank"]
                if sum(item[1] for item in opened.values()) + cpus > reservation["runtime_cpus"]:
                    return ControllerLedgerVerdict("CPU_EXCEEDED")
                opened[trace] = (key, cpus)
                launched = True
            elif event in {"LAUNCH_STARTED", "LAUNCH_FINISHED", "LAUNCH_ABANDONED"}:
                if trace not in opened or opened[trace][0] != key:
                    return ControllerLedgerVerdict("UNKNOWN_TRACE")
                if event != "LAUNCH_STARTED":
                    del opened[trace]
                    closed[trace] = (key, event == "LAUNCH_FINISHED")
                    if event == "LAUNCH_FINISHED":
                        finished.add(key)
            elif event == "NODE_SETTLED":
                if trace not in closed or not closed[trace][1]:
                    return ControllerLedgerVerdict("SETTLED_WITHOUT_FINISHED_LAUNCH")
                if closed[trace][0] != key:
                    return ControllerLedgerVerdict("SETTLED_KEY_MISMATCH")
                if key in settled:
                    return ControllerLedgerVerdict("DUPLICATE_SETTLEMENT")
                settled.add(key)
            elif event == "SETTLEMENT_RECOVERED":
                if launched:
                    return ControllerLedgerVerdict("RECOVERY_AFTER_LAUNCH")
                if key in settled:
                    return ControllerLedgerVerdict("DUPLICATE_SETTLEMENT")
                if key not in finished_by_attempt.get(line["source_attempt_id"], set()):
                    return ControllerLedgerVerdict("RECOVERED_WITHOUT_LAUNCH")
                settled.add(key)
        if attempt["end"] == "NORMAL" and opened:
            return ControllerLedgerVerdict("UNCLOSED_INTENT")
        finished_by_attempt[attempt["attempt_id"]] = finished
    return ControllerLedgerVerdict("ACCEPT")
