"""Phase 5 readiness aggregation and fail-closed reduction tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qraft.cli import main
from qraft.environment_inspection import EnvironmentReport, ProbeResult, ProbeStatus
from qraft.readiness import (
    ReadinessChecker,
    ReadinessDimension,
    ReadinessState,
    OverallReadiness,
    reduce_readiness,
)
from qraft.target_classifier import TargetClassification, TargetKind, classify_target
from tests.authoring.test_workflow_authoring import converge_then_relaxation_source
from tests.campaigns.test_campaign_spec_v1 import campaign_file
from tests.runs.test_prepared_run import _prepared


class _EnvironmentStub:
    def __init__(self, report: EnvironmentReport) -> None:
        self.report = report

    def inspect(self, **_kwargs: object) -> EnvironmentReport:
        return self.report


def _environment(*, engine: ProbeStatus = ProbeStatus.AVAILABLE) -> EnvironmentReport:
    selected = ProbeResult("launcher:selected:direct", ProbeStatus.NOT_REQUIRED)
    return EnvironmentReport(
        qraft_version="test",
        python_version="test",
        platform="test",
        installation_path="test",
        engine=ProbeResult("engine:siesta", engine),
        scheduler=ProbeResult("scheduler:local", ProbeStatus.NOT_REQUIRED),
        launchers=(selected,),
        profile=ProbeResult("profile", ProbeStatus.NOT_REQUIRED),
        filesystem=ProbeResult("filesystem", ProbeStatus.AVAILABLE),
        compatibility=ProbeResult("runtime:compatibility", ProbeStatus.UNKNOWN),
        workspace=".",
        config_paths=(),
    )


def _checker(report: EnvironmentReport | None = None) -> ReadinessChecker:
    return ReadinessChecker(environment_inspector=_EnvironmentStub(report or _environment()))


def _valid_campaign(root: Path) -> Path:
    target = campaign_file(root)
    fdf = root / "calc.fdf"
    fdf.write_text(
        fdf.read_text(encoding="utf-8")
        + "NetCharge 0\nSpin non-polarized\nMD.TypeOfRun CG\nMD.NumCGSteps 0\n",
        encoding="utf-8",
    )
    return target


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_new_campaign_is_not_numerically_overclaimed(tmp_path: Path) -> None:
    target = _valid_campaign(tmp_path)
    result = _checker().check(classify_target(target))
    assert result.dimensions[0].status is ReadinessState.PASS
    assert result.dimensions[2].status is ReadinessState.NOT_EVALUATED
    assert result.numerically_adequate is None
    assert result.scientifically_ready is None
    assert result.can_run is True
    assert result.status is OverallReadiness.READY


def test_check_is_read_only_and_never_runs_an_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _valid_campaign(tmp_path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("readiness attempted scientific execution"),
    )
    result = _checker().check(classify_target(target))
    assert result.exit_code == 0
    assert _snapshot(tmp_path) == before


def test_structural_and_required_input_failures_block(tmp_path: Path) -> None:
    target = _valid_campaign(tmp_path)
    fdf = tmp_path / "calc.fdf"
    fdf.write_text(fdf.read_text(encoding="utf-8").replace("NumberOfAtoms 1", "NumberOfAtoms 2"), encoding="utf-8")
    result = _checker().check(classify_target(target))
    assert result.status is OverallReadiness.BLOCKED
    assert result.can_run is False
    assert result.exit_code == 2

    (tmp_path / "C.psf").unlink()
    missing = _checker().check(classify_target(target))
    assert missing.dimensions[0].status is ReadinessState.BLOCKED
    assert any(
        item.code in {"SCIENTIFIC_INPUT_INCOMPLETE", "PSEUDOPOTENTIAL_MANIFEST_INVALID"}
        for item in missing.dimensions[0].findings
    )


def test_environment_incompatibility_blocks_without_execution(tmp_path: Path) -> None:
    target = _valid_campaign(tmp_path)
    result = _checker(_environment(engine=ProbeStatus.NOT_FOUND)).check(classify_target(target))
    assert result.dimensions[3].status is ReadinessState.BLOCKED
    assert result.can_run is False
    assert result.status is OverallReadiness.BLOCKED


def test_approved_numerical_profile_is_hash_bound(tmp_path: Path) -> None:
    intent, definition = converge_then_relaxation_source(tmp_path)
    from qraft.workflow_authoring import WorkflowAuthoringService

    WorkflowAuthoringService().create_definition(intent, definition)
    result = _checker().check(classify_target(definition))
    assert result.dimensions[2].status is ReadinessState.PASS
    assert result.numerically_adequate is True

    report = tmp_path / "mesh-convergence-report.json"
    report.write_text(report.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    mismatched = _checker().check(classify_target(definition))
    assert mismatched.dimensions[2].status is ReadinessState.BLOCKED
    assert mismatched.numerically_adequate is False


def test_ready_for_human_review_is_not_approval(tmp_path: Path) -> None:
    from qraft.campaign_spec import CampaignSpec
    from qraft.readiness import _campaign_numerical_dimension

    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"status": "READY_FOR_HUMAN_REVIEW"}), encoding="utf-8")
    campaign = CampaignSpec.from_mapping({
        "schema_version": "1.0", "campaign_id": "review", "engine": "siesta",
        "protocol": "convergence", "system": {"fdf": "calc.fdf"},
        "parameters": {
            "mesh_cutoff": {"mode": "scan", "values": [200, 250], "unit": "Ry"},
            "basis_size": {"mode": "inherit", "inherit": {"evidence": str(evidence), "value": "DZP"}},
        },
        "criterion": {"metric": "energy_per_atom", "delta": 0.001, "unit": "eV", "consecutive": 2},
    }, source=tmp_path / "campaign.yaml")
    dimension = _campaign_numerical_dimension(campaign, ())
    assert dimension.status is ReadinessState.REVIEW


def test_workflow_package_and_runs_root_are_conservative(tmp_path: Path) -> None:
    intent, definition = converge_then_relaxation_source(tmp_path / "workflow")
    from qraft.workflow_authoring import WorkflowAuthoringService

    WorkflowAuthoringService().create_definition(intent, definition)
    workflow = _checker().check(classify_target(definition))
    assert workflow.dimensions[3].status is ReadinessState.NOT_EVALUATED
    assert workflow.status is OverallReadiness.REVIEW_REQUIRED

    from qraft.workflows import WorkflowCompiler, write_workflow_lock

    compilation = WorkflowCompiler().compile(definition)
    assert compilation.valid
    lock = definition.parent / "workflow.lock.json"
    write_workflow_lock(compilation, lock)
    locked = _checker().check(classify_target(lock))
    assert locked.dimensions[2].status is ReadinessState.PASS
    assert locked.dimensions[3].status is ReadinessState.NOT_EVALUATED

    (tmp_path / "package").mkdir()
    _, package = _prepared(tmp_path / "package")
    packaged = _checker().check(classify_target(package))
    assert packaged.dimensions[2].status is ReadinessState.NOT_EVALUATED
    assert packaged.dimensions[3].status is ReadinessState.NOT_EVALUATED
    assert packaged.scientifically_ready is None

    runs = tmp_path / "runs"
    runs.mkdir()
    session_target = tmp_path / "session-target"
    session_target.mkdir()
    target = _valid_campaign(session_target)
    (runs / "session.json").write_text(json.dumps({
        "schema_version": "1.0", "fdf": str(target), "profile": None,
        "protocol": "convergence", "pseudo_manifest": None,
        "project_config": None, "recipe": None, "runs_root": str(runs), "overrides": {},
    }), encoding="utf-8")
    session = _checker().check(classify_target(runs))
    assert session.dimensions[2].status is ReadinessState.NOT_EVALUATED


def _dimensions(*, environment: ReadinessState = ReadinessState.PASS,
                input_model: ReadinessState = ReadinessState.PASS,
                scientific: ReadinessState = ReadinessState.PASS,
                numerical: ReadinessState = ReadinessState.NOT_EVALUATED,
                review_required: bool = False) -> tuple[ReadinessDimension, ...]:
    return (
        ReadinessDimension("input_model", "INPUT / MODEL", input_model, "test", mandatory=True),
        ReadinessDimension("scientific_consistency", "SCIENTIFIC CONSISTENCY", scientific, "test", mandatory=True),
        ReadinessDimension("numerical_evidence", "NUMERICAL EVIDENCE", numerical, "test"),
        ReadinessDimension("execution_environment", "EXECUTION ENVIRONMENT", environment, "test", mandatory=True, review_required=review_required),
    )


def test_reduction_rejects_scientific_and_numerical_overclaims() -> None:
    classification = TargetClassification(TargetKind.FDF, Path("calc.fdf"), "test")
    ready = reduce_readiness(classification, _dimensions())
    assert ready.can_run is True
    assert ready.scientifically_ready is None
    assert ready.numerically_adequate is None
    assert reduce_readiness(classification, _dimensions(environment=ReadinessState.BLOCKED)).status is OverallReadiness.BLOCKED
    assert reduce_readiness(classification, _dimensions(input_model=ReadinessState.BLOCKED)).status is OverallReadiness.BLOCKED
    assert reduce_readiness(classification, _dimensions(environment=ReadinessState.REVIEW, review_required=True)).status is OverallReadiness.REVIEW_REQUIRED
    with pytest.raises(ValueError):
        reduce_readiness(classification, _dimensions(), scientifically_ready_claim=True)


def test_cli_human_and_json_outputs_are_pure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = campaign_file(tmp_path)
    checker = _checker()
    monkeypatch.setattr("qraft.cli.ReadinessChecker", lambda: checker)
    assert main(["check", str(target)]) == 0
    human = capsys.readouterr()
    assert "INPUT / MODEL" in human.out
    assert "SCIENTIFIC CONSISTENCY" in human.out
    assert "NUMERICAL EVIDENCE" in human.out
    assert "EXECUTION ENVIRONMENT" in human.out
    assert "OVERALL READINESS" in human.out
    assert human.err == ""

    assert main(["check", str(target), "--json"]) == 0
    machine = capsys.readouterr()
    payload = json.loads(machine.out)
    assert payload["status"] == "READY"
    assert payload["scientifically_ready"] is None
    assert machine.out.lstrip().startswith("{")
    assert machine.err == ""
