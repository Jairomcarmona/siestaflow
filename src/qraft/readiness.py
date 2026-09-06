"""Read-only readiness aggregation over existing QRAFT authorities."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .application import ApplicationConfiguration, QraftApplication
from .campaign_spec import CampaignSpec, ParameterMode
from .contracts import ApprovalDecision, canonical_primitive
from .engines.siesta.fdf_parser import FDFParser
from .engines.siesta.input_validator import SiestaInputValidator
from .engines.siesta.magnetism import validate_magnetic_input
from .engines.siesta.pseudopotentials import (
    PseudopotentialManifest,
    PseudopotentialVerifier,
)
from .environment_inspection import EnvironmentInspector, ProbeStatus
from .project_packages import load_structured
from .protocols.convergence import ConvergenceProtocol
from .protocols.single_fdf import build_scientific_identity
from .run_inspection import RunInspector
from .scientific_approvals import load_approved_profile, load_decision
from .siesta_validation import SiestaContextualValidator
from .target_classifier import (
    TargetClassification,
    TargetClassificationError,
    TargetKind,
    classify_target,
)
from .workflows import WorkflowCompiler, load_workflow_lock
from .workflow_preflight import WorkflowPreflightValidator


class ReadinessState(str, Enum):
    """Frozen status vocabulary for each readiness dimension."""

    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


class OverallReadiness(str, Enum):
    """Frozen aggregate outcomes and their CLI exit-code meanings."""

    READY = "READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ReadinessFinding:
    """Concise adapter view of one existing authority finding."""

    code: str
    message: str
    authority: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "authority": self.authority,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ReadinessDimension:
    """One independent readiness claim, including its epistemic limits."""

    key: str
    name: str
    status: ReadinessState
    reason: str
    findings: tuple[ReadinessFinding, ...] = ()
    authorities: tuple[str, ...] = ()
    mandatory: bool = False
    review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "reason": self.reason,
            "findings": [item.to_dict() for item in self.findings],
            "authorities": list(self.authorities),
        }


@dataclass(frozen=True)
class ReadinessResult:
    """Reduced readiness without a combined scientific-correctness claim."""

    status: OverallReadiness
    can_run: bool | None
    model_consistent: bool | None
    numerically_adequate: bool | None
    scientifically_ready: bool | None
    dimensions: tuple[ReadinessDimension, ...]
    next_command: str
    target: str
    target_kind: str

    @property
    def exit_code(self) -> int:
        return 0 if self.status is OverallReadiness.READY else 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "can_run": self.can_run,
            "model_consistent": self.model_consistent,
            "numerically_adequate": self.numerically_adequate,
            "scientifically_ready": self.scientifically_ready,
            "dimensions": {
                item.key: item.to_dict() for item in self.dimensions
            },
            "next_command": self.next_command,
            "target": self.target,
            "target_kind": self.target_kind,
        }


@dataclass(frozen=True)
class ReadinessOptions:
    """Existing execution inputs accepted by ``qraft check``."""

    profile: str | Path | None = None
    project_config: Path | None = None
    recipe: Path | None = None
    pseudo_manifest: Path | None = None
    runs_root: Path = Path(".qraft-runs")
    overrides: Mapping[str, Any] = field(default_factory=dict)


_DIMENSION_KEYS = (
    "input_model",
    "scientific_consistency",
    "numerical_evidence",
    "execution_environment",
)
_BLOCKING = {ReadinessState.BLOCKED}
_UNKNOWN = {ReadinessState.NOT_APPLICABLE, ReadinessState.NOT_EVALUATED}


def reduce_readiness(
    classification: TargetClassification,
    dimensions: Sequence[ReadinessDimension],
    *,
    scientifically_ready_claim: bool | None = None,
) -> ReadinessResult:
    """Apply the frozen reduction and reject unsupported scientific claims."""

    by_key = {item.key: item for item in dimensions}
    if tuple(by_key) != _DIMENSION_KEYS or len(dimensions) != len(by_key):
        raise ValueError("readiness reduction requires each frozen dimension once")
    if scientifically_ready_claim is True:
        raise ValueError(
            "scientifically_ready=true requires an authority not provided by check"
        )

    input_model = by_key["input_model"]
    scientific = by_key["scientific_consistency"]
    numerical = by_key["numerical_evidence"]
    environment = by_key["execution_environment"]
    mandatory = tuple(item for item in dimensions if item.mandatory)

    blocked = any(item.status in _BLOCKING for item in mandatory)
    unresolved = any(item.status in _UNKNOWN for item in mandatory)
    required_review = any(
        item.review_required and item.status is ReadinessState.REVIEW
        for item in dimensions
    )
    if blocked:
        overall = OverallReadiness.BLOCKED
        can_run: bool | None = False
    elif unresolved or required_review:
        overall = OverallReadiness.REVIEW_REQUIRED
        can_run = None
    else:
        overall = OverallReadiness.READY
        can_run = True

    model_states = (input_model.status, scientific.status)
    if any(state is ReadinessState.BLOCKED for state in model_states):
        model_consistent: bool | None = False
    elif any(
        state in {ReadinessState.REVIEW, *_UNKNOWN} for state in model_states
    ):
        model_consistent = None
    else:
        model_consistent = True

    if numerical.status is ReadinessState.PASS:
        numerically_adequate: bool | None = True
    elif numerical.status is ReadinessState.BLOCKED:
        numerically_adequate = False
    else:
        numerically_adequate = None

    next_command = _next_command(classification, overall)
    return ReadinessResult(
        overall,
        can_run,
        model_consistent,
        numerically_adequate,
        scientifically_ready_claim,
        tuple(dimensions),
        next_command,
        str(classification.path),
        classification.kind.value,
    )


class ReadinessChecker:
    """Orchestrate existing validators without execution or persistence."""

    def __init__(
        self, *, environment_inspector: EnvironmentInspector | None = None,
    ) -> None:
        self.environment_inspector = environment_inspector or EnvironmentInspector()

    def check(
        self,
        classification: TargetClassification,
        options: ReadinessOptions | None = None,
    ) -> ReadinessResult:
        selected = options or ReadinessOptions()
        handlers = {
            TargetKind.CAMPAIGN_SPEC: self._campaign,
            TargetKind.FDF: self._fdf,
            TargetKind.WORKFLOW_DEFINITION: self._workflow_definition,
            TargetKind.WORKFLOW_LOCK: self._workflow_lock,
            TargetKind.PREPARED_RUN_PACKAGE: self._prepared_package,
            TargetKind.RUNS_ROOT: self._runs_root,
        }
        dimensions = handlers[classification.kind](classification, selected)
        return reduce_readiness(classification, dimensions)

    def _campaign(
        self, classification: TargetClassification, options: ReadinessOptions,
    ) -> tuple[ReadinessDimension, ...]:
        campaign = CampaignSpec.from_mapping(
            load_structured(classification.path), source=classification.path,
        )
        preflight = ConvergenceProtocol().preflight(campaign)
        input_findings: list[ReadinessFinding] = []
        scientific_findings: list[ReadinessFinding] = []
        scientific_codes = {
            "PARAMETER_INVALID",
            "INHERIT_EVIDENCE_MISSING",
            "INHERIT_EVIDENCE_HASH_MISMATCH",
            "INHERIT_IDENTITY_INCOMPATIBLE",
            "AUTO_SUGGEST_NOT_EXECUTED",
            "VARIANT_MATERIALIZATION_FAILED",
        }
        for raw in preflight["findings"]:
            finding = ReadinessFinding(
                str(raw["code"]),
                str(raw["message"]),
                "ConvergenceProtocol.preflight",
            )
            target = (
                scientific_findings
                if raw["code"] in scientific_codes
                else input_findings
            )
            target.append(finding)
        input_dimension = _preflight_dimension(
            "input_model",
            "INPUT / MODEL",
            input_findings,
            preflight["findings"],
            scientific_codes,
            include_codes=False,
            mandatory=True,
            pass_reason="CampaignSpec and referenced scientific inputs are readable",
        )
        scientific_dimension = _preflight_dimension(
            "scientific_consistency",
            "SCIENTIFIC CONSISTENCY",
            scientific_findings,
            preflight["findings"],
            scientific_codes,
            include_codes=True,
            mandatory=True,
            pass_reason="campaign protocol invariants and referenced evidence agree",
        )
        numerical = _campaign_numerical_dimension(campaign, preflight["findings"])
        environment = self._execution_environment(
            classification.path, "convergence", options,
        )
        return input_dimension, scientific_dimension, numerical, environment

    def _fdf(
        self, classification: TargetClassification, options: ReadinessOptions,
    ) -> tuple[ReadinessDimension, ...]:
        path = classification.path
        document = FDFParser().parse_path(path)
        pseudo_result = None
        input_adapter_findings: list[ReadinessFinding] = []
        if options.pseudo_manifest is not None:
            try:
                manifest = PseudopotentialManifest.load(options.pseudo_manifest)
                structural = SiestaInputValidator().validate(document)
                pseudo_result = PseudopotentialVerifier().verify(
                    manifest, structural.species,
                )
            except (OSError, TypeError, ValueError) as exc:
                input_adapter_findings.append(ReadinessFinding(
                    "BLOCKED:PSEUDOPOTENTIAL_MANIFEST_INVALID",
                    str(exc),
                    "PseudopotentialManifest.load",
                    (str(options.pseudo_manifest),),
                ))
        report = SiestaContextualValidator().validate(
            document,
            pseudo_result=pseudo_result,
            require_pseudos=options.pseudo_manifest is not None,
        )
        input_contract, scientific_contract = _partition_validation_findings(
            report.findings
        )
        try:
            identity = build_scientific_identity(
                path, pseudo_manifest=options.pseudo_manifest,
            )
            identity_evidence = (identity.fingerprint,)
        except (OSError, TypeError, ValueError, TargetClassificationError) as exc:
            input_adapter_findings.append(ReadinessFinding(
                "BLOCKED:SCIENTIFIC_INPUT_INCOMPLETE",
                str(exc),
                "build_scientific_identity",
                (str(path),),
            ))
            identity_evidence = ()
        input_dimension = _validation_dimension(
            "input_model",
            "INPUT / MODEL",
            (*input_contract, *input_adapter_findings),
            mandatory=True,
            pass_reason="FDF structure, closure, and required inputs are valid",
            authorities=(
                "FDFParser",
                "SiestaInputValidator",
                "SiestaContextualValidator",
                "build_scientific_identity",
            ),
            pass_evidence=identity_evidence,
        )
        magnetic_findings: list[ReadinessFinding] = list(scientific_contract)
        try:
            validate_magnetic_input(
                path, pseudo_manifest=options.pseudo_manifest,
            )
        except (OSError, TypeError, ValueError, TargetClassificationError) as exc:
            magnetic_findings.append(ReadinessFinding(
                "BLOCKED:MAGNETIC_CONTRACT_INCONSISTENT",
                str(exc),
                "validate_magnetic_input",
                (str(path),),
            ))
        scientific_dimension = _validation_dimension(
            "scientific_consistency",
            "SCIENTIFIC CONSISTENCY",
            tuple(magnetic_findings),
            mandatory=True,
            pass_reason="implemented FDF scientific contracts are internally consistent",
            authorities=("SiestaContextualValidator", "validate_magnetic_input"),
        )
        numerical = ReadinessDimension(
            "numerical_evidence",
            "NUMERICAL EVIDENCE",
            ReadinessState.NOT_APPLICABLE,
            "single FDF does not reference a numerical-convergence authority",
            authorities=("target contract",),
        )
        environment = self._execution_environment(path, "single_fdf", options)
        return input_dimension, scientific_dimension, numerical, environment

    def _workflow_definition(
        self, classification: TargetClassification, options: ReadinessOptions,
    ) -> tuple[ReadinessDimension, ...]:
        compilation = WorkflowCompiler().compile(classification.path)
        if not compilation.valid or compilation.compiled is None:
            input_dimension = _blocked_dimension(
                "input_model", "INPUT / MODEL", "WORKFLOW_INVALID",
                "workflow definition no longer compiles",
                "WorkflowCompiler.compile", mandatory=True,
            )
            compiled = None
        else:
            compiled = compilation.compiled
            input_dimension, scientific = _workflow_contract_dimensions(
                compiled, classification.path.parent, definition=classification.path,
            )
        if compiled is None:
            scientific = ReadinessDimension(
                "scientific_consistency", "SCIENTIFIC CONSISTENCY",
                ReadinessState.NOT_EVALUATED,
                "workflow consistency cannot be evaluated until compilation passes",
                authorities=("WorkflowCompiler.compile",), mandatory=True,
            )
            numerical = _not_evaluated_numerical(
                "workflow evidence cannot be inspected until compilation passes"
            )
        else:
            numerical = _workflow_numerical_dimension(
                compiled, classification.path.parent,
            )
        environment = _unbound_workflow_environment(classification.path)
        return input_dimension, scientific, numerical, environment

    def _workflow_lock(
        self, classification: TargetClassification, options: ReadinessOptions,
    ) -> tuple[ReadinessDimension, ...]:
        _, compiled = load_workflow_lock(classification.path)
        input_dimension, scientific = _workflow_contract_dimensions(
            compiled, classification.path.parent,
        )
        numerical = _workflow_numerical_dimension(
            compiled, classification.path.parent,
        )
        environment = _unbound_workflow_environment(classification.path)
        return input_dimension, scientific, numerical, environment

    def _prepared_package(
        self, classification: TargetClassification, options: ReadinessOptions,
    ) -> tuple[ReadinessDimension, ...]:
        inspection = RunInspector().inspect(classification.path)
        input_dimension = ReadinessDimension(
            "input_model", "INPUT / MODEL", ReadinessState.PASS,
            "prepared package integrity and required contracts verify",
            authorities=("RunInspector.inspect",), mandatory=True,
        )
        scientific = ReadinessDimension(
            "scientific_consistency", "SCIENTIFIC CONSISTENCY",
            ReadinessState.PASS,
            "workflow, run, profile, and controller identities agree",
            authorities=("RunInspector.inspect",), mandatory=True,
        )
        numerical = _not_evaluated_numerical(
            "package completion or integrity does not establish numerical adequacy"
        )
        historical = tuple(
            str(path) for path in (
                classification.path / "execution-compatibility.json",
                classification.path / "execution-resolution.json",
            ) if path.is_file()
        )
        environment = ReadinessDimension(
            "execution_environment", "EXECUTION ENVIRONMENT",
            ReadinessState.NOT_EVALUATED,
            "prepared package evidence is not a live target-cluster authorization",
            findings=(ReadinessFinding(
                "LIVE_ENVIRONMENT_UNCONFIRMED",
                "historical or packaged environment evidence cannot authorize a live run",
                "RunInspector.inspect",
                historical,
            ),),
            authorities=("RunInspector.inspect",), mandatory=True,
        )
        if inspection.status != "PREPARED_RUN_VERIFIED":
            input_dimension = _blocked_dimension(
                "input_model", "INPUT / MODEL", "PACKAGE_NOT_VERIFIED",
                inspection.status, "RunInspector.inspect", mandatory=True,
            )
        return input_dimension, scientific, numerical, environment

    def _runs_root(
        self, classification: TargetClassification, options: ReadinessOptions,
    ) -> tuple[ReadinessDimension, ...]:
        application = QraftApplication.from_session(classification.path)
        configured = application.configuration.fdf
        if configured is None:
            return (
                _blocked_dimension(
                    "input_model", "INPUT / MODEL", "SESSION_TARGET_MISSING",
                    "runs root session has no configured target",
                    "QraftApplication.from_session", mandatory=True,
                ),
                ReadinessDimension(
                    "scientific_consistency", "SCIENTIFIC CONSISTENCY",
                    ReadinessState.NOT_EVALUATED,
                    "session target is unavailable", mandatory=True,
                ),
                _not_evaluated_numerical("session target is unavailable"),
                ReadinessDimension(
                    "execution_environment", "EXECUTION ENVIRONMENT",
                    ReadinessState.NOT_EVALUATED,
                    "session target is unavailable", mandatory=True,
                ),
            )
        try:
            target = classify_target(configured)
        except (OSError, TypeError, ValueError, TargetClassificationError) as exc:
            return (
                _blocked_dimension(
                    "input_model", "INPUT / MODEL", "SESSION_TARGET_INVALID",
                    str(exc), "QraftApplication.from_session", mandatory=True,
                ),
                ReadinessDimension(
                    "scientific_consistency", "SCIENTIFIC CONSISTENCY",
                    ReadinessState.NOT_EVALUATED,
                    "session target cannot be classified", mandatory=True,
                ),
                _not_evaluated_numerical("session target cannot be classified"),
                ReadinessDimension(
                    "execution_environment", "EXECUTION ENVIRONMENT",
                    ReadinessState.NOT_EVALUATED,
                    "session target cannot be classified", mandatory=True,
                ),
            )
        session_options = ReadinessOptions(
            profile=options.profile or application.configuration.profile,
            project_config=(
                options.project_config or application.configuration.project_config
            ),
            recipe=options.recipe or application.configuration.recipe,
            pseudo_manifest=(
                options.pseudo_manifest or application.configuration.pseudo_manifest
            ),
            runs_root=classification.path,
            overrides={
                **application.configuration.overrides,
                **dict(options.overrides),
            },
        )
        if target.kind is TargetKind.CAMPAIGN_SPEC:
            dimensions = list(self._campaign(target, session_options))
            dimensions[2] = _runs_root_numerical_dimension(application)
            return tuple(dimensions)
        if target.kind is TargetKind.FDF:
            return self._fdf(target, session_options)
        return (
            _blocked_dimension(
                "input_model", "INPUT / MODEL", "SESSION_TARGET_UNSUPPORTED",
                f"runs root references unsupported session target {target.kind.value}",
                "QraftApplication.from_session", mandatory=True,
            ),
            ReadinessDimension(
                "scientific_consistency", "SCIENTIFIC CONSISTENCY",
                ReadinessState.NOT_EVALUATED,
                "session target type is unsupported", mandatory=True,
            ),
            _not_evaluated_numerical("session target type is unsupported"),
            ReadinessDimension(
                "execution_environment", "EXECUTION ENVIRONMENT",
                ReadinessState.NOT_EVALUATED,
                "session target type is unsupported", mandatory=True,
            ),
        )

    def _execution_environment(
        self, target: Path, protocol: str, options: ReadinessOptions,
    ) -> ReadinessDimension:
        application = QraftApplication(
            ApplicationConfiguration(
                fdf=target,
                profile=options.profile,
                protocol=protocol,
                pseudo_manifest=options.pseudo_manifest,
                project_config=options.project_config,
                recipe=options.recipe,
                runs_root=options.runs_root,
            ),
            environment_inspector=self.environment_inspector,
        )
        try:
            report = application.environment(
                command_overrides=dict(options.overrides),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return _blocked_dimension(
                "execution_environment", "EXECUTION ENVIRONMENT",
                "EXECUTION_RESOLUTION_INVALID", str(exc),
                "QraftApplication.environment", mandatory=True,
            )
        acceptable = {ProbeStatus.AVAILABLE, ProbeStatus.NOT_REQUIRED}
        selected = next(
            (
                item for item in report.launchers
                if item.name.startswith("launcher:selected:")
            ),
            None,
        )
        probes = tuple(
            item for item in (
                report.engine, selected, report.scheduler,
                report.profile, report.filesystem,
            ) if item is not None
        )
        findings = tuple(
            ReadinessFinding(
                "EXECUTION_PROBE_BLOCKED",
                f"{probe.name}: {probe.detail or probe.status.value}",
                "EnvironmentInspector.inspect",
                tuple(filter(None, (probe.executable,))),
            )
            for probe in probes if probe.status not in acceptable
        )
        if report.compatibility.status is ProbeStatus.INCOMPATIBLE:
            findings += (ReadinessFinding(
                "RUNTIME_INCOMPATIBLE",
                report.compatibility.detail or "runtime evidence is incompatible",
                "evaluate_runtime_compatibility",
            ),)
        status = ReadinessState.PASS if report.ready else ReadinessState.BLOCKED
        return ReadinessDimension(
            "execution_environment", "EXECUTION ENVIRONMENT", status,
            (
                "live execution resolution and required probes pass"
                if status is ReadinessState.PASS
                else "one or more mandatory execution probes failed"
            ),
            findings=findings,
            authorities=(
                "QraftApplication.environment",
                "EnvironmentInspector.inspect",
                "evaluate_runtime_compatibility",
            ),
            mandatory=True,
        )


def render_readiness(result: ReadinessResult) -> str:
    """Render the frozen human check order without internal representations."""

    lines = [f"QRAFT CHECK — {Path(result.target).name}", ""]
    for dimension in result.dimensions:
        label = dimension.status.value.replace("_", " ")
        suffix = ""
        if dimension.status in {
            ReadinessState.REVIEW,
            ReadinessState.BLOCKED,
            ReadinessState.NOT_EVALUATED,
        }:
            suffix = f" — {dimension.reason}"
        lines.append(f"{dimension.name:<27}{label}{suffix}")
        if dimension.status is not ReadinessState.PASS:
            for finding in dimension.findings:
                lines.append(f"  {finding.code}: {finding.message}")
    lines.extend((
        "",
        f"{'OVERALL READINESS':<27}{result.status.value.replace('_', ' ')}",
        f"{'CAN RUN':<27}{_claim(result.can_run)}",
        f"{'MODEL CONSISTENT':<27}{_claim(result.model_consistent)}",
        f"{'NUMERICALLY ADEQUATE':<27}{_claim(result.numerically_adequate)}",
        f"{'SCIENTIFICALLY READY':<27}{_scientific_claim(result.scientifically_ready)}",
        "",
        f"Next: {result.next_command}",
    ))
    return "\n".join(lines)


def _claim(value: bool | None) -> str:
    return "YES" if value is True else "NO" if value is False else "NOT EVALUATED"


def _scientific_claim(value: bool | None) -> str:
    return "YES" if value is True else "NO" if value is False else "NOT CLAIMED"


def _next_command(
    classification: TargetClassification, status: OverallReadiness,
) -> str:
    path = str(classification.path)
    if status is not OverallReadiness.READY:
        return shlex.join(("qraft", "check", path))
    if classification.kind in {TargetKind.CAMPAIGN_SPEC, TargetKind.FDF}:
        return shlex.join(("qraft", "run", path))
    if classification.kind is TargetKind.RUNS_ROOT:
        return shlex.join(("qraft", "status", "--runs-root", path))
    if classification.kind is TargetKind.PREPARED_RUN_PACKAGE:
        return shlex.join(("qraft", "advanced", "execution", "status", path))
    return shlex.join(("qraft", "advanced", "execution", "prepare", path))


def _state_from_findings(
    findings: Sequence[ReadinessFinding],
) -> ReadinessState:
    if any(
        item.code.startswith(("FAIL:", "BLOCKED:")) for item in findings
    ):
        return ReadinessState.BLOCKED
    if findings:
        return ReadinessState.REVIEW
    return ReadinessState.PASS


def _validation_dimension(
    key: str,
    name: str,
    findings: Sequence[ReadinessFinding],
    *,
    mandatory: bool,
    pass_reason: str,
    authorities: tuple[str, ...],
    pass_evidence: tuple[str, ...] = (),
) -> ReadinessDimension:
    state = _state_from_findings(findings)
    if pass_evidence and state is ReadinessState.PASS:
        findings = (ReadinessFinding(
            "AUTHORITY_PASSED", pass_reason, authorities[-1], pass_evidence,
        ),)
    return ReadinessDimension(
        key,
        name,
        state,
        pass_reason if state is ReadinessState.PASS else "authority findings require attention",
        tuple(findings),
        authorities,
        mandatory=mandatory,
    )


def _partition_validation_findings(
    findings: Sequence[Any],
) -> tuple[tuple[ReadinessFinding, ...], tuple[ReadinessFinding, ...]]:
    input_findings: list[ReadinessFinding] = []
    scientific_findings: list[ReadinessFinding] = []
    for item in findings:
        adapted = ReadinessFinding(
            f"{item.status.value}:{item.code}",
            item.message,
            item.rule_id,
            tuple(item.evidence),
        )
        scope = item.scope.value
        target = (
            input_findings
            if scope in {"SYNTAX", "STRUCTURE", "PSEUDOPOTENTIAL", "PROVENANCE"}
            else scientific_findings
        )
        target.append(adapted)
    return tuple(input_findings), tuple(scientific_findings)


def _preflight_dimension(
    key: str,
    name: str,
    findings: Sequence[ReadinessFinding],
    raw_findings: Sequence[Mapping[str, Any]],
    codes: set[str],
    *,
    include_codes: bool,
    mandatory: bool,
    pass_reason: str,
) -> ReadinessDimension:
    selected = [
        item for item in raw_findings
        if (str(item["code"]) in codes) is include_codes
    ]
    if any(item["severity"] == "ERROR" for item in selected):
        state = ReadinessState.BLOCKED
    elif selected:
        state = ReadinessState.REVIEW
    else:
        state = ReadinessState.PASS
    return ReadinessDimension(
        key, name, state,
        pass_reason if state is ReadinessState.PASS else "campaign preflight reported findings",
        tuple(findings),
        ("CampaignSpec.from_mapping", "ConvergenceProtocol.preflight"),
        mandatory=mandatory,
    )


def _campaign_numerical_dimension(
    campaign: CampaignSpec, preflight_findings: Sequence[Mapping[str, Any]],
) -> ReadinessDimension:
    findings: list[ReadinessFinding] = []
    inherited = [
        parameter for parameter in campaign.parameters.values()
        if parameter.mode is ParameterMode.INHERIT and parameter.inheritance
    ]
    for parameter in inherited:
        assert parameter.inheritance is not None
        path = Path(parameter.inheritance.evidence)
        if not path.is_absolute() and campaign.source is not None:
            path = campaign.source.parent / path
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, Mapping) and raw.get("status") == "READY_FOR_HUMAN_REVIEW":
            findings.append(ReadinessFinding(
                "EVIDENCE_REQUIRES_HUMAN_REVIEW",
                "convergence evidence is ready for review but is not approved",
                "convergence evaluator output",
                (str(path.resolve()),),
            ))
    inherited_errors = tuple(
        item for item in preflight_findings
        if str(item["code"]).startswith("INHERIT_")
        and item["severity"] == "ERROR"
    )
    if inherited_errors:
        return ReadinessDimension(
            "numerical_evidence", "NUMERICAL EVIDENCE",
            ReadinessState.BLOCKED,
            "target-referenced numerical evidence is missing or incompatible",
            tuple(ReadinessFinding(
                f"BLOCKED:{item['code']}", str(item["message"]),
                "ConvergenceProtocol.preflight",
            ) for item in inherited_errors),
            ("ConvergenceProtocol.preflight",), mandatory=True,
        )
    if findings:
        return ReadinessDimension(
            "numerical_evidence", "NUMERICAL EVIDENCE",
            ReadinessState.REVIEW,
            "referenced convergence evidence lacks an approval",
            tuple(findings),
            ("convergence evaluator output",), review_required=True,
        )
    return _not_evaluated_numerical(
        "numerical convergence evidence is produced by this campaign"
    )


def _workflow_contract_dimensions(
    compiled: Any, root: Path, *, definition: Path | None = None,
) -> tuple[ReadinessDimension, ReadinessDimension]:
    findings: list[ReadinessFinding] = []
    scientific_findings: list[ReadinessFinding] = []
    for artifact in compiled.external_artifacts:
        path = root / Path(*PurePosixPath(artifact.relative_path).parts)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != artifact.sha256:
                raise ValueError("external artifact SHA-256 mismatch")
        except (OSError, ValueError) as exc:
            findings.append(ReadinessFinding(
                "BLOCKED:WORKFLOW_EXTERNAL_INPUT_INVALID",
                f"{artifact.relative_path}: {exc}",
                "CompiledWorkflow.external_artifacts",
                (str(path),),
            ))
            continue
    if definition is not None and not findings:
        try:
            report = WorkflowPreflightValidator().validate(definition)
            input_part, scientific_part = _partition_validation_findings(report.findings)
            findings.extend(input_part)
            scientific_findings.extend(scientific_part)
        except (OSError, TypeError, ValueError) as exc:
            findings.append(ReadinessFinding(
                "BLOCKED:WORKFLOW_PREFLIGHT_FAILED",
                str(exc), "WorkflowPreflightValidator.validate",
                (str(definition),),
            ))
    elif definition is None and not findings:
        for artifact in compiled.external_artifacts:
            if artifact.media_type.casefold() not in {
                "text/x-siesta-fdf", "application/x-siesta-fdf",
            }:
                continue
            path = root / Path(*PurePosixPath(artifact.relative_path).parts)
            try:
                report = SiestaContextualValidator().validate(
                    FDFParser().parse_path(path)
                )
                input_part, scientific_part = _partition_validation_findings(
                    report.findings
                )
                findings.extend(input_part)
                scientific_findings.extend(scientific_part)
            except (OSError, TypeError, ValueError) as exc:
                findings.append(ReadinessFinding(
                    "BLOCKED:WORKFLOW_INPUT_INVALID",
                    f"{artifact.relative_path}: {exc}",
                    "SiestaContextualValidator",
                    (str(path),),
                ))
    input_dimension = _validation_dimension(
        "input_model", "INPUT / MODEL", tuple(findings), mandatory=True,
        pass_reason="workflow graph, external inputs, and hashes are valid",
        authorities=(
            "CompiledWorkflow",
            "CompiledWorkflow.external_artifacts",
            "WorkflowPreflightValidator",
        ),
    )
    scientific = _validation_dimension(
        "scientific_consistency", "SCIENTIFIC CONSISTENCY",
        tuple(scientific_findings), mandatory=True,
        pass_reason="workflow graph and implemented handoff contracts are consistent",
        authorities=("CompiledWorkflow", "WorkflowPreflightValidator", "SiestaContextualValidator"),
    )
    return input_dimension, scientific


def _workflow_numerical_dimension(compiled: Any, root: Path) -> ReadinessDimension:
    records: list[tuple[Any, int, Mapping[str, Any]]] = []
    produces_evidence = False
    for task in compiled.tasks:
        produces_evidence = produces_evidence or "evidence-evaluator" in task.capability_id
        raw_profiles = task.settings.get("numerical_profiles") if task.settings else None
        if isinstance(raw_profiles, list):
            records.extend((task, index, raw) for index, raw in enumerate(raw_profiles, 1))
    if not records:
        if produces_evidence:
            return _not_evaluated_numerical(
                "numerical evidence is produced by this workflow"
            )
        return ReadinessDimension(
            "numerical_evidence", "NUMERICAL EVIDENCE",
            ReadinessState.NOT_APPLICABLE,
            "workflow does not reference an approved numerical profile",
            authorities=("CompiledWorkflow",),
        )
    errors: list[ReadinessFinding] = []
    evidence_refs: list[str] = []
    artifacts = {item.artifact_id: item for item in compiled.external_artifacts}
    expected_fields = {
        "profile_id", "profile_sha256", "parameter", "selection",
        "candidate_sha256", "evidence_sha256", "approval_id", "approval_sha256",
    }
    for task, index, raw in records:
        try:
            if not isinstance(raw, Mapping) or set(raw) != expected_fields:
                raise ValueError("approved numerical profile record fields mismatch")
            paths: dict[str, Path] = {}
            for kind in ("profile", "approval", "evidence"):
                binding = next(
                    item for item in task.inputs
                    if item.name == f"numerical_{index:03d}_{kind}"
                )
                artifact = artifacts[str(binding.external_artifact_id)]
                path = root / Path(*PurePosixPath(artifact.relative_path).parts)
                if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
                    raise ValueError(f"{kind} artifact hash mismatch")
                paths[kind] = path
            profile = load_approved_profile(paths["profile"])
            candidate, approval, approval_sha256 = load_decision(paths["approval"])
            evidence_sha256 = hashlib.sha256(paths["evidence"].read_bytes()).hexdigest()
            if (
                approval.decision is not ApprovalDecision.APPROVE
                or approval_sha256 != profile.reference.approval_sha256
                or approval.approval_id != profile.reference.approval_id
                or approval.subject_sha256 != profile.candidate_sha256
                or approval.evidence_sha256 != profile.evidence_sha256
                or evidence_sha256 != profile.evidence_sha256
                or candidate["parameter"] != profile.parameter
                or canonical_primitive(candidate["selection"])
                != canonical_primitive(profile.selection)
                or raw["profile_id"] != profile.reference.profile_id
                or raw["profile_sha256"] != profile.reference.sha256
                or raw["parameter"] != profile.parameter
                or canonical_primitive(raw["selection"])
                != canonical_primitive(profile.selection)
                or raw["candidate_sha256"] != profile.candidate_sha256
                or raw["evidence_sha256"] != profile.evidence_sha256
                or raw["approval_id"] != profile.reference.approval_id
                or raw["approval_sha256"] != profile.reference.approval_sha256
            ):
                raise ValueError(
                    "numerical profile, approval, evidence, and workflow scope disagree"
                )
            evidence_refs.extend(str(paths[kind]) for kind in ("profile", "approval", "evidence"))
        except (KeyError, OSError, StopIteration, TypeError, ValueError) as exc:
            errors.append(ReadinessFinding(
                "BLOCKED:APPROVED_NUMERICAL_EVIDENCE_INVALID",
                f"{task.task_id}: {exc}",
                "approved numerical profile contracts",
            ))
    if errors:
        return ReadinessDimension(
            "numerical_evidence", "NUMERICAL EVIDENCE",
            ReadinessState.BLOCKED,
            "target-declared approved evidence is unresolved or mismatched",
            tuple(errors),
            ("load_approved_profile", "load_decision", "CompiledWorkflow"),
            mandatory=True,
        )
    return ReadinessDimension(
        "numerical_evidence", "NUMERICAL EVIDENCE", ReadinessState.PASS,
        "hash-bound approved numerical profiles match their exact evidence scope",
        (ReadinessFinding(
            "APPROVED_NUMERICAL_EVIDENCE_VALID",
            "explicit approval and numerical profile are hash-bound",
            "load_approved_profile/load_decision",
            tuple(evidence_refs),
        ),),
        ("load_approved_profile", "load_decision", "CompiledWorkflow"),
    )


def _runs_root_numerical_dimension(application: QraftApplication) -> ReadinessDimension:
    try:
        campaign = application.status().get("campaign")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessDimension(
            "numerical_evidence", "NUMERICAL EVIDENCE",
            ReadinessState.BLOCKED,
            "persisted campaign evidence is unreadable",
            (ReadinessFinding(
                "BLOCKED:CAMPAIGN_EVIDENCE_INVALID", str(exc),
                "QraftApplication.status",
            ),),
            ("QraftApplication.status",), mandatory=True,
        )
    if not isinstance(campaign, Mapping):
        return _not_evaluated_numerical(
            "runs root contains no completed convergence result"
        )
    decision = str(campaign.get("scientific_decision", "NOT_EVALUATED"))
    evidence = (str(application.configuration.runs_root / "campaign-result.json"),)
    if decision == "CONVERGED":
        return ReadinessDimension(
            "numerical_evidence", "NUMERICAL EVIDENCE", ReadinessState.PASS,
            "existing convergence evaluator found a satisfying candidate",
            (ReadinessFinding(
                "CONVERGENCE_EVIDENCE_PASS", decision,
                "evaluate_convergence", evidence,
            ),),
            ("QraftApplication.status", "evaluate_convergence"),
        )
    if decision in {"SCIENTIFIC_NOT_CONVERGED", "NOT_CONVERGED"}:
        return ReadinessDimension(
            "numerical_evidence", "NUMERICAL EVIDENCE",
            ReadinessState.BLOCKED,
            "existing convergence evaluator found no satisfying candidate",
            (ReadinessFinding(
                "BLOCKED:CONVERGENCE_NOT_SATISFIED", decision,
                "evaluate_convergence", evidence,
            ),),
            ("QraftApplication.status", "evaluate_convergence"), mandatory=True,
        )
    return _not_evaluated_numerical(
        f"persisted numerical decision is {decision}"
    )


def _not_evaluated_numerical(reason: str) -> ReadinessDimension:
    return ReadinessDimension(
        "numerical_evidence", "NUMERICAL EVIDENCE",
        ReadinessState.NOT_EVALUATED, reason,
        authorities=("target-referenced numerical evidence",),
    )


def _unbound_workflow_environment(path: Path) -> ReadinessDimension:
    return ReadinessDimension(
        "execution_environment", "EXECUTION ENVIRONMENT",
        ReadinessState.NOT_EVALUATED,
        "workflow has no prepared package bound to a live execution environment",
        (ReadinessFinding(
            "LIVE_ENVIRONMENT_UNBOUND",
            "compile-time resources and historical evidence are not live authorization",
            "CompiledWorkflow",
            (str(path),),
        ),),
        ("CompiledWorkflow",), mandatory=True,
    )


def _blocked_dimension(
    key: str,
    name: str,
    code: str,
    message: str,
    authority: str,
    *,
    mandatory: bool,
) -> ReadinessDimension:
    return ReadinessDimension(
        key, name, ReadinessState.BLOCKED, message,
        (ReadinessFinding(f"BLOCKED:{code}", message, authority),),
        (authority,), mandatory=mandatory,
    )
