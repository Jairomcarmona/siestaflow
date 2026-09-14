"""Read-only, fail-closed classification of existing QRAFT target types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from .application import QraftApplication
from .campaign_spec import CampaignSpec
from .engines.siesta.fdf_parser import FDFParser
from .engines.siesta.models import FDFBlock, FDFScalar, normalize_label
from .errors import QraftError
from .project_packages import load_structured
from .run_inspection import RunInspector
from .workflows import WorkflowCompiler, load_workflow_lock


class TargetKind(str, Enum):
    """Content kinds backed by current QRAFT validators or markers."""

    CAMPAIGN_SPEC = "CAMPAIGN_SPEC"
    FDF = "FDF"
    WORKFLOW_DEFINITION = "WORKFLOW_DEFINITION"
    WORKFLOW_LOCK = "WORKFLOW_LOCK"
    PREPARED_RUN_PACKAGE = "PREPARED_RUN_PACKAGE"
    RUNS_ROOT = "RUNS_ROOT"


ACCEPTED_TARGET_TYPES = tuple(kind.value for kind in TargetKind)


@dataclass(frozen=True)
class TargetClassification:
    """One deterministic interpretation supported by an existing authority."""

    kind: TargetKind
    path: Path
    authority: str
    reference: str | None = None


class TargetClassificationError(QraftError):
    """Expected user-correctable failure from target classification."""

    def __init__(
        self, code: str, message: str, *, why: str, fix: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.why = why
        self.fix = fix
        self.expected = "one of: " + ", ".join(ACCEPTED_TARGET_TYPES)


def classify_target(path: Path | str) -> TargetClassification:
    """Classify one path without writes, execution, scheduler, or network access."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise TargetClassificationError(
            "TARGET_NOT_FOUND",
            f"target does not exist: {resolved}",
            why="QRAFT can classify only an existing file or directory",
            fix="create the target or provide its correct path",
        )
    candidates = (
        _classify_file(resolved) if resolved.is_file()
        else _classify_directory(resolved) if resolved.is_dir()
        else ()
    )
    if not candidates:
        accepted = ", ".join(ACCEPTED_TARGET_TYPES)
        raise TargetClassificationError(
            "TARGET_NOT_CLASSIFIABLE",
            (
                f"target has no supported QRAFT interpretation: {resolved}; "
                f"accepted target types: {accepted}"
            ),
            why="no current validator or authoritative marker accepted the target",
            fix="provide a valid CampaignSpec, FDF, workflow, prepared package, or runs root",
        )
    if len(candidates) > 1:
        kinds = ", ".join(candidate.kind.value for candidate in candidates)
        raise TargetClassificationError(
            "TARGET_AMBIGUOUS",
            f"target has multiple supported interpretations: {kinds}",
            why="QRAFT will not guess which target contract should apply",
            fix="provide a target containing exactly one authoritative QRAFT contract",
        )
    return candidates[0]


def _classify_file(path: Path) -> tuple[TargetClassification, ...]:
    candidates: list[TargetClassification] = []
    structured = _structured_mapping(path)
    if structured is not None:
        _append_candidate(candidates, lambda: _campaign(path, structured))
        _append_candidate(candidates, lambda: _workflow_definition(path))
        _append_candidate(candidates, lambda: _workflow_lock(path))
    _append_candidate(candidates, lambda: _fdf(path))
    return tuple(candidates)


def _classify_directory(path: Path) -> tuple[TargetClassification, ...]:
    candidates: list[TargetClassification] = []
    if (path / "manifest.json").is_file():
        _append_candidate(candidates, lambda: _prepared_package(path))
    if (path / "session.json").is_file():
        _append_candidate(candidates, lambda: _runs_root(path))
    return tuple(candidates)


def _append_candidate(
    candidates: list[TargetClassification],
    probe: Callable[[], TargetClassification],
) -> None:
    try:
        candidates.append(probe())
    except PermissionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, QraftError):
        return


def _structured_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        return load_structured(path)
    except PermissionError:
        raise
    except (OSError, ValueError, TypeError):
        return None


def _campaign(
    path: Path, structured: Mapping[str, Any],
) -> TargetClassification:
    campaign = CampaignSpec.from_mapping(structured, source=path)
    return TargetClassification(
        TargetKind.CAMPAIGN_SPEC,
        path,
        "CampaignSpec.from_mapping",
        campaign.campaign_id,
    )


def _workflow_definition(path: Path) -> TargetClassification:
    compilation = WorkflowCompiler().compile(path)
    if not compilation.valid or compilation.compiled is None:
        raise ValueError("workflow definition did not compile")
    return TargetClassification(
        TargetKind.WORKFLOW_DEFINITION,
        path,
        "WorkflowCompiler.compile",
        compilation.compiled.workflow_id,
    )


def _workflow_lock(path: Path) -> TargetClassification:
    _, workflow = load_workflow_lock(path)
    return TargetClassification(
        TargetKind.WORKFLOW_LOCK,
        path,
        "load_workflow_lock",
        workflow.workflow_id,
    )


def _fdf(path: Path) -> TargetClassification:
    document = FDFParser().parse_path(path)
    if any(item.severity == "ERROR" for item in document.diagnostics):
        raise ValueError("FDF parser reported structural errors")
    labels = {
        normalize_label(node.label)
        for node in document.nodes
        if isinstance(node, FDFScalar)
    } | {
        normalize_label(node.name)
        for node in document.nodes
        if isinstance(node, FDFBlock)
    }
    required = {
        normalize_label("NumberOfAtoms"),
        normalize_label("NumberOfSpecies"),
        normalize_label("ChemicalSpeciesLabel"),
        normalize_label("LatticeVectors"),
        normalize_label("AtomicCoordinatesAndAtomicSpecies"),
    }
    if not required.issubset(labels):
        raise ValueError("file lacks required structural FDF markers")
    return TargetClassification(
        TargetKind.FDF,
        path,
        "FDFParser structural markers",
        document.original_sha256,
    )


def _prepared_package(path: Path) -> TargetClassification:
    inspection = RunInspector().inspect(path)
    return TargetClassification(
        TargetKind.PREPARED_RUN_PACKAGE,
        path,
        "RunInspector.inspect",
        inspection.run_id,
    )


def _runs_root(path: Path) -> TargetClassification:
    application = QraftApplication.from_session(path)
    return TargetClassification(
        TargetKind.RUNS_ROOT,
        path,
        "QraftApplication.from_session",
        str(application.configuration.fdf) if application.configuration.fdf else None,
    )
