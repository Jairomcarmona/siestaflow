"""Reproducible remote preview packaging and conservative result import."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from .engines.siesta.output_parser import SiestaOutputParser
from .engines.siesta.pseudopotentials import PseudopotentialManifest
from .models import DecisionStatus, primitive
from .siesta_campaigns import CampaignDefinition, render_campaign_slurm
from .slurm_renderer import SlurmProfile


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _sha(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PackagePlan:
    campaign_id: str
    destination: str
    files: tuple[str, ...]
    hashes: dict[str, str]
    render_status: str
    dry_run: bool


class RemotePackager:
    def build_files(
        self, definition: CampaignDefinition, input_path: Path,
        profile: SlurmProfile | None = None,
        pseudopotentials: PseudopotentialManifest | None = None,
    ) -> dict[str, str]:
        cluster = profile or SlurmProfile()
        slurm = render_campaign_slurm(definition, cluster)
        input_name = input_path.name
        files: dict[str, str] = {
            "README_RUN.md": "# Remote validation preview\n\nHuman inspection is required. Configure profiles, run `preflight.sh`, then submit manually only after authorization. No command in this package submits a job.\n",
            "VALIDATION_CHECKLIST.md": "# Validation checklist\n\n- [ ] Yoltla profile verified for SIESTA\n- [ ] executable and launcher configured\n- [ ] pseudopotential paths and hashes verified\n- [ ] MPI and modules verified\n- [ ] human authorization recorded\n",
            "campaign.yaml": _simple_yaml({"campaign_id": definition.manifest.campaign_id, "status": definition.status, **definition.metadata}),
            "authorization.json": _canonical(primitive(definition.authorization)),
            "cluster_profile.yaml": _simple_yaml(cluster.to_dict()),
            "engine_profile.yaml": "engine:\n  executable: null\n  launcher:\n    type: null\n    command_template: null\n",
            "preflight.sh": _preflight_script(pseudopotentials),
            "submit_campaign.slurm": slurm.script,
            "inspect_job.sh": "#!/usr/bin/env bash\nset -euo pipefail\n: \"${JOB_ID:?JOB_ID must be configured}\"\nsqueue -j \"$JOB_ID\"\nsacct -j \"$JOB_ID\" --format=JobID,State,ExitCode,Elapsed\n",
            "collect_results.sh": "#!/usr/bin/env bash\nset -euo pipefail\n: \"${RESULT_DIR:?RESULT_DIR must be configured}\"\ntar -czf remote-results.tar.gz \"$RESULT_DIR\"\necho RESULTS_COLLECTED_FOR_MANUAL_TRANSFER\n",
            "expected_files.txt": "results/siesta.out\nevents.jsonl\nartifacts.jsonl\nresult_manifest.json\n",
            f"inputs/{input_name}": input_path.read_text(encoding="utf-8"),
            "scripts/run_worker.py": "raise SystemExit('REMOTE_PREFLIGHT_REQUIRES_CONFIGURATION')\n",
        }
        file_hashes = {name: _sha(content) for name, content in sorted(files.items())}
        validation = {
            "campaign_id": definition.manifest.campaign_id,
            "package_type": "REMOTE_SANITY_PACKAGE_PREVIEW",
            "render_status": slurm.status.value,
            "input_sha256": definition.input_sha256,
            "scientific_status": "SANITY_READY_PENDING_PREFLIGHT",
            "real_execution_authorized": False,
            "pseudopotentials_included": False,
            "pseudopotential_requirements": {
                "entries": [
                    {"species": item.species, "filename": item.filename, "sha256": item.sha256}
                    for item in (pseudopotentials.entries if pseudopotentials else ())
                ],
                "distribution_status": "EXTERNAL_NOT_PACKAGED",
            },
            "files": file_hashes,
        }
        files["validation_manifest.json"] = _canonical(validation)
        files["validation_manifest.sha256"] = _sha(files["validation_manifest.json"]) + "  validation_manifest.json\n"
        files["checksums.sha256"] = "".join(f"{_sha(content)}  {name}\n" for name, content in sorted(files.items()))
        return files

    def package(
        self,
        definition: CampaignDefinition,
        input_path: Path,
        output_root: Path,
        *,
        profile: SlurmProfile | None = None,
        pseudopotentials: PseudopotentialManifest | None = None,
        dry_run: bool = False,
    ) -> PackagePlan:
        files = self.build_files(definition, input_path, profile, pseudopotentials)
        destination = output_root / definition.manifest.campaign_id
        if not dry_run:
            if destination.exists():
                raise FileExistsError(f"remote package already exists: {destination}")
            for name, content in files.items():
                path = destination.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
        return PackagePlan(
            definition.manifest.campaign_id, str(destination), tuple(sorted(files)),
            {name: _sha(content) for name, content in sorted(files.items())},
            "PREVIEW_WITH_UNVERIFIED_PROFILE", dry_run,
        )


class ImportStatus(str, Enum):
    REMOTE_RESULTS_IMPORTED = "REMOTE_RESULTS_IMPORTED"
    REMOTE_RESULTS_REVIEW = "REMOTE_RESULTS_REVIEW"
    REMOTE_RESULTS_INVALID = "REMOTE_RESULTS_INVALID"
    REMOTE_RESULTS_INCOMPLETE = "REMOTE_RESULTS_INCOMPLETE"


@dataclass(frozen=True)
class ImportReport:
    status: ImportStatus
    campaign_id: str | None
    synthetic: bool
    output_classification: str | None
    gate: str | None
    missing_files: tuple[str, ...]
    findings: tuple[str, ...]
    preserved_original: str | None
    dry_run: bool


class RemoteResultImporter:
    REQUIRED = ("result_manifest.json", "results/siesta.out", "events.jsonl", "artifacts.jsonl", "checksums.sha256")

    def import_bundle(
        self,
        bundle: Path,
        destination: Path,
        *,
        expected_campaign_id: str | None = None,
        dry_run: bool = False,
    ) -> ImportReport:
        missing = tuple(name for name in self.REQUIRED if not (bundle / name).is_file())
        if missing:
            return ImportReport(ImportStatus.REMOTE_RESULTS_INCOMPLETE, expected_campaign_id, True, None, DecisionStatus.REVIEW.value, missing, ("required files are missing",), None, dry_run)
        try:
            manifest = json.loads((bundle / "result_manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ImportReport(ImportStatus.REMOTE_RESULTS_INVALID, None, True, None, None, (), (f"invalid manifest: {exc}",), None, dry_run)
        campaign_id = manifest.get("campaign_id")
        synthetic = bool(manifest.get("synthetic", False))
        if expected_campaign_id and campaign_id != expected_campaign_id:
            return ImportReport(ImportStatus.REMOTE_RESULTS_INVALID, campaign_id, synthetic, None, None, (), ("campaign identity mismatch",), None, dry_run)
        checksum_findings = _verify_checksums(bundle)
        if checksum_findings:
            return ImportReport(ImportStatus.REMOTE_RESULTS_INVALID, campaign_id, synthetic, None, None, (), tuple(checksum_findings), None, dry_run)
        output = (bundle / "results" / "siesta.out").read_text(encoding="utf-8", errors="replace")
        parser = SiestaOutputParser()
        parsed = parser.parse(output.splitlines(keepends=True), synthetic=synthetic)
        gate = parser.gate(parsed)
        status = ImportStatus.REMOTE_RESULTS_IMPORTED if gate.status is DecisionStatus.PASS else ImportStatus.REMOTE_RESULTS_REVIEW
        preserved = destination / "original_bundle"
        findings = [parsed.provisional_status]
        if synthetic:
            findings.append("SYNTHETIC_BUNDLE_NOT_REAL_EVIDENCE")
        if not dry_run:
            if destination.exists():
                raise FileExistsError(f"import destination already exists: {destination}")
            shutil.copytree(bundle, preserved)
            destination.mkdir(parents=True, exist_ok=True)
            report_data = {
                "status": status.value, "campaign_id": campaign_id, "synthetic": synthetic,
                "output_classification": parsed.classification.value, "gate": gate.status.value,
                "findings": findings, "real_evidence_promoted": False,
            }
            (destination / "import_report.json").write_text(_canonical(report_data), encoding="utf-8", newline="\n")
        return ImportReport(status, campaign_id, synthetic, parsed.classification.value, gate.status.value, (), tuple(findings), str(preserved) if not dry_run else None, dry_run)


def create_synthetic_result_bundle(path: Path, campaign_id: str, output: str) -> None:
    files = {
        "result_manifest.json": _canonical({"campaign_id": campaign_id, "synthetic": True, "real_evidence": False}),
        "results/siesta.out": output,
        "events.jsonl": _canonical({"event": "SYNTHETIC_TASK_COMPLETED"}),
        "artifacts.jsonl": "",
    }
    for name, content in files.items():
        target = path.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    (path / "checksums.sha256").write_text("".join(f"{_sha(content)}  {name}\n" for name, content in sorted(files.items())), encoding="utf-8", newline="\n")


def _verify_checksums(bundle: Path) -> list[str]:
    findings = []
    for line in (bundle / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            expected, name = line.split(None, 1)
            name = name.strip().lstrip("*")
        except ValueError:
            findings.append("invalid checksum line")
            continue
        path = bundle.joinpath(*PurePosixPath(name).parts)
        if not path.is_file():
            findings.append(f"checksum target missing: {name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            findings.append(f"checksum mismatch: {name}")
    return findings


def _simple_yaml(data: dict[str, Any], indent: int = 0) -> str:
    lines = []
    for key, value in data.items():
        prefix = " " * indent + f"{key}:"
        if isinstance(value, dict):
            lines.append(prefix)
            lines.append(_simple_yaml(value, indent + 2).rstrip())
        elif isinstance(value, (list, tuple)):
            lines.append(prefix)
            lines.extend(" " * (indent + 2) + f"- {item}" for item in value)
        elif value is None:
            lines.append(prefix + " null")
        elif isinstance(value, bool):
            lines.append(prefix + (" true" if value else " false"))
        else:
            lines.append(prefix + f" {value}")
    return "\n".join(lines) + "\n"


def _preflight_script(manifest: PseudopotentialManifest | None) -> str:
    checks = "".join(
        f'  echo "{item.sha256}  $PSEUDO_DIR/{item.filename}" | sha256sum -c - || missing=1\n'
        for item in (manifest.entries if manifest else ()) if item.sha256
    )
    return """#!/usr/bin/env bash
set -euo pipefail
missing=0
for command in bash squeue sacct sbatch sha256sum df; do
  command -v "$command" >/dev/null 2>&1 || { echo "MISSING_COMMAND:$command" >&2; missing=1; }
done
: "${SIESTA_EXECUTABLE:=}"
: "${MPI_LAUNCHER:=}"
: "${PSEUDO_DIR:=}"
for variable in SIESTA_EXECUTABLE MPI_LAUNCHER PSEUDO_DIR; do
  [[ -n "${!variable}" ]] || { echo "MISSING_CONFIGURATION:$variable" >&2; missing=1; }
done
[[ -x "$SIESTA_EXECUTABLE" ]] || missing=1
[[ -d "$PSEUDO_DIR" ]] || missing=1
[[ -r validation_manifest.json ]] || missing=1
[[ -w . ]] || missing=1
df -Pk . >/dev/null
if [[ -n "$MPI_LAUNCHER" ]]; then
  command -v "${MPI_LAUNCHER%% *}" >/dev/null 2>&1 || missing=1
fi
if [[ -x "$SIESTA_EXECUTABLE" ]]; then
  "$SIESTA_EXECUTABLE" --version >/dev/null 2>&1 || missing=1
fi
if [[ -d "$PSEUDO_DIR" ]]; then
""" + checks + """fi
sha256sum -c checksums.sha256 >/dev/null || missing=1
echo "VERSION_MPI_PSEUDO_HASH_AND_PATH_CHECKS_REQUIRE_CLUSTER_CONFIGURATION" >&2
echo REMOTE_PREFLIGHT_REQUIRES_CONFIGURATION >&2
exit 2
"""
