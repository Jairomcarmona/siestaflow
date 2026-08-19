"""Generic operational gates and an extensible evidence-rule registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .models import DecisionStatus, FailureType, GateDecision, TaskResult


class GateEngine:
    def evaluate(self, result: TaskResult) -> GateDecision:
        evidence = (f"failure={result.failure.value}", f"exit_code={result.exit_code}")
        if result.failure is FailureType.SUCCESS and not result.warnings:
            return GateDecision(DecisionStatus.PASS, "simulated task completed", evidence)
        if result.failure is FailureType.UNKNOWN_WARNING or result.warnings:
            return GateDecision(DecisionStatus.REVIEW, "unknown warning requires review", evidence + result.warnings)
        if result.failure is FailureType.INTERRUPTED:
            return GateDecision(DecisionStatus.BLOCKED, "task was interrupted", evidence)
        if result.failure in {FailureType.TRUNCATED_OUTPUT, FailureType.UNKNOWN_FAILURE}:
            return GateDecision(DecisionStatus.REVIEW, "terminal evidence is ambiguous", evidence)
        return GateDecision(DecisionStatus.FAIL, f"task failed: {result.failure.value}", evidence)


class EvidenceGate(Protocol):
    name: str

    def evaluate(self, evidence: Mapping[str, Any]) -> GateDecision: ...


@dataclass(frozen=True)
class BooleanEvidenceGate:
    name: str
    evidence_key: str
    missing_status: DecisionStatus = DecisionStatus.BLOCKED

    def evaluate(self, evidence: Mapping[str, Any]) -> GateDecision:
        if self.evidence_key not in evidence:
            return GateDecision(self.missing_status, f"missing evidence: {self.evidence_key}", (self.evidence_key,))
        if bool(evidence[self.evidence_key]):
            return GateDecision(DecisionStatus.PASS, f"{self.name} passed", (self.evidence_key,))
        return GateDecision(DecisionStatus.FAIL, f"{self.name} failed", (self.evidence_key,))


class TechnicalCompletionGate(BooleanEvidenceGate):
    def __init__(self) -> None:
        super().__init__("technical_completion", "technical_completion")


class KnownWarningsGate(BooleanEvidenceGate):
    def __init__(self) -> None:
        super().__init__("known_warnings", "warnings_are_known", DecisionStatus.REVIEW)


class ArtifactPresenceGate(BooleanEvidenceGate):
    def __init__(self) -> None:
        super().__init__("artifact_presence", "required_artifacts_present")


class SCFConvergenceGate(BooleanEvidenceGate):
    def __init__(self) -> None:
        super().__init__("scf_convergence", "scf_converged", DecisionStatus.REVIEW)


class HumanReviewGate(BooleanEvidenceGate):
    def __init__(self) -> None:
        super().__init__("human_review", "human_review_approved", DecisionStatus.REVIEW)


class ParameterSeriesCompletionGate(BooleanEvidenceGate):
    def __init__(self) -> None:
        super().__init__("parameter_series_completion", "parameter_series_complete")


class GateRegistry:
    def __init__(self) -> None:
        gates: tuple[EvidenceGate, ...] = (
            TechnicalCompletionGate(), KnownWarningsGate(), ArtifactPresenceGate(),
            SCFConvergenceGate(), HumanReviewGate(), ParameterSeriesCompletionGate(),
        )
        self._gates = {gate.name: gate for gate in gates}

    def register(self, gate: EvidenceGate) -> None:
        if gate.name in self._gates:
            raise ValueError(f"gate already registered: {gate.name}")
        self._gates[gate.name] = gate

    def evaluate(self, name: str, evidence: Mapping[str, Any]) -> GateDecision:
        try:
            return self._gates[name].evaluate(evidence)
        except KeyError as exc:
            raise KeyError(f"unknown gate: {name}") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._gates))
