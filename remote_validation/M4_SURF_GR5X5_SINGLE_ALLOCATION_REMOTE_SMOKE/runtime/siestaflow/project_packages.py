"""Versioned, engine-neutral project package contracts.

Project data belongs in a package directory.  The runtime validates and loads
that data without knowing chemical species, campaign names, or parameter grids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


REQUIRED_DIRECTORIES = (
    "systems", "structures", "pseudopotentials", "campaigns", "policies",
    "authorizations", "expected_contracts",
)


def load_structured(path: Path) -> dict[str, Any]:
    """Load JSON or YAML; JSON-encoded YAML needs no optional dependency."""
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError(f"{path} is not JSON-compatible YAML and PyYAML is unavailable") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"structured document must be a mapping: {path}")
    return value


def _relative_path(raw: str, *, field: str) -> Path:
    posix = PurePosixPath(raw.replace("\\", "/"))
    if not raw or posix.is_absolute() or ".." in posix.parts or posix.parts[0].endswith(":"):
        raise ValueError(f"unsafe relative path in {field}: {raw}")
    return Path(*posix.parts)


@dataclass(frozen=True)
class ProjectSystem:
    system_id: str
    structure: str
    species: tuple[str, ...]
    input_template: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class DeclarativeCampaign:
    campaign_id: str
    system_id: str
    task_type: str
    parameter: str | None
    values: tuple[str, ...]
    authorization: str
    policy: str | None
    mode: str
    synthetic_only: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ProjectPackage:
    root: Path
    schema_version: str
    project_id: str
    title: str
    engine: str
    systems: Mapping[str, ProjectSystem]
    campaigns: Mapping[str, DeclarativeCampaign]
    pseudopotential_manifest: Path
    metadata: Mapping[str, Any]

    def campaign(self, campaign_id: str) -> DeclarativeCampaign:
        try:
            return self.campaigns[campaign_id]
        except KeyError as exc:
            raise KeyError(f"unknown campaign {campaign_id!r} in {self.project_id}") from exc

    def system(self, system_id: str) -> ProjectSystem:
        try:
            return self.systems[system_id]
        except KeyError as exc:
            raise KeyError(f"unknown system {system_id!r} in {self.project_id}") from exc


@dataclass(frozen=True)
class PackageValidation:
    valid: bool
    project_id: str | None
    schema_version: str | None
    findings: tuple[str, ...]
    systems: tuple[str, ...]
    campaigns: tuple[str, ...]


class ProjectPackageLoader:
    """Validate and load a self-contained project directory."""

    SUPPORTED_SCHEMA = {"1.0"}

    def inspect(self, root: Path) -> dict[str, Any]:
        result = self.validate(root)
        return {
            "path": str(root.resolve()), "valid": result.valid,
            "project_id": result.project_id, "schema_version": result.schema_version,
            "systems": list(result.systems), "campaigns": list(result.campaigns),
            "findings": list(result.findings), "execution_claim": "INSPECTION_ONLY",
        }

    def validate(self, root: Path) -> PackageValidation:
        findings: list[str] = []
        manifest_path = root / "project.yaml"
        if not manifest_path.is_file():
            return PackageValidation(False, None, None, ("MISSING:project.yaml",), (), ())
        try:
            data = load_structured(manifest_path)
        except (OSError, ValueError) as exc:
            return PackageValidation(False, None, None, (f"INVALID:project.yaml:{exc}",), (), ())
        schema = str(data.get("schema_version", ""))
        project_id = data.get("project_id")
        if schema not in self.SUPPORTED_SCHEMA:
            findings.append(f"UNSUPPORTED_SCHEMA:{schema}")
        if not isinstance(project_id, str) or not project_id.strip():
            findings.append("INVALID:project_id")
            project_id = None
        for directory in REQUIRED_DIRECTORIES:
            if not (root / directory).is_dir():
                findings.append(f"MISSING_DIRECTORY:{directory}")
        systems: list[str] = []
        campaigns: list[str] = []
        try:
            systems = self._validate_systems(root, data, findings)
            campaigns = self._validate_campaigns(root, data, systems, findings)
            pseudo_path = root / _relative_path(str(data.get("pseudopotential_manifest", "")), field="pseudopotential_manifest")
            if not pseudo_path.is_file():
                findings.append("MISSING:pseudopotential_manifest")
            else:
                pseudo = load_structured(pseudo_path)
                entries = pseudo.get("entries")
                if not isinstance(entries, list):
                    findings.append("INVALID:pseudopotential_manifest.entries")
                else:
                    declared = {str(item.get("species")) for item in entries if isinstance(item, dict)}
                    for system_name in systems:
                        system_data = load_structured(root / "systems" / f"{system_name}.yaml")
                        for species in system_data.get("species", []):
                            if str(species) not in declared:
                                findings.append(f"MISSING_PSEUDOPOTENTIAL_ENTRY:{system_name}:{species}")
        except (OSError, ValueError, TypeError) as exc:
            findings.append(f"INVALID_PACKAGE:{exc}")
        return PackageValidation(not findings, project_id, schema, tuple(findings), tuple(systems), tuple(campaigns))

    def load(self, root: Path) -> ProjectPackage:
        validation = self.validate(root)
        if not validation.valid:
            raise ValueError("invalid project package: " + "; ".join(validation.findings))
        data = load_structured(root / "project.yaml")
        systems: dict[str, ProjectSystem] = {}
        for system_id in validation.systems:
            item = load_structured(root / "systems" / f"{system_id}.yaml")
            systems[system_id] = ProjectSystem(
                system_id, str(item["structure"]), tuple(map(str, item["species"])),
                str(item["input_template"]), dict(item.get("metadata", {})),
            )
        campaigns: dict[str, DeclarativeCampaign] = {}
        for campaign_id in validation.campaigns:
            item = load_structured(root / "campaigns" / f"{campaign_id}.yaml")
            parameter = item.get("parameter")
            campaigns[campaign_id] = DeclarativeCampaign(
                campaign_id, str(item["system_id"]), str(item["task_type"]),
                str(parameter) if parameter is not None else None,
                tuple(map(str, item.get("values", []))), str(item["authorization"]),
                str(item["policy"]) if item.get("policy") is not None else None,
                str(item.get("mode", "sequential")), bool(item.get("synthetic_only", True)),
                dict(item.get("metadata", {})),
            )
        return ProjectPackage(
            root.resolve(), str(data["schema_version"]), str(data["project_id"]),
            str(data.get("title", data["project_id"])), str(data.get("engine", "siesta")),
            systems, campaigns,
            root.resolve() / _relative_path(str(data["pseudopotential_manifest"]), field="pseudopotential_manifest"),
            dict(data.get("metadata", {})),
        )

    @staticmethod
    def _validate_systems(root: Path, data: Mapping[str, Any], findings: list[str]) -> list[str]:
        identifiers = data.get("systems")
        if not isinstance(identifiers, list) or not identifiers:
            findings.append("INVALID:systems")
            return []
        result: list[str] = []
        for raw in identifiers:
            system_id = str(raw)
            path = root / "systems" / f"{system_id}.yaml"
            if not path.is_file():
                findings.append(f"MISSING_SYSTEM:{system_id}")
                continue
            item = load_structured(path)
            if item.get("system_id") != system_id:
                findings.append(f"SYSTEM_ID_MISMATCH:{system_id}")
            species = item.get("species")
            if not isinstance(species, list) or not species or len(set(map(str, species))) != len(species):
                findings.append(f"INVALID_SPECIES:{system_id}")
            for field in ("structure", "input_template"):
                relative = _relative_path(str(item.get(field, "")), field=field)
                if not (root / relative).is_file():
                    findings.append(f"MISSING_{field.upper()}:{system_id}:{relative.as_posix()}")
            result.append(system_id)
        return result

    @staticmethod
    def _validate_campaigns(root: Path, data: Mapping[str, Any], systems: list[str], findings: list[str]) -> list[str]:
        identifiers = data.get("campaigns")
        if not isinstance(identifiers, list) or not identifiers:
            findings.append("INVALID:campaigns")
            return []
        result: list[str] = []
        for raw in identifiers:
            campaign_id = str(raw)
            path = root / "campaigns" / f"{campaign_id}.yaml"
            if not path.is_file():
                findings.append(f"MISSING_CAMPAIGN:{campaign_id}")
                continue
            item = load_structured(path)
            if str(item.get("schema_version", "")) != "1.0":
                findings.append(f"UNSUPPORTED_CAMPAIGN_SCHEMA:{campaign_id}:{item.get('schema_version')}")
            if item.get("campaign_id") != campaign_id:
                findings.append(f"CAMPAIGN_ID_MISMATCH:{campaign_id}")
            if item.get("system_id") not in systems:
                findings.append(f"UNKNOWN_CAMPAIGN_SYSTEM:{campaign_id}")
            values = item.get("values", [])
            if not isinstance(values, list) or len(set(map(str, values))) != len(values):
                findings.append(f"INVALID_CAMPAIGN_VALUES:{campaign_id}")
            for field, directory in (("authorization", "authorizations"), ("policy", "policies")):
                if item.get(field) is not None:
                    relative = _relative_path(str(item[field]), field=field)
                    if relative.parts[0] != directory or not (root / relative).is_file():
                        findings.append(f"MISSING_{field.upper()}:{campaign_id}:{relative.as_posix()}")
            result.append(campaign_id)
        return result
