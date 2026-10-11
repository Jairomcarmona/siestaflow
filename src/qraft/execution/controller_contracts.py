"""Offline validation of the native ADR-017 descriptor and ledger schemas."""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from qraft.contracts.serialization import contract_sha256


class ControllerContractError(ValueError):
    """A controller artifact cannot be trusted as a native contract."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ControllerContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ControllerContractError(f"non-finite JSON value: {value}")


def parse_controller_json(raw: bytes | str) -> dict[str, Any]:
    """Reject duplicate keys, non-finite values and non-object documents."""
    try:
        result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ControllerContractError(f"invalid controller JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ControllerContractError("controller JSON must be an object")
    return result


def _valid_utc_calendar(value: Any) -> bool:
    if not isinstance(value, str):
        return True  # type validation owns this failure
    if not value.endswith("Z"):
        return False
    try:
        datetime.strptime(value[:-1].partition(".")[0], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


@lru_cache(maxsize=3)
def _validator(name: str) -> Draft202012Validator:
    resources = files("qraft.execution.controller_schemas")
    schemas = [parse_controller_json(resources.joinpath(item).read_bytes()) for item in (
        "defs.schema.json", "qraft-controller-reservation.schema.json",
        "qraft-controller-ledger-entry.schema.json",
        "qraft-controller-resume-verdict.schema.json",
    )]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schema = next(schema for schema in schemas if schema["$id"].endswith("/" + name))
    Draft202012Validator.check_schema(schema)
    # The registry contains every reference: validation never downloads schemas.
    checker = FormatChecker()
    # jsonschema's base wheel does not install an RFC3339 checker. Make calendar
    # validation explicit; the normative UTC/nanosecond pattern stays untouched.
    checker.checks("date-time")(_valid_utc_calendar)
    return Draft202012Validator(schema, registry=registry, format_checker=checker)


def _validate(name: str, payload: Mapping[str, Any]) -> None:
    try:
        _validator(name).validate(dict(payload))
    except Exception as exc:
        raise ControllerContractError(f"invalid {name}: {exc}") from exc


def validate_controller_descriptor(payload: Mapping[str, Any]) -> None:
    _validate("qraft-controller-reservation.schema.json", payload)
    reserved, inner = payload["reserved"], payload["inner"]
    minimum = (inner["processes_per_node"] * inner["cpus_per_process"]
               * inner["max_concurrent"])
    if minimum <= 0 or reserved["min_cpus"] != minimum:
        raise ControllerContractError("invalid controller min_cpus")
    if reserved["runtime_cpus"] < minimum:
        raise ControllerContractError("CONTROLLER_ALLOCATION_INSUFFICIENT")
    if payload["attempt_number"] < 1 or payload["containment"]["supervisor"]["pid"] < 1:
        raise ControllerContractError("invalid controller attempt/supervisor identity")
    observed = reserved["scheduler_cpus_on_host"]
    if payload["allocation"]["scheduler"] == "slurm":
        if (observed["source"] != "SLURM_JOB_CPUS_PER_NODE"
                or observed["value"] is None
                or observed["value"] < reserved["runtime_cpus"]):
            raise ControllerContractError("CONTROLLER_ALLOCATION_MISMATCH")
    elif (observed["source"] != "LOCAL_PROFILE_DECLARATION"
          or observed["value"] != reserved["runtime_cpus"]):
        raise ControllerContractError("CONTROLLER_ALLOCATION_MISMATCH")
    if (payload["attempt_number"] == 1) != (payload["previous_attempt"] is None):
        raise ControllerContractError("invalid controller previous_attempt")
    if timestamp_key(payload["deadline"]["stop_launching_at"]) > timestamp_key(
        payload["deadline"]["hard_stop_at"]
    ):
        raise ControllerContractError("invalid controller deadline order")


def validate_controller_ledger_entry(payload: Mapping[str, Any]) -> None:
    _validate("qraft-controller-ledger-entry.schema.json", payload)
    if payload["seq"] < 1:
        raise ControllerContractError("ledger sequence must start at 1")
    if payload["event"] == "LAUNCH_INTENT" and (
        payload["ranks"] < 1 or payload["cpus_per_rank"] < 1
    ):
        raise ControllerContractError("ledger launch dimensions must be positive")


def validate_controller_resume_verdict(payload: Mapping[str, Any]) -> None:
    _validate("qraft-controller-resume-verdict.schema.json", payload)


def timestamp_key(value: str) -> tuple[str, int]:
    """Compare schema-validated UTC timestamps without losing nanoseconds."""
    whole, dot, fraction = value[:-1].partition(".")
    return whole, int(fraction.ljust(9, "0")) if dot else 0


def controller_descriptor_digest(payload: Mapping[str, Any]) -> str:
    """qraft.content-sha256-v1: the existing native canonical JSON digest."""
    validate_controller_descriptor(payload)
    return contract_sha256(payload)


def read_controller_ledger(path: Path) -> tuple[dict[str, Any], ...]:
    """A torn final line is evidence of interruption, never silently discarded."""
    lines: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        for raw in stream:
            if not raw.endswith(b"\n"):
                raise ControllerContractError("ledger has an incomplete line")
            entry = parse_controller_json(raw)
            validate_controller_ledger_entry(entry)
            lines.append(entry)
    return tuple(lines)
