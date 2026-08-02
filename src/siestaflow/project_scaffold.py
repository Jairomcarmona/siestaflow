"""Create a valid preparation-only project package from researcher inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .contract_adapters import validation_report_from_siesta
from .contracts import DECISION_RANK, DecisionStatus, ValidationReport
from .engines.siesta.fdf_parser import FDFParser
from .engines.siesta.input_validator import SiestaInputValidator
from .engines.siesta.pseudopotentials import PseudopotentialManifest
from .errors import AlreadyExistsError
from .filesystem import DryRunFileSystem, FileSystem, RealFileSystem, validate_identifier
from .project_packages import ProjectPackageLoader


_DIRECTORIES = (
    "systems",
    "structures",
    "pseudopotentials",
    "campaigns",
    "policies",
    "authorizations",
    "expected_contracts",
    "inputs",
    "cluster_profiles",
    "resources",
)


@dataclass(frozen=True)
class ProjectInitRequest:
    root: Path
    project_id: str
    title: str
    system_id: str
    fdf: Path
    structure: Path
    pseudopotential_manifest: Path
    dry_run: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.project_id, field_name="project_id")
        validate_identifier(self.system_id, field_name="system_id")
        if not self.title.strip():
            raise ValueError("project title must be non-empty")


@dataclass(frozen=True)
class ProjectInitFinding:
    code: str
    status: DecisionStatus
    message: str
    hint: str | None = None


@dataclass(frozen=True)
class ProjectInitResult:
    status: str
    decision: DecisionStatus
    root: str
    project_id: str
    system_id: str
    dry_run: bool
    changed: bool
    planned_files: tuple[str, ...]
    findings: tuple[ProjectInitFinding, ...]
    input_validation: ValidationReport
    request_sha256: str
    execution_authorized: bool = False


class ProjectScaffolder:
    """Materialize a preparation-only package without scientific defaults."""

    def __init__(
        self,
        filesystem: FileSystem | None = None,
        *,
        loader: ProjectPackageLoader | None = None,
    ) -> None:
        self.fs = filesystem or RealFileSystem()
        self.loader = loader or ProjectPackageLoader()

    def initialize(self, request: ProjectInitRequest) -> ProjectInitResult:
        sources = {
            "fdf": _required_file(request.fdf, "FDF"),
            "structure": _required_file(request.structure, "structure"),
            "pseudopotential_manifest": _required_file(
                request.pseudopotential_manifest,
                "pseudopotential manifest",
            ),
        }
        document = FDFParser().parse_path(sources["fdf"])
        legacy = SiestaInputValidator().validate(document)
        input_report = validation_report_from_siesta(
            legacy,
            subject_id=request.system_id,
            source=str(sources["fdf"]),
            producer="siestaflow.project-init",
        )
        manifest = PseudopotentialManifest.load(
            sources["pseudopotential_manifest"]
        )
        findings = list(
            _preparation_findings(
                input_report,
                tuple(item.species for item in manifest.entries),
                legacy.species,
            )
        )
        decision = max(
            (input_report.status, *(item.status for item in findings)),
            key=DECISION_RANK.get,
        )
        signature = _request_signature(request, sources)
        root = request.root.resolve()
        relative_files = _relative_files(
            request,
            structure_suffix=sources["structure"].suffix,
        )

        if root.exists():
            return self._existing_result(
                request,
                root,
                signature,
                relative_files,
                findings,
                input_report,
                decision,
            )
        if decision in {DecisionStatus.FAIL, DecisionStatus.BLOCKED}:
            return ProjectInitResult(
                "PROJECT_INIT_BLOCKED",
                decision,
                str(root),
                request.project_id,
                request.system_id,
                request.dry_run,
                False,
                relative_files,
                tuple(findings),
                input_report,
                signature,
            )
        if request.dry_run:
            dry_fs = self.fs
            if not isinstance(dry_fs, DryRunFileSystem):
                dry_fs = DryRunFileSystem()
            self._materialize(
                request,
                root,
                sources,
                relative_files,
                signature,
                dry_fs,
            )
            return ProjectInitResult(
                "PROJECT_INIT_PREVIEW",
                decision,
                str(root),
                request.project_id,
                request.system_id,
                True,
                False,
                relative_files,
                tuple(findings),
                input_report,
                signature,
            )

        self._materialize(
            request,
            root,
            sources,
            relative_files,
            signature,
            self.fs,
        )
        validation = self.loader.validate(root)
        if not validation.valid:
            raise RuntimeError(
                "generated project package failed validation: "
                + "; ".join(validation.findings)
            )
        return ProjectInitResult(
            (
                "PROJECT_INITIALIZED"
                if decision is DecisionStatus.PASS
                else "PROJECT_INITIALIZED_WITH_REVIEW"
            ),
            decision,
            str(root),
            request.project_id,
            request.system_id,
            False,
            True,
            relative_files,
            tuple(findings),
            input_report,
            signature,
        )

    def _existing_result(
        self,
        request: ProjectInitRequest,
        root: Path,
        signature: str,
        relative_files: tuple[str, ...],
        findings: list[ProjectInitFinding],
        input_report: ValidationReport,
        decision: DecisionStatus,
    ) -> ProjectInitResult:
        lock = root / "project_init.lock.json"
        try:
            lock_data = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            lock_data = {}
        validation = self.loader.validate(root)
        if (
            lock_data.get("request_sha256") != signature
            or lock_data.get("project_id") != request.project_id
            or not validation.valid
        ):
            raise AlreadyExistsError(
                f"refusing to modify existing non-matching project: {root}"
            )
        return ProjectInitResult(
            "PROJECT_ALREADY_INITIALIZED",
            decision,
            str(root),
            request.project_id,
            request.system_id,
            request.dry_run,
            False,
            relative_files,
            tuple(findings),
            input_report,
            signature,
        )

    @staticmethod
    def _materialize(
        request: ProjectInitRequest,
        root: Path,
        sources: dict[str, Path],
        relative_files: tuple[str, ...],
        signature: str,
        fs: FileSystem,
    ) -> None:
        fs.mkdir(root, parents=True, exist_ok=False)
        for directory in _DIRECTORIES:
            fs.mkdir(root / directory, parents=False, exist_ok=False)

        structure_name = next(
            item for item in relative_files if item.startswith("structures/")
        )
        fdf_name = f"systems/{request.system_id}.fdf"
        fs.copy(sources["structure"], root / structure_name)
        fs.copy(sources["fdf"], root / fdf_name)
        fs.copy(
            sources["pseudopotential_manifest"],
            root / "pseudopotentials/manifest.yaml",
        )

        generated = _generated_documents(
            request,
            structure_name=structure_name,
            fdf_name=fdf_name,
            signature=signature,
            source_hashes={
                name: _sha256(path)
                for name, path in sources.items()
            },
        )
        for relative, content in generated.items():
            fs.write_text(root / relative, content)


def _required_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} file does not exist: {resolved}")
    return resolved


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_signature(
    request: ProjectInitRequest,
    sources: dict[str, Path],
) -> str:
    payload = {
        "schema_version": "1.0",
        "project_id": request.project_id,
        "title": request.title,
        "system_id": request.system_id,
        "sources": {
            name: _sha256(path)
            for name, path in sorted(sources.items())
        },
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _preparation_findings(
    input_report: ValidationReport,
    declared_pseudos: tuple[str, ...],
    species: tuple[str, ...],
) -> tuple[ProjectInitFinding, ...]:
    declared = {item.casefold() for item in declared_pseudos}
    missing = tuple(item for item in species if item.casefold() not in declared)
    findings: list[ProjectInitFinding] = []
    if missing:
        findings.append(
            ProjectInitFinding(
                "PSEUDOPOTENTIAL_DECLARATION_MISSING",
                DecisionStatus.BLOCKED,
                "Manifest has no entry for: " + ", ".join(missing),
                "Add one unambiguous manifest entry per FDF species.",
            )
        )
    else:
        findings.append(
            ProjectInitFinding(
                "PSEUDOPOTENTIAL_DECLARATIONS_COMPLETE",
                DecisionStatus.PASS,
                "Every FDF species has a pseudopotential manifest entry.",
            )
        )
    findings.append(
        ProjectInitFinding(
            "STRUCTURE_CHEMISTRY_REVIEW_REQUIRED",
            DecisionStatus.REVIEW,
            (
                "The structure file is preserved byte-for-byte, but project "
                "initialization does not assert chemical equivalence with the FDF."
            ),
            "Inspect atom identity, ordering, units, cell, charge, and geometry before execution.",
        )
    )
    if input_report.status is DecisionStatus.REVIEW:
        findings.append(
            ProjectInitFinding(
                "FDF_REVIEW_CARRIED_FORWARD",
                DecisionStatus.REVIEW,
                "The project preserves unresolved FDF review findings.",
                "Resolve the reported findings before compiling a productive workflow.",
            )
        )
    return tuple(findings)


def _relative_files(
    request: ProjectInitRequest,
    *,
    structure_suffix: str,
) -> tuple[str, ...]:
    suffix = structure_suffix if structure_suffix else ".structure"
    return tuple(
        sorted(
            (
                "project.yaml",
                "project_init.lock.json",
                f"systems/{request.system_id}.yaml",
                f"systems/{request.system_id}.fdf",
                f"structures/{request.system_id}{suffix}",
                "pseudopotentials/manifest.yaml",
                "campaigns/baseline_preparation.yaml",
                "authorizations/preparation_only.yaml",
                "policies/review_required.yaml",
                "expected_contracts/preparation.yaml",
                "inputs/README.md",
                "cluster_profiles/README.md",
                "resources/README.md",
            )
        )
    )


def _json_text(payload: dict[str, object]) -> str:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )


def _generated_documents(
    request: ProjectInitRequest,
    *,
    structure_name: str,
    fdf_name: str,
    signature: str,
    source_hashes: dict[str, str],
) -> dict[str, str]:
    return {
        "project.yaml": _json_text(
            {
                "schema_version": "1.0",
                "project_id": request.project_id,
                "title": request.title,
                "engine": "siesta",
                "systems": [request.system_id],
                "campaigns": ["baseline_preparation"],
                "pseudopotential_manifest": "pseudopotentials/manifest.yaml",
                "metadata": {
                    "project_status": "DRAFT_REVIEW_REQUIRED",
                    "scientific_defaults_assigned": False,
                    "execution_authorized": False,
                },
            }
        ),
        f"systems/{request.system_id}.yaml": _json_text(
            {
                "system_id": request.system_id,
                "structure": structure_name,
                "species": _species_from_fdf(request.fdf),
                "input_template": fdf_name,
                "metadata": {
                    "source_preserved": True,
                    "scientific_review_required": True,
                },
            }
        ),
        "campaigns/baseline_preparation.yaml": _json_text(
            {
                "schema_version": "1.0",
                "campaign_id": "baseline_preparation",
                "system_id": request.system_id,
                "task_type": "SIESTA_PREPARATION",
                "parameter": None,
                "values": [],
                "authorization": "authorizations/preparation_only.yaml",
                "policy": "policies/review_required.yaml",
                "mode": "single",
                "synthetic_only": True,
                "metadata": {
                    "purpose": "prepare_and_validate_only",
                    "real_execution_authorized": False,
                },
            }
        ),
        "authorizations/preparation_only.yaml": _json_text(
            {
                "authorization_id": f"AUTH_{request.project_id}_PREPARATION",
                "allowed_task_types": ["SIESTA_PREPARATION"],
                "targets": [request.system_id],
                "forbidden_operations": [
                    "REAL_ENGINE",
                    "SBATCH",
                    "SSH",
                    "AUTO_RESTART",
                ],
                "stop_on_review": True,
                "issued_by": "SIESTAFLOW_PROJECT_INIT",
                "valid_days": 30,
            }
        ),
        "policies/review_required.yaml": _json_text(
            {
                "schema_version": "1.0",
                "execution": "preparation_only",
                "scientific_review_required": True,
                "real_evidence_promotion": False,
            }
        ),
        "expected_contracts/preparation.yaml": _json_text(
            {
                "schema_version": "1.0",
                "expected_decision": "REVIEW",
                "real_engine_runs": 0,
                "scheduler_submissions": 0,
            }
        ),
        "project_init.lock.json": _json_text(
            {
                "schema_version": "1.0",
                "project_id": request.project_id,
                "system_id": request.system_id,
                "request_sha256": signature,
                "source_sha256": source_hashes,
                "execution_authorized": False,
            }
        ),
        "inputs/README.md": (
            "# Inputs\n\n"
            f"The preserved FDF source is `../{fdf_name}`. No scientific "
            "parameter was selected by project initialization.\n"
        ),
        "cluster_profiles/README.md": (
            "# Cluster profiles\n\n"
            "No cluster profile is selected during project initialization.\n"
        ),
        "resources/README.md": (
            "# Resources\n\n"
            "No CPU, memory, walltime, or partition default is assigned here.\n"
        ),
    }


def _species_from_fdf(path: Path) -> list[str]:
    result = SiestaInputValidator().validate(FDFParser().parse_path(path))
    return list(result.species)


def render_project_init(result: ProjectInitResult) -> str:
    lines = [
        f"PROJECT INIT: {result.status}",
        f"DECISION: {result.decision.value}",
        f"ROOT: {result.root}",
        f"CHANGED: {'YES' if result.changed else 'NO'}",
        "EXECUTION_AUTHORIZED: NO",
    ]
    for finding in result.findings:
        lines.append(f"[{finding.status.value}] {finding.code}")
        lines.append(f"  {finding.message}")
        if finding.hint:
            lines.append(f"  Suggested action: {finding.hint}")
    lines.append(f"FILES: {len(result.planned_files)}")
    return "\n".join(lines)
