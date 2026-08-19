"""Content-addressed, arbitrary-species pseudopotential audit and staging."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
import shutil
from typing import Any

from ...models import DecisionStatus
from ...project_packages import load_structured


@dataclass(frozen=True)
class PseudopotentialEntry:
    species: str
    filename: str
    format: str
    sha256: str | None
    source: str
    xc_family: str | None
    relativity: str | None
    valence_metadata: dict[str, Any] = field(default_factory=dict)
    distribution_status: str = "EXTERNAL_NOT_PACKAGED"
    location_status: str = "UNCONFIGURED"
    path: str | None = None


@dataclass(frozen=True)
class PseudopotentialManifest:
    entries: tuple[PseudopotentialEntry, ...]
    schema_version: str = "1.0"

    @classmethod
    def load(cls, path: Path) -> "PseudopotentialManifest":
        data = load_structured(path)
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("pseudopotential manifest entries must be a list")
        entries = tuple(PseudopotentialEntry(**item) for item in raw_entries)
        species = [item.species.casefold() for item in entries]
        filenames = [item.filename.casefold() for item in entries]
        if len(set(species)) != len(species) or len(set(filenames)) != len(filenames):
            raise ValueError("pseudopotential manifest species and filenames must be unique")
        for item in entries:
            if Path(item.filename).name != item.filename or not re.fullmatch(r"[A-Za-z0-9._-]+", item.filename):
                raise ValueError(f"unsafe pseudopotential filename: {item.filename}")
            if item.sha256 is not None and (len(item.sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in item.sha256)):
                raise ValueError(f"invalid pseudopotential SHA-256: {item.filename}")
        return cls(entries, str(data.get("schema_version", "1.0")))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "entries": [asdict(item) for item in self.entries]}

@dataclass(frozen=True)
class PseudopotentialVerificationResult:
    status: DecisionStatus
    missing_species: tuple[str, ...]
    duplicate_species: tuple[str, ...]
    findings: tuple[str, ...]
    verified_hashes: tuple[str, ...]


class PseudopotentialVerifier:
    FORMATS = {"psml", "psf"}

    def verify(
        self,
        manifest: PseudopotentialManifest,
        expected_species: tuple[str, ...] | list[str],
    ) -> PseudopotentialVerificationResult:
        findings: list[str] = []
        verified: list[str] = []
        by_species: dict[str, list[PseudopotentialEntry]] = {}
        for entry in manifest.entries:
            by_species.setdefault(entry.species.casefold(), []).append(entry)
            if entry.format.casefold() not in self.FORMATS:
                findings.append(f"INVALID_FORMAT:{entry.species}:{entry.format}")
            expected_extension = "." + entry.format.casefold()
            if not entry.filename.casefold().endswith(expected_extension):
                findings.append(f"FORMAT_FILENAME_MISMATCH:{entry.filename}")
            if not entry.filename.casefold().startswith(entry.species.casefold()):
                findings.append(f"SPECIES_FILENAME_MISMATCH:{entry.species}:{entry.filename}")
            if entry.path:
                path = Path(entry.path)
                if not path.is_file():
                    findings.append(f"MISSING_FILE:{entry.species}:{path}")
                else:
                    actual = hashlib.sha256(path.read_bytes()).hexdigest()
                    if entry.sha256 and actual.casefold() != entry.sha256.casefold():
                        findings.append(f"HASH_MISMATCH:{entry.species}")
                    else:
                        verified.append(entry.species)
            elif entry.location_status != "EXTERNAL_NOT_PACKAGED":
                findings.append(f"LOCATION_UNCONFIGURED:{entry.species}")

        missing = tuple(species for species in expected_species if species.casefold() not in by_species)
        duplicates = tuple(items[0].species for items in by_species.values() if len(items) > 1)
        if missing:
            findings.extend(f"MISSING_SPECIES:{species}" for species in missing)
        if duplicates:
            findings.extend(f"DUPLICATE_SPECIES:{species}" for species in duplicates)

        hard = any(item.startswith(("INVALID_FORMAT", "FORMAT_FILENAME", "SPECIES_FILENAME", "HASH_MISMATCH", "DUPLICATE")) for item in findings)
        unavailable = bool(missing) or any(item.startswith(("MISSING_FILE", "LOCATION_UNCONFIGURED")) for item in findings)
        external = any(entry.location_status == "EXTERNAL_NOT_PACKAGED" and not entry.path for entry in manifest.entries)
        if hard:
            status = DecisionStatus.FAIL
        elif unavailable or external:
            status = DecisionStatus.BLOCKED
        else:
            status = DecisionStatus.PASS
        return PseudopotentialVerificationResult(status, missing, duplicates, tuple(findings), tuple(verified))


@dataclass(frozen=True)
class StagingEntry:
    species: str
    filename: str
    source: str | None
    destination: str
    status: str
    sha256: str | None


@dataclass(frozen=True)
class StagingReport:
    status: DecisionStatus
    example_status: str
    policy: str
    dry_run: bool
    entries: tuple[StagingEntry, ...]
    findings: tuple[str, ...]
    manifest_path: str | None


class PseudopotentialStager:
    """Stage manifest-declared files using an explicit copy or link policy."""

    POLICIES = {"copy", "link"}

    def stage(
        self,
        manifest: PseudopotentialManifest,
        source_root: Path,
        destination: Path,
        *,
        policy: str,
        dry_run: bool = False,
    ) -> StagingReport:
        if policy not in self.POLICIES:
            raise ValueError(f"unsupported staging policy: {policy}")
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise FileExistsError(f"staging destination is not an empty directory: {destination}")
        entries: list[StagingEntry] = []
        findings: list[str] = []
        for item in manifest.entries:
            if Path(item.filename).name != item.filename or any(separator in item.filename for separator in ("/", "\\")):
                findings.append(f"INVALID_MANIFEST_PATH:{item.species}:{item.filename}")
                entries.append(StagingEntry(item.species, item.filename, None, str(destination), "INVALID_MANIFEST", None))
                continue
            candidates = sorted(path for path in source_root.rglob(item.filename) if path.is_file()) if source_root.is_dir() else []
            target = destination / item.filename
            if len(candidates) != 1:
                status = "MISSING" if not candidates else "AMBIGUOUS"
                findings.append(f"{status}:{item.species}:{item.filename}:{len(candidates)}")
                entries.append(StagingEntry(item.species, item.filename, None, str(target), status, None))
                continue
            source = candidates[0]
            try:
                content = source.read_bytes()
            except OSError:
                findings.append(f"UNREADABLE:{item.species}:{item.filename}")
                entries.append(StagingEntry(item.species, item.filename, str(source), str(target), "UNREADABLE", None))
                continue
            digest = hashlib.sha256(content).hexdigest()
            valid_format = (
                item.format.casefold() == "psml" and b"<psml" in content[:8192].lower()
            ) or (
                item.format.casefold() == "psf" and bool(content.strip())
            )
            if not valid_format:
                findings.append(f"INVALID_FORMAT:{item.species}:{item.filename}")
                entries.append(StagingEntry(item.species, item.filename, str(source), str(target), "INVALID_FORMAT", digest))
                continue
            if item.sha256 and digest.casefold() != item.sha256.casefold():
                findings.append(f"HASH_MISMATCH:{item.species}:{item.filename}")
                entries.append(StagingEntry(item.species, item.filename, str(source), str(target), "HASH_MISMATCH", digest))
                continue
            if not dry_run:
                destination.mkdir(parents=True, exist_ok=True)
                if policy == "copy":
                    shutil.copy2(source, target)
                else:
                    target.symlink_to(source.resolve())
            entries.append(StagingEntry(item.species, item.filename, str(source), str(target), "PLANNED" if dry_run else "STAGED", digest))
        status = DecisionStatus.PASS if not findings else DecisionStatus.BLOCKED
        if not findings:
            example_status = "EXAMPLE_READY"
        elif any(item.startswith("HASH_MISMATCH") for item in findings):
            example_status = "EXAMPLE_BLOCKED_HASH_MISMATCH"
        elif any(item.startswith(("MISSING", "AMBIGUOUS")) for item in findings):
            example_status = "EXAMPLE_BLOCKED_MISSING_PSEUDOS"
        else:
            example_status = "EXAMPLE_BLOCKED_INVALID_MANIFEST"
        manifest_path = destination / "staging_manifest.json"
        if not dry_run and not findings:
            payload = {
                "schema_version": "1.0", "status": example_status, "policy": policy,
                "entries": [asdict(entry) for entry in entries],
            }
            manifest_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
        return StagingReport(status, example_status, policy, dry_run, tuple(entries), tuple(findings), str(manifest_path) if not dry_run and not findings else None)
