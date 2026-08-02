from __future__ import annotations

import ast
from pathlib import Path

from siestaflow.contract_adapters import (
    artifact_reference_from_siesta,
    execution_evidence_from_step_outcome,
    step_launch_spec_from_execution_request,
    validation_report_from_siesta,
)
from siestaflow.contracts import (
    ArtifactRole,
    DecisionStatus,
    ExecutionRequest,
    FailureType,
    LauncherKind,
    ResourceRequest,
)
from siestaflow.engines.siesta.models import (
    ArtifactDescriptor,
    InputValidationResult,
    ValidationFinding,
)
from siestaflow.execution.srun_launcher import StepOutcome


def test_existing_siesta_validation_maps_without_decision_loss() -> None:
    legacy = InputValidationResult(
        DecisionStatus.REVIEW,
        (
            ValidationFinding(
                "UNKNOWN_LABEL",
                DecisionStatus.REVIEW,
                "unknown label",
                ("line:10",),
            ),
        ),
        2,
        ("Mn", "O"),
        "system",
    )
    report = validation_report_from_siesta(
        legacy, subject_id="system", source="input.fdf"
    )
    assert report.status is DecisionStatus.REVIEW
    assert report.subject.attributes["atoms"] == 2


def test_existing_artifact_and_launcher_models_have_boundary_adapters(
    tmp_path: Path,
) -> None:
    descriptor = ArtifactDescriptor(
        "system.DM",
        "DM",
        10,
        "a" * 64,
        "parent",
        "attempt_001",
        True,
        "HASH_AND_PARENT_REQUIRED",
    )
    artifact = artifact_reference_from_siesta(descriptor)
    assert artifact.role is ArtifactRole.RESTART

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
        resources=ResourceRequest(
            2, 64, 1, 32, 3600, 256000, LauncherKind.HYDRA
        ),
    )
    launch = step_launch_spec_from_execution_request(
        request, root=tmp_path, hosts=("tt82", "tt85")
    )
    assert launch.mpi_processes == 64
    assert launch.hosts == ("tt82", "tt85")

    evidence = execution_evidence_from_step_outcome(
        StepOutcome(
            "parent",
            "attempt_001",
            ("mpiexec.hydra", "siesta"),
            0,
            1.0,
            False,
        ),
        artifacts=(artifact,),
    )
    assert evidence.failure is FailureType.SUCCESS
    assert evidence.artifacts == (artifact,)


def test_contract_kernel_has_no_engine_or_cluster_dependencies() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "siestaflow" / "contracts"
    imported: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not any(name.startswith("siestaflow.engines") for name in imported)
    assert not any(name.startswith("siestaflow.execution") for name in imported)
    assert "subprocess" not in imported
