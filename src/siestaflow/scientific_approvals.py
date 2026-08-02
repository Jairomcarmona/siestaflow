"""Persisted human approval and hash-bound numerical-profile propagation.

Convergence evaluators only produce a recommendation.  This module turns a
reviewed recommendation into two immutable public contracts: a human decision
and, only for an explicit approval, a numerical profile.  It intentionally
does not edit an FDF, a workflow lock, or a running campaign.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    NUMERICAL_PROFILE,
    SCIENTIFIC_APPROVAL,
    ApprovalDecision,
    ContractEnvelope,
    NumericalProfileReference,
    ScientificApproval,
    ScientificAuthority,
    canonical_primitive,
    contract_sha256,
)
from .contracts.workflow import require_local_id


_READY_STATUS = "READY_FOR_HUMAN_REVIEW"
_APPROVAL_FIELDS = {"schema_version", "candidate", "approval"}
_PROFILE_FIELDS = {
    "schema_version", "profile_id", "authority", "parameter", "selection",
    "candidate_sha256", "evidence_sha256", "approval_id", "approval_sha256",
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64:
        raise ValueError(f"{field} must contain 64 hexadecimal characters")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must contain 64 hexadecimal characters") from exc
    return normalized


def _load_json(path: Path, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load {field}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON mapping")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    destination = path.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite immutable scientific contract: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    encoded = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _candidate_from_report(report: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "rule_id", "rule_sha256", "status"}
    if not required <= set(report) or report.get("schema_version") != "1.0":
        raise ValueError("convergence report schema is incomplete")
    if report.get("status") != _READY_STATUS:
        raise ValueError("only READY_FOR_HUMAN_REVIEW evidence may be decided")
    rule_id = require_local_id(str(report["rule_id"]), field_name="convergence rule id")
    rule_sha256 = _require_sha256(report["rule_sha256"], field="convergence report rule_sha256")
    cutoff = report.get("selected_cutoff_ry")
    grid = report.get("selected_grid")
    if isinstance(cutoff, str) and grid is None:
        try:
            if Decimal(cutoff.replace("D", "E").replace("d", "e")) <= 0:
                raise ValueError
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("convergence report selected_cutoff_ry is invalid") from exc
        selection: dict[str, Any] = {"value": cutoff, "unit": "Ry"}
        parameter = "Mesh.Cutoff"
    elif cutoff is None and isinstance(grid, Mapping):
        dimensions = grid.get("dimensions")
        shifts = grid.get("shifts")
        if (
            not isinstance(dimensions, (list, tuple)) or len(dimensions) != 3
            or any(type(item) is not int or item <= 0 for item in dimensions)
            or not isinstance(shifts, (list, tuple)) or len(shifts) != 3
            or any(not isinstance(item, str) for item in shifts)
        ):
            raise ValueError("convergence report selected_grid is invalid")
        selection = {"dimensions": list(dimensions), "shifts": list(shifts)}
        parameter = "kgrid.MonkhorstPack"
    else:
        raise ValueError("convergence report must select exactly one supported numerical parameter")
    candidate = {
        "schema_version": "1.0", "rule_id": rule_id, "rule_sha256": rule_sha256,
        "parameter": parameter, "selection": selection,
    }
    canonical_primitive(candidate)
    return candidate


def _approval_from_payload(value: Mapping[str, Any]) -> ScientificApproval:
    if set(value) != {"approval_id", "subject_sha256", "evidence_sha256", "decision", "actor", "decided_at"}:
        raise ValueError("scientific approval fields mismatch")
    return ScientificApproval(**dict(value))


@dataclass(frozen=True)
class ApprovedNumericalProfile:
    """A verified profile plus the exact evidence and decision it propagates."""

    reference: NumericalProfileReference
    parameter: str
    selection: Mapping[str, Any]
    candidate_sha256: str
    evidence_sha256: str


def create_decision(
    report_path: Path,
    *,
    approval_id: str,
    decision: ApprovalDecision | str,
    actor: str,
    decided_at: str,
    output: Path,
) -> dict[str, Any]:
    """Persist an immutable human decision bound to exact report bytes."""
    report = _load_json(report_path, field="convergence report")
    candidate = _candidate_from_report(report)
    candidate_sha256 = contract_sha256(candidate)
    evidence_sha256 = _sha256_file(report_path)
    approval = ScientificApproval(
        approval_id=approval_id, subject_sha256=candidate_sha256,
        evidence_sha256=evidence_sha256, decision=ApprovalDecision(decision),
        actor=actor, decided_at=decided_at,
    )
    envelope = ContractEnvelope.create(
        SCIENTIFIC_APPROVAL,
        producer="siestaflow.scientific-approvals",
        payload={"schema_version": "1.0", "candidate": candidate, "approval": canonical_primitive(approval)},
    )
    _write_new(output, envelope.to_dict())
    return {
        "status": "SCIENTIFIC_DECISION_RECORDED", "output": str(output.resolve()),
        "decision": approval.decision.value, "approval_id": approval.approval_id,
        "candidate_sha256": candidate_sha256, "evidence_sha256": evidence_sha256,
        "approval_sha256": envelope.content_sha256,
    }


def load_decision(path: Path) -> tuple[dict[str, Any], ScientificApproval, str]:
    raw = _load_json(path, field="scientific approval")
    envelope = ContractEnvelope.from_dict(raw, required_contract=SCIENTIFIC_APPROVAL)
    payload = envelope.payload
    if set(payload) != _APPROVAL_FIELDS or payload["schema_version"] != "1.0":
        raise ValueError("scientific approval payload schema mismatch")
    candidate = payload["candidate"]
    approval_raw = payload["approval"]
    if not isinstance(candidate, Mapping) or not isinstance(approval_raw, Mapping):
        raise ValueError("scientific approval payload is invalid")
    selection = candidate.get("selection") if isinstance(candidate, Mapping) else None
    if not isinstance(selection, Mapping):
        raise ValueError("scientific approval candidate selection is invalid")
    normalized_candidate = _candidate_from_report({
        "schema_version": "1.0", "rule_id": candidate.get("rule_id"),
        "rule_sha256": candidate.get("rule_sha256"), "status": _READY_STATUS,
        "selected_cutoff_ry": selection.get("value")
        if candidate.get("parameter") == "Mesh.Cutoff" else None,
        "selected_grid": selection
        if candidate.get("parameter") == "kgrid.MonkhorstPack" else None,
    })
    if canonical_primitive(candidate) != normalized_candidate:
        raise ValueError("scientific approval candidate is not canonical")
    approval = _approval_from_payload(approval_raw)
    if approval.subject_sha256 != contract_sha256(normalized_candidate):
        raise ValueError("scientific approval does not bind its exact candidate")
    return normalized_candidate, approval, envelope.content_sha256


def create_approved_profile(
    report_path: Path, approval_path: Path, *, profile_id: str, output: Path,
) -> dict[str, Any]:
    """Create a usable numerical profile only from matching explicit approval."""
    report = _load_json(report_path, field="convergence report")
    candidate = _candidate_from_report(report)
    evidence_sha256 = _sha256_file(report_path)
    approved_candidate, approval, approval_sha256 = load_decision(approval_path)
    if approval.decision is not ApprovalDecision.APPROVE:
        raise ValueError("rejected scientific decisions cannot create a numerical profile")
    if approved_candidate != candidate or approval.evidence_sha256 != evidence_sha256:
        raise ValueError("scientific approval does not match the exact convergence evidence")
    payload = {
        "schema_version": "1.0", "profile_id": require_local_id(profile_id, field_name="numerical profile id"),
        "authority": ScientificAuthority.APPROVED.value, "parameter": candidate["parameter"],
        "selection": candidate["selection"], "candidate_sha256": approval.subject_sha256,
        "evidence_sha256": evidence_sha256, "approval_id": approval.approval_id,
        "approval_sha256": approval_sha256,
    }
    envelope = ContractEnvelope.create(
        NUMERICAL_PROFILE, producer="siestaflow.scientific-approvals", payload=payload,
    )
    _write_new(output, envelope.to_dict())
    return {
        "status": "APPROVED_NUMERICAL_PROFILE_CREATED", "output": str(output.resolve()),
        "profile_id": payload["profile_id"], "profile_sha256": envelope.content_sha256,
        "approval_id": approval.approval_id, "approval_sha256": approval_sha256,
        "evidence_sha256": evidence_sha256,
    }


def load_approved_profile(path: Path) -> ApprovedNumericalProfile:
    raw = _load_json(path, field="numerical profile")
    envelope = ContractEnvelope.from_dict(raw, required_contract=NUMERICAL_PROFILE)
    payload = envelope.payload
    if set(payload) != _PROFILE_FIELDS or payload["schema_version"] != "1.0":
        raise ValueError("numerical profile payload schema mismatch")
    if payload["authority"] != ScientificAuthority.APPROVED.value:
        raise ValueError("numerical profile is not approved")
    parameter = str(payload["parameter"])
    selection = payload["selection"]
    if not isinstance(selection, Mapping):
        raise ValueError("numerical profile selection must be a mapping")
    # Validate the supported selection shape without pretending the synthetic
    # rule identity is the source of authority.
    _candidate_from_report({
        "schema_version": "1.0", "rule_id": "profile-only", "rule_sha256": "0" * 64,
        "status": _READY_STATUS,
        "selected_cutoff_ry": selection.get("value") if parameter == "Mesh.Cutoff" else None,
        "selected_grid": dict(selection) if parameter == "kgrid.MonkhorstPack" else None,
    })
    reference = NumericalProfileReference(
        profile_id=str(payload["profile_id"]), sha256=envelope.content_sha256,
        authority=ScientificAuthority.APPROVED, approval_id=str(payload["approval_id"]),
        approval_sha256=str(payload["approval_sha256"]),
    )
    return ApprovedNumericalProfile(
        reference=reference, parameter=parameter, selection=canonical_primitive(selection),
        candidate_sha256=_require_sha256(payload["candidate_sha256"], field="numerical profile candidate_sha256"),
        evidence_sha256=_require_sha256(payload["evidence_sha256"], field="numerical profile evidence_sha256"),
    )
