"""Public API for discovering and exercising repository project examples."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .engines.siesta.pseudopotentials import PseudopotentialManifest, PseudopotentialStager, StagingReport
from .project_packages import PackageValidation, ProjectPackage, ProjectPackageLoader
from .remote import ImportReport, RemoteResultImporter
from .siesta_campaigns import CampaignDefinition, SiestaCampaignFactory, simulate_definition


@dataclass(frozen=True)
class ExamplePackage:
    name: str
    path: Path
    project: ProjectPackage


@dataclass(frozen=True)
class ExampleRunReport:
    project_id: str
    campaign_id: str
    tasks: int
    variants: int
    decision: str
    launches: int
    allocations: int
    synthetic: bool


class ExampleRegistry:
    def __init__(self, roots: Iterable[Path]) -> None:
        self.roots = tuple(path.resolve() for path in roots)

    def list(self) -> tuple[tuple[str, Path], ...]:
        found: list[tuple[str, Path]] = []
        for root in self.roots:
            if not root.is_dir():
                continue
            for manifest in sorted(root.rglob("project.yaml")):
                if not (manifest.parent / "example.yaml").is_file():
                    continue
                relative = manifest.parent.relative_to(root).as_posix()
                found.append((relative, manifest.parent))
        return tuple(found)

    def resolve(self, name_or_path: str | Path) -> Path:
        direct = Path(name_or_path)
        if (direct / "project.yaml").is_file() and (direct / "example.yaml").is_file():
            return direct.resolve()
        matches = [path for name, path in self.list() if name == str(name_or_path) or path.name == str(name_or_path)]
        if len(matches) != 1:
            raise FileNotFoundError(f"expected one example named {name_or_path!s}, found {len(matches)}")
        return matches[0]

    def load(self, name_or_path: str | Path) -> ExamplePackage:
        path = self.resolve(name_or_path)
        return ExamplePackage(path.name, path, ProjectPackageLoader().load(path))


class ExampleService:
    def __init__(self, registry: ExampleRegistry) -> None:
        self.registry = registry

    def inspect(self, name_or_path: str | Path) -> dict[str, Any]:
        return ProjectPackageLoader().inspect(self.registry.resolve(name_or_path))

    def validate(self, name_or_path: str | Path) -> PackageValidation:
        return ProjectPackageLoader().validate(self.registry.resolve(name_or_path))

    def stage(
        self, name_or_path: str | Path, source_root: Path, destination: Path,
        *, policy: str, dry_run: bool = False,
    ) -> StagingReport:
        package = self.registry.load(name_or_path).project
        manifest = PseudopotentialManifest.load(package.pseudopotential_manifest)
        return PseudopotentialStager().stage(manifest, source_root, destination, policy=policy, dry_run=dry_run)

    def package(self, name_or_path: str | Path, output: Path, *, dry_run: bool = False) -> dict[str, Any]:
        example = self.registry.load(name_or_path)
        files = sorted(path for path in example.path.rglob("*") if path.is_file())
        archive = output / f"{example.name}.zip"
        hashes = {path.relative_to(example.path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        if not dry_run:
            output.mkdir(parents=True, exist_ok=True)
            if archive.exists():
                raise FileExistsError(f"example archive already exists: {archive}")
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
                for path in files:
                    name = path.relative_to(example.path).as_posix()
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    handle.writestr(info, path.read_bytes())
        return {"example": example.name, "archive": str(archive), "files": len(files), "hashes": hashes, "dry_run": dry_run}

    def run(self, name_or_path: str | Path, campaign_id: str, workspace: Path) -> ExampleRunReport:
        package = self.registry.load(name_or_path).project
        definition, variants = SiestaCampaignFactory().from_package(package, campaign_id)
        state, launcher, slurm = simulate_definition(definition, workspace)
        decision = state.final_decision.value if state.final_decision else "UNKNOWN"
        return ExampleRunReport(package.project_id, campaign_id, len(definition.manifest.tasks), len(variants), decision, len(launcher.launches), slurm.submissions, True)

    def import_results(
        self, bundle: Path, destination: Path, *, campaign_id: str | None = None,
        dry_run: bool = False,
    ) -> ImportReport:
        return RemoteResultImporter().import_bundle(
            bundle, destination, expected_campaign_id=campaign_id, dry_run=dry_run,
        )


def public_api_contract() -> dict[str, Any]:
    """Machine-readable surface used by documentation consistency tests."""
    return {
        "class": "ExamplePackage",
        "operations": ["list", "inspect", "validate", "stage", "package", "results import", "run"],
        "project_schema": "1.0",
    }
