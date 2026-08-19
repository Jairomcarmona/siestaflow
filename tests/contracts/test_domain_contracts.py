from __future__ import annotations

import pytest

from qraft.contracts import (
    ArtifactReference,
    ArtifactRole,
    DecisionStatus,
    EvidenceClass,
    ExecutionRequest,
    FindingScope,
    LauncherKind,
    ResourceRequest,
    ValidationFinding,
    ValidationReport,
    ValidationSubject,
    WorkflowEvent,
    contract_sha256,
)


DIGEST = "a" * 64


def test_artifact_paths_hashes_and_producer_identity_are_strict() -> None:
    artifact = ArtifactReference(
        artifact_id="task:attempt:aaaa",
        role=ArtifactRole.RESTART,
        relative_path="results/system.DM",
        sha256=DIGEST,
        size_bytes=10,
        media_type="application/x-siesta-dm",
        producer_task_id="task",
        producer_attempt_id="attempt",
    )
    assert artifact.relative_path == "results/system.DM"
    with pytest.raises(ValueError):
        ArtifactReference(
            "bad",
            ArtifactRole.INPUT,
            "../secret",
            DIGEST,
            1,
            "text/plain",
        )
    with pytest.raises(ValueError):
        ArtifactReference(
            "bad",
            ArtifactRole.INPUT,
            "input.fdf",
            DIGEST,
            1,
            "text/plain",
            producer_task_id="task",
        )


def test_resource_request_requires_exact_node_placement() -> None:
    resources = ResourceRequest(
        nodes=2,
        mpi_processes=64,
        cpus_per_process=1,
        processes_per_node=32,
        walltime_seconds=3600,
        memory_per_node_mb=256000,
        launcher=LauncherKind.HYDRA,
    )
    assert resources.allocated_cpus == 64
    with pytest.raises(ValueError):
        ResourceRequest(2, 63, 1, 32, 3600, None, LauncherKind.HYDRA)


def test_execution_request_is_relative_and_acyclic_at_task_level() -> None:
    resources = ResourceRequest(1, 20, 1, 20, 300, None, LauncherKind.HYDRA)
    request = ExecutionRequest(
        task_id="parent",
        attempt_id="attempt_001",
        engine="siesta",
        executable="siesta",
        arguments=(),
        working_directory="work/parent",
        input_path="input/parent.fdf",
        stdout_path="work/parent/siesta.out",
        stderr_path="work/parent/siesta.err",
        resources=resources,
    )
    assert request.resources.allocated_cpus == 20
    with pytest.raises(ValueError):
        ExecutionRequest(
            task_id="parent",
            attempt_id="attempt_001",
            engine="siesta",
            executable="siesta",
            arguments=(),
            working_directory="work",
            input_path="/absolute/input.fdf",
            stdout_path="out",
            stderr_path="err",
            resources=resources,
        )


def test_validation_report_status_is_derived_not_declared_arbitrarily() -> None:
    subject = ValidationSubject("system", "siesta.fdf")
    finding = ValidationFinding(
        rule_id="siestaflow.siesta.unknown-keyword",
        code="UNKNOWN_KEYWORD",
        status=DecisionStatus.BLOCKED,
        message="keyword is not in the selected engine registry",
        evidence_class=EvidenceClass.ENGINE_MANUAL,
        scope=FindingScope.SYNTAX,
        subject_id="system",
    )
    report = ValidationReport.build(
        report_id="report",
        subject=subject,
        findings=(finding,),
        ruleset_sha256=contract_sha256({"rules": ["unknown-keyword@1.0"]}),
        produced_by="tests",
    )
    assert report.status is DecisionStatus.BLOCKED
    with pytest.raises(ValueError):
        ValidationReport(
            "report",
            subject,
            (finding,),
            DecisionStatus.PASS,
            report.ruleset_sha256,
            "tests",
        )


def test_workflow_event_extensions_are_namespaced() -> None:
    with pytest.raises(ValueError):
        WorkflowEvent(
            event_id="event-1",
            event_type="siestaflow.task.started",
            source="controller",
            subject_id="task",
            sequence=1,
            timestamp="2026-07-30T00:00:00+00:00",
            payload={},
            extensions={"custom": True},
        )
