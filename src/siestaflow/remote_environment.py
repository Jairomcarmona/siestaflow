"""M3 Yoltla environment probe packaging and evidence acceptance.

This module never opens a network connection, submits a job, or runs SIESTA.
It creates inert files for a human-operated remote workflow and imports the
resulting evidence locally.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .validation.embedded_code import STANDALONE_VALIDATOR
from .validation.scheduler_resolution import standalone_source as scheduler_resolution_source


PROBE_ID = "M3_YOLTLA_ENVIRONMENT_PROBE"
SENSITIVE = re.compile(r"(?:TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL|COOKIE)", re.I)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or path.parts[0].endswith(":"):
        raise ValueError(f"unsafe bundle path: {name}")
    return path.as_posix()


class EvidenceStatus(str, Enum):
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    MISSING = "MISSING"
    CONTRADICTORY = "CONTRADICTORY"


class RemoteEnvironmentStatus(str, Enum):
    REMOTE_ENVIRONMENT_ACCEPTED = "REMOTE_ENVIRONMENT_ACCEPTED"
    REMOTE_ENVIRONMENT_REVIEW = "REMOTE_ENVIRONMENT_REVIEW"
    REMOTE_ENVIRONMENT_FAILED = "REMOTE_ENVIRONMENT_FAILED"
    REMOTE_EVIDENCE_INCOMPLETE = "REMOTE_EVIDENCE_INCOMPLETE"


@dataclass(frozen=True)
class ProfileField:
    value: Any
    evidence_status: EvidenceStatus
    source_file: str | None
    observed_at: str | None


PROFILE_FIELDS = (
    "scheduler", "partition", "account", "QoS", "nodes", "ntasks",
    "cpus_per_task", "memory", "walltime", "signal", "launcher",
    "launcher_command", "module_commands", "siesta_executable",
    "siesta_version", "scratch_root", "project_root",
    "pseudopotential_root", "sacct_available",
)


@dataclass(frozen=True)
class YoltlaProfile:
    profile_status: str
    fields: Mapping[str, ProfileField]

    @classmethod
    def pending(cls) -> "YoltlaProfile":
        return cls("REMOTE_EVIDENCE_PENDING", {
            name: ProfileField(None, EvidenceStatus.MISSING, None, None)
            for name in PROFILE_FIELDS
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": "yoltla_siesta",
            "profile_status": self.profile_status,
            "fields": {
                key: {
                    "value": field.value,
                    "evidence_status": field.evidence_status.value,
                    "source_file": field.source_file,
                    "observed_at": field.observed_at,
                }
                for key, field in self.fields.items()
            },
        }

    def to_yaml(self) -> str:
        lines = ["profile_id: yoltla_siesta", f"profile_status: {self.profile_status}", "fields:"]
        for name in PROFILE_FIELDS:
            field = self.fields[name]
            lines.extend((
                f"  {name}:",
                f"    value: {_yaml_value(field.value)}",
                f"    evidence_status: {field.evidence_status.value}",
                f"    source_file: {_yaml_value(field.source_file)}",
                f"    observed_at: {_yaml_value(field.observed_at)}",
            ))
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ProbePackagePlan:
    probe_id: str
    destination: str
    files: tuple[str, ...]
    hashes: Mapping[str, str]
    dry_run: bool
    status: str = "REMOTE_EVIDENCE_PENDING"


class EnvironmentProbePackager:
    """Build a deterministic, no-input, no-pseudopotential probe package."""

    def __init__(
        self,
        pseudopotential_requirements: Mapping[str, str] | None = None,
        pseudopotential_status_labels: Mapping[str, str] | None = None,
    ) -> None:
        self.pseudopotential_requirements = dict(pseudopotential_requirements or {})
        self.pseudopotential_status_labels = dict(pseudopotential_status_labels or {
            "verified": "PSEUDOPOTENTIAL_SET_HASH_VERIFIED",
            "missing": "PSEUDOPOTENTIAL_SET_MISSING",
            "mismatch": "PSEUDOPOTENTIAL_SET_HASH_MISMATCH",
            "review": "PSEUDOPOTENTIAL_SET_REVIEW",
        })

    def build_files(self) -> dict[str, str]:
        files = _probe_files(self.pseudopotential_requirements, self.pseudopotential_status_labels)
        hashes = {name: sha256_bytes(content) for name, content in sorted(files.items())}
        manifest = {
            "probe_id": PROBE_ID,
            "schema_version": "1.0",
            "package_type": "YOLTLA_REMOTE_ENVIRONMENT_CHARACTERIZATION",
            "reproducibility_epoch": "M3_STATIC_V3",
            "package_revision": 3,
            "supersedes": "M3_STATIC_V2",
            "scientific_calculation_permitted": False,
            "contains_fdf": False,
            "contains_geometry": False,
            "contains_pseudopotentials": False,
            "remote_execution_mode": "HUMAN_OPERATED_ONLY",
            "scheduler_selection_policy": "UNIQUE_COMPATIBLE_DEFAULT_PARTITION_OR_EVIDENCE_BOUND_HUMAN_SELECTION",
            "expected_pseudopotentials": {
                "entries": self.pseudopotential_requirements,
                "status_labels": self.pseudopotential_status_labels,
                "distribution_status": "EXTERNAL_NOT_PACKAGED",
            },
            "files": hashes,
        }
        files["probe_manifest.json"] = canonical_json(manifest)
        files["probe_manifest.sha256"] = f"{sha256_bytes(files['probe_manifest.json'])}  probe_manifest.json\n"
        files["checksums.sha256"] = "".join(
            f"{sha256_bytes(content)}  {name}\n" for name, content in sorted(files.items())
        )
        return files

    def package(self, output_root: Path, *, dry_run: bool = False) -> ProbePackagePlan:
        files = self.build_files()
        destination = output_root / PROBE_ID
        if not dry_run:
            if destination.exists():
                raise FileExistsError(f"probe package already exists: {destination}")
            for name, content in files.items():
                target = destination.joinpath(*PurePosixPath(safe_member_name(name)).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
        return ProbePackagePlan(
            PROBE_ID, str(destination), tuple(sorted(files)),
            {name: sha256_bytes(content) for name, content in sorted(files.items())}, dry_run,
        )


@dataclass(frozen=True)
class EnvironmentImportReport:
    status: RemoteEnvironmentStatus
    probe_id: str | None
    evidence_type: str | None
    synthetic: bool
    missing_files: tuple[str, ...]
    findings: tuple[str, ...]
    requirements: Mapping[str, bool]
    profile: YoltlaProfile
    preserved_original: str | None
    dry_run: bool


class RemoteEnvironmentImporter:
    REQUIRED = (
        "results_manifest.json", "results_manifest.sha256", "checksums.sha256",
        "login_probe/summary.json", "scheduler_probe/summary.json",
        "siesta_discovery/summary.json", "mpi_discovery/summary.json",
        "slurm_accounting/summary.json", "filesystem/summary.json",
        "pseudo_verification/summary.json", "stdout/login_probe.log",
        "stdout/scheduler.out", "stderr/login_probe.err", "stderr/scheduler.err",
    )

    def import_bundle(
        self,
        bundle: Path,
        destination: Path,
        *,
        dry_run: bool = False,
        canonical_profile_path: Path | None = None,
    ) -> EnvironmentImportReport:
        try:
            contents = _read_bundle(bundle)
        except (OSError, tarfile.TarError, ValueError) as exc:
            return self._failed(f"bundle cannot be read safely: {exc}", dry_run=dry_run)
        missing = tuple(name for name in self.REQUIRED if name not in contents)
        if missing:
            return EnvironmentImportReport(
                RemoteEnvironmentStatus.REMOTE_EVIDENCE_INCOMPLETE, None, None, True,
                missing, ("required remote evidence is incomplete",), {},
                YoltlaProfile.pending(), None, dry_run,
            )
        checksum_findings = _verify_content_checksums(contents)
        manifest_hash_findings = _verify_named_hash(contents, "results_manifest.json", "results_manifest.sha256")
        if checksum_findings or manifest_hash_findings:
            return self._failed(*(checksum_findings + manifest_hash_findings), dry_run=dry_run)
        try:
            manifest = _json_file(contents, "results_manifest.json")
            evidence = {
                "login": _json_file(contents, "login_probe/summary.json"),
                "scheduler": _json_file(contents, "scheduler_probe/summary.json"),
                "siesta": _json_file(contents, "siesta_discovery/summary.json"),
                "mpi": _json_file(contents, "mpi_discovery/summary.json"),
                "accounting": _json_file(contents, "slurm_accounting/summary.json"),
                "filesystem": _json_file(contents, "filesystem/summary.json"),
                "pseudo": _json_file(contents, "pseudo_verification/summary.json"),
            }
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            return self._failed(f"invalid structured evidence: {exc}", dry_run=dry_run)
        if manifest.get("probe_id") != PROBE_ID:
            return self._failed("probe identity mismatch", dry_run=dry_run)
        if manifest.get("scientific_calculation_performed") is not False:
            return self._failed("bundle does not prove scientific_calculation_performed=false", dry_run=dry_run)
        synthetic = bool(manifest.get("synthetic", False))
        evidence_type = manifest.get("evidence_type")
        requirements, findings = _evaluate_requirements(evidence)
        pseudo_entries = tuple(evidence["pseudo"].get("entries", {}).values())
        pseudo_mismatch = any(
            item.get("exists") and item.get("readable") and not item.get("verified")
            for item in pseudo_entries if isinstance(item, dict)
        ) or "MISMATCH" in str(evidence["pseudo"].get("status", ""))
        if pseudo_mismatch:
            status = RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED
            findings.append("pseudopotential hash mismatch is blocking")
        elif synthetic:
            status = RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_REVIEW
            findings.append("SYNTHETIC_BUNDLE_REJECTED_AS_REAL_EVIDENCE")
        elif evidence_type != "REAL_REMOTE_ENVIRONMENT_PROBE":
            status = RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED
            findings.append("real evidence type is not established")
        elif all(requirements.values()):
            status = RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_ACCEPTED
        else:
            status = RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_REVIEW
        profile = _build_profile(evidence, status, synthetic)
        preserved: str | None = None
        if not dry_run:
            if destination.exists():
                raise FileExistsError(f"environment import destination already exists: {destination}")
            destination.mkdir(parents=True)
            preserved_path = destination / "original_bundle"
            if bundle.is_dir():
                shutil.copytree(bundle, preserved_path)
            else:
                preserved_path.mkdir()
                shutil.copy2(bundle, preserved_path / bundle.name)
            preserved = str(preserved_path)
            (destination / "import_report.json").write_text(canonical_json({
                "status": status.value, "probe_id": PROBE_ID,
                "evidence_type": evidence_type, "synthetic": synthetic,
                "requirements": requirements, "findings": findings,
            }), encoding="utf-8", newline="\n")
            (destination / "yoltla_candidate.yaml").write_text(profile.to_yaml(), encoding="utf-8", newline="\n")
            if status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_ACCEPTED and canonical_profile_path:
                if canonical_profile_path.exists():
                    existing = canonical_profile_path.read_text(encoding="utf-8")
                    if "profile_status: REMOTE_EVIDENCE_PENDING" not in existing:
                        raise FileExistsError(f"canonical Yoltla profile is not a replaceable pending skeleton: {canonical_profile_path}")
                canonical_profile_path.parent.mkdir(parents=True, exist_ok=True)
                canonical_profile_path.write_text(profile.to_yaml(), encoding="utf-8", newline="\n")
        return EnvironmentImportReport(
            status, PROBE_ID, evidence_type, synthetic, (), tuple(findings),
            requirements, profile, preserved, dry_run,
        )

    @staticmethod
    def _failed(*findings: str, dry_run: bool) -> EnvironmentImportReport:
        return EnvironmentImportReport(
            RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED, None, None, True,
            (), tuple(findings), {}, YoltlaProfile.pending(), None, dry_run,
        )


def create_environment_fixture_bundle(
    root: Path,
    *,
    synthetic: bool = True,
    complete: bool = True,
    pseudo_status: str = "PSEUDOPOTENTIAL_SET_HASH_VERIFIED",
    pseudopotential_requirements: Mapping[str, str] | None = None,
    squeue_present: bool = False,
    terminal_evidence: bool = True,
) -> None:
    """Create explicit test evidence; synthetic fixtures can never be accepted."""
    observed = "2026-07-20T00:00:00Z"
    requirements = dict(pseudopotential_requirements or {})
    verified = pseudo_status == "PSEUDOPOTENTIAL_SET_HASH_VERIFIED"
    data: dict[str, Any] = {
        "results_manifest.json": {
            "probe_id": PROBE_ID,
            "evidence_type": "SYNTHETIC_REMOTE_ENVIRONMENT_PROBE" if synthetic else "REAL_REMOTE_ENVIRONMENT_PROBE",
            "scientific_calculation_performed": False,
            "synthetic": synthetic,
            "observed_at": observed,
        },
        "login_probe/summary.json": {
            "observed_at": observed, "scheduler": "SLURM", "slurm_commands_available": True,
            "eligible_associations": [{"partition": "test-partition", "account": "test-account", "qos": "test-qos"}],
            "module_commands": ["module load siesta/test"],
        },
        "scheduler_probe/summary.json": {
            "observed_at": observed, "job_id": "12345", "partition": "test-partition",
            "account": "test-account", "qos": "test-qos", "nodes": 1, "ntasks": 1,
            "cpus_per_task": 1, "memory": "1G", "walltime": "00:02:00",
            "signal": "B:USR1@60", "signal_received": True,
        },
        "siesta_discovery/summary.json": {
            "observed_at": observed, "executable": "/apps/siesta/5.4.2/bin/siesta",
            "version": "5.4.2", "version_evidence": "module metadata",
        },
        "mpi_discovery/summary.json": {
            "observed_at": observed, "launcher": "mpiexec.hydra",
            "launcher_command": "/usr/bin/mpiexec.hydra", "version": "HYDRA test",
        },
        "slurm_accounting/summary.json": {
            "observed_at": observed, "squeue_present": squeue_present,
            "sacct_available": True, "terminal_evidence": terminal_evidence,
            "state": "COMPLETED" if terminal_evidence else None,
            "exit_code": "0:0" if terminal_evidence else None,
            "elapsed": "00:00:10", "alloc_tres": "cpu=1,mem=1G,node=1",
            "max_rss": "1M", "node_list": "node-test",
            "partition": "test-partition", "account": "test-account", "qos": "test-qos",
        },
        "filesystem/summary.json": {
            "observed_at": observed, "project_root": "/project/test",
            "project_root_visible": True, "scratch_root": "/scratch/test",
            "scratch_writable": True,
        },
        "pseudo_verification/summary.json": {
            "observed_at": observed, "status": pseudo_status, "root": "/pseudos/test",
            "entries": {
                filename: {"filename": filename, "sha256": digest, "verified": verified}
                for filename, digest in requirements.items()
            },
        },
    }
    text_files: dict[str, str] = {name: canonical_json(value) for name, value in data.items()}
    text_files.update({
        "stdout/login_probe.log": "SYNTHETIC LOGIN PROBE\n",
        "stdout/scheduler.out": "SYNTHETIC SCHEDULER PROBE\n",
        "stderr/login_probe.err": "",
        "stderr/scheduler.err": "",
    })
    if not complete:
        text_files.pop("mpi_discovery/summary.json")
    for name, content in text_files.items():
        target = root.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    manifest_hash = sha256_bytes(text_files["results_manifest.json"])
    (root / "results_manifest.sha256").write_text(
        f"{manifest_hash}  results_manifest.json\n", encoding="utf-8", newline="\n",
    )
    checksum_inputs = dict(text_files)
    checksum_inputs["results_manifest.sha256"] = f"{manifest_hash}  results_manifest.json\n"
    (root / "checksums.sha256").write_text("".join(
        f"{sha256_bytes(content)}  {name}\n" for name, content in sorted(checksum_inputs.items())
    ), encoding="utf-8", newline="\n")


def redact_environment(values: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if not SENSITIVE.search(key)}


def _evaluate_requirements(evidence: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, bool], list[str]]:
    login, scheduler = evidence["login"], evidence["scheduler"]
    siesta, mpi = evidence["siesta"], evidence["mpi"]
    accounting, filesystem, pseudo = evidence["accounting"], evidence["filesystem"], evidence["pseudo"]
    contradictions = any(
        scheduler.get(key) and accounting.get(key) and scheduler.get(key) != accounting.get(key)
        for key in ("partition", "account", "qos")
    )
    requirements = {
        "slurm_job_terminal_demonstrated": bool(accounting.get("terminal_evidence")) and accounting.get("state") == "COMPLETED" and str(accounting.get("exit_code")) in {"0", "0:0"},
        "account_verified": bool(scheduler.get("account")),
        "partition_verified": bool(scheduler.get("partition")),
        "slurm_commands_functional": bool(login.get("slurm_commands_available")),
        "siesta_located": bool(siesta.get("executable")),
        "siesta_version_evidenced": bool(siesta.get("version")),
        "launcher_evidenced": bool(mpi.get("launcher") and mpi.get("launcher_command")),
        "filesystem_verified": bool(filesystem.get("project_root_visible") and filesystem.get("scratch_writable")),
        "pseudopotentials_verified": all(
            bool(item.get("verified")) for item in pseudo.get("entries", {}).values()
        ) and (bool(pseudo.get("entries")) or "VERIFIED" in str(pseudo.get("status", ""))),
        "sacct_terminal_evidence": bool(accounting.get("sacct_available") and accounting.get("terminal_evidence")),
        "controlled_signal_received": bool(scheduler.get("signal_received")),
        "scheduler_resources_observed": bool(
            scheduler.get("nodes") and scheduler.get("ntasks") and
            scheduler.get("cpus_per_task") and scheduler.get("walltime") and
            scheduler.get("signal") and accounting.get("alloc_tres")
        ),
        "no_blocking_contradictions": not contradictions,
    }
    findings = [f"MISSING_REQUIREMENT:{name}" for name, passed in requirements.items() if not passed]
    if not accounting.get("squeue_present") and not accounting.get("terminal_evidence"):
        findings.append("EMPTY_SQUEUE_IS_NOT_TERMINAL_SUCCESS")
    return requirements, findings


def _build_profile(
    evidence: Mapping[str, Mapping[str, Any]],
    decision: RemoteEnvironmentStatus,
    synthetic: bool,
) -> YoltlaProfile:
    login, scheduler = evidence["login"], evidence["scheduler"]
    siesta, mpi = evidence["siesta"], evidence["mpi"]
    accounting, filesystem, pseudo = evidence["accounting"], evidence["filesystem"], evidence["pseudo"]
    memory_match = re.search(r"(?:^|,)mem=([^,]+)", str(accounting.get("alloc_tres") or ""))
    observed_memory = scheduler.get("memory") or (memory_match.group(1) if memory_match else None)
    values = {
        "scheduler": ("SLURM", "login_probe/summary.json", login.get("observed_at")),
        "partition": (scheduler.get("partition"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "account": (scheduler.get("account"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "QoS": (scheduler.get("qos"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "nodes": (scheduler.get("nodes"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "ntasks": (scheduler.get("ntasks"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "cpus_per_task": (scheduler.get("cpus_per_task"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "memory": (observed_memory, "slurm_accounting/summary.json" if memory_match else "scheduler_probe/summary.json", accounting.get("observed_at") if memory_match else scheduler.get("observed_at")),
        "walltime": (scheduler.get("walltime"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "signal": (scheduler.get("signal"), "scheduler_probe/summary.json", scheduler.get("observed_at")),
        "launcher": (mpi.get("launcher"), "mpi_discovery/summary.json", mpi.get("observed_at")),
        "launcher_command": (mpi.get("launcher_command"), "mpi_discovery/summary.json", mpi.get("observed_at")),
        "module_commands": (login.get("module_commands"), "login_probe/summary.json", login.get("observed_at")),
        "siesta_executable": (siesta.get("executable"), "siesta_discovery/summary.json", siesta.get("observed_at")),
        "siesta_version": (siesta.get("version"), "siesta_discovery/summary.json", siesta.get("observed_at")),
        "scratch_root": (filesystem.get("scratch_root"), "filesystem/summary.json", filesystem.get("observed_at")),
        "project_root": (filesystem.get("project_root"), "filesystem/summary.json", filesystem.get("observed_at")),
        "pseudopotential_root": (pseudo.get("root"), "pseudo_verification/summary.json", pseudo.get("observed_at")),
        "sacct_available": (accounting.get("sacct_available"), "slurm_accounting/summary.json", accounting.get("observed_at")),
    }
    fields: dict[str, ProfileField] = {}
    for name, (value, source, observed) in values.items():
        if value is None or value == []:
            status = EvidenceStatus.MISSING
            source = observed = None
        elif synthetic:
            status = EvidenceStatus.INFERRED
        elif decision is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_ACCEPTED:
            status = EvidenceStatus.VERIFIED if name in {"siesta_version", "launcher", "launcher_command", "pseudopotential_root", "sacct_available"} else EvidenceStatus.OBSERVED
        else:
            status = EvidenceStatus.OBSERVED
        fields[name] = ProfileField(value, status, source, observed)
    return YoltlaProfile(decision.value, fields)


def _read_bundle(bundle: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    if bundle.is_dir():
        for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
            name = safe_member_name(path.relative_to(bundle).as_posix())
            result[name] = path.read_bytes()
        return result
    if not bundle.is_file():
        raise OSError(f"bundle does not exist: {bundle}")
    with tarfile.open(bundle, "r:*") as archive:
        for member in archive.getmembers():
            name = safe_member_name(member.name)
            if member.issym() or member.islnk():
                raise ValueError(f"links are forbidden in bundles: {name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"unsupported bundle member: {name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"cannot read bundle member: {name}")
            result[name] = stream.read()
    return result


def _verify_content_checksums(contents: Mapping[str, bytes]) -> list[str]:
    findings: list[str] = []
    try:
        lines = contents["checksums.sha256"].decode("utf-8").splitlines()
    except (KeyError, UnicodeDecodeError):
        return ["checksums.sha256 is missing or invalid"]
    for line in lines:
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line)
        if not match:
            findings.append("invalid checksum record")
            continue
        expected, raw_name = match.groups()
        try:
            name = safe_member_name(raw_name.strip())
        except ValueError as exc:
            findings.append(str(exc))
            continue
        if name not in contents:
            findings.append(f"checksum target missing: {name}")
        elif sha256_bytes(contents[name]) != expected.lower():
            findings.append(f"checksum mismatch: {name}")
    return findings


def _verify_named_hash(contents: Mapping[str, bytes], target: str, hash_file: str) -> list[str]:
    try:
        record = contents[hash_file].decode("utf-8").strip()
        expected, name = record.split(None, 1)
    except (KeyError, UnicodeDecodeError, ValueError):
        return [f"invalid {hash_file}"]
    if name.strip().lstrip("*") != target or sha256_bytes(contents[target]) != expected.lower():
        return [f"{hash_file} mismatch"]
    return []


def _json_file(contents: Mapping[str, bytes], name: str) -> dict[str, Any]:
    return json.loads(contents[name].decode("utf-8"))


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(str(value), ensure_ascii=False)


def _probe_files(requirements: Mapping[str, str], status_labels: Mapping[str, str]) -> dict[str, str]:
    """Static package members. Kept as a function for reproducibility tests."""
    return {
        "README_RUN.md": _readme(),
        "EXACT_COMMANDS.md": _exact_commands(),
        "PROBE_CHECKLIST.md": _checklist(),
        "expected_evidence.json": canonical_json({
            "probe_id": PROBE_ID,
            "package_revision": 3,
            "required_directories": ["login_probe", "scheduler_probe", "siesta_discovery", "mpi_discovery", "slurm_accounting", "filesystem", "pseudo_verification", "stdout", "stderr"],
            "acceptance_requires_real_evidence": True,
            "terminal_state_requires_sacct_main_job_row": True,
            "empty_squeue_is_success": False,
            "scientific_calculation_performed": False,
        }),
        "run_login_probe.sh": _login_probe(),
        "prepare_scheduler_probe.py": _prepare_scheduler_probe(),
        "submit_environment_probe.slurm": _unprepared_slurm(),
        "inspect_probe_job.sh": _inspect_job(),
        "collect_probe_results.sh": _collect_results(),
        "verify_local_package.py": _verify_package(),
        "scripts/probe_common.sh": _probe_common(),
        "scripts/build_login_summary.py": _build_login_summary(),
        "scripts/scheduler_resolution.py": scheduler_resolution_source(),
        "scripts/verify_pseudos.py": _verify_pseudos_script(requirements, status_labels),
        "scripts/collect_bundle.py": _collect_bundle_script(),
        "scripts/validate_embedded_python.py": STANDALONE_VALIDATOR,
    }


def _readme() -> str:
    return """# M3 Yoltla environment probe — package revision V3

This is a non-scientific, human-operated environment characterization package.
It contains no FDF, geometry, pseudopotential, credential, or production command.
V3 supersedes V2 by supporting account-wide associations and evidence-bound
default-partition resolution. Use a clean V3 directory and never mix files
between revisions. Follow `EXACT_COMMANDS.md` exactly. Nothing transfers files
or submits a job automatically. The placeholder SLURM file exits until the V3
preparer creates and syntax-validates an evidence-backed script under `generated/`.
"""


def _exact_commands() -> str:
    return """# Exact commands for Yoltla — V3

Run after manually transferring and extracting this directory on Yoltla:

```bash
cd M3_YOLTLA_ENVIRONMENT_PROBE

python3 verify_local_package.py

chmod u+x \
  run_login_probe.sh \
  inspect_probe_job.sh \
  collect_probe_results.sh \
  scripts/*.sh \
  scripts/*.py

./run_login_probe.sh

python3 prepare_scheduler_probe.py \
  --login-evidence evidence/login_probe/summary.json \
  --output generated/submit_environment_probe.slurm

bash -n generated/submit_environment_probe.slurm

python3 scripts/validate_embedded_python.py \
  generated/submit_environment_probe.slurm

sed -n '1,240p' generated/submit_environment_probe.slurm
```

DETENERSE PARA INSPECCIÓN HUMANA

Only after human inspection, submit the non-scientific probe manually:

```bash
sbatch generated/submit_environment_probe.slurm \
  | tee evidence/scheduler_probe/sbatch_submission.txt

JOB_ID=$(awk '/Submitted batch job/{print $NF}' \
  evidence/scheduler_probe/sbatch_submission.txt)

./inspect_probe_job.sh "$JOB_ID"
```

Run `./inspect_probe_job.sh "$JOB_ID"` again after the job leaves `squeue`,
until terminal `sacct` evidence is present. Empty `squeue` is never success.
Then set the existing external pseudo directory and collect:

```bash
export PSEUDO_ROOT='/ruta/absoluta/a/psml/auditados'

./collect_probe_results.sh \
  --pseudo-root "$PSEUDO_ROOT"
```

Manually download the resulting `M3_YOLTLA_ENVIRONMENT_RESULTS_<timestamp>.tar.gz`
through the institutionally approved channel and attach it to Codex. Do not edit
scripts or YAML. Do not run any SIESTA input.
"""


def _checklist() -> str:
    return """# Probe checklist — V3

- [ ] A clean V3 directory was used; no earlier-revision files were mixed
- [ ] Account, partition, and QoS selection is supported by scheduler evidence
- [ ] Package hashes verified before execution
- [ ] Direct Python, Bash, SLURM, and embedded Python syntax verified
- [ ] Login probe completed without persistent environment changes
- [ ] Generated scheduler script inspected by a human
- [ ] Job used one node/task and no scientific input
- [ ] Job ID and submission stdout preserved
- [ ] `sacct` shows terminal State and ExitCode
- [ ] SIESTA discovery contains no FDF execution
- [ ] MPI launcher evidence captured
- [ ] Work/project/scratch visibility captured
- [ ] Every manifest-declared pseudopotential was read in place and hash checked
- [ ] Result bundle hashes verified locally before import
"""


def _probe_common() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
safe_head() { head -n "${2:-200}" "$1"; }
run_optional() {
  local out="$1"; shift
  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout "${PROBE_COMMAND_TIMEOUT_SECONDS:-20}" "$@" >"$out" 2>&1
  else
    "$@" >"$out" 2>&1
  fi
  local code=$?
  set -e
  printf '%s\n' "$code" >"${out}.exit_code"
  return 0
}
refuse_existing() { [[ ! -e "$1" ]] || { echo "REFUSING_OVERWRITE:$1" >&2; exit 2; }; }
"""


def _login_probe() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
source "$ROOT/scripts/probe_common.sh"
OUT="$ROOT/evidence/login_probe"
refuse_existing "$OUT"
mkdir -p "$OUT/raw" "$ROOT/evidence/stdout" "$ROOT/evidence/stderr"
LOG="$ROOT/evidence/stdout/login_probe.log"
ERR="$ROOT/evidence/stderr/login_probe.err"
exec > >(tee "$LOG") 2> >(tee "$ERR" >&2)
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/raw/observed_at.txt"
hostname >"$OUT/raw/hostname.txt"
id -un >"$OUT/raw/user.txt"
uname -srm >"$OUT/raw/system.txt"
printf '%s\n' "${SHELL:-unknown}" >"$OUT/raw/shell.txt"
ulimit -a >"$OUT/raw/ulimit.txt"
df -Pk "$ROOT" >"$OUT/raw/df_project.txt"
run_optional "$OUT/raw/quota.txt" quota -s
if type module >/dev/null 2>&1; then
  printf 'true\n' >"$OUT/raw/module_available.txt"
  module list >"$OUT/raw/module_list.txt" 2>&1 || true
  module spider siesta >"$OUT/raw/module_spider_siesta.txt" 2>&1 || true
  module avail siesta >"$OUT/raw/module_avail_siesta.txt" 2>&1 || true
  module -t avail siesta 2>&1 | grep -i 'siesta' | head -n 10 >"$OUT/raw/module_siesta_candidates.txt" || true
  while IFS= read -r candidate; do
    [[ "$candidate" =~ ^[A-Za-z0-9._/+:-]+$ ]] || continue
    module show "$candidate" >>"$OUT/raw/module_show_siesta.txt" 2>&1 || true
  done <"$OUT/raw/module_siesta_candidates.txt"
else
  printf 'false\n' >"$OUT/raw/module_available.txt"
fi
for cmd in sbatch squeue sinfo sacct scontrol sacctmgr srun mpirun mpiexec mpiexec.hydra siesta siesta-5.4.2; do
  command -v "$cmd" >"$OUT/raw/command_${cmd//./_}.txt" 2>/dev/null || true
done
run_optional "$OUT/raw/sinfo.txt" sinfo -h -o '%P|%a|%l|%D|%c|%m'
run_optional "$OUT/raw/squeue.txt" squeue -h -u "$(id -un)" -o '%i|%T|%P|%a|%q|%M|%N'
run_optional "$OUT/raw/sacct.txt" sacct -n -X -S now-1days -o JobID,State,ExitCode,Elapsed,Partition,Account,QOS
run_optional "$OUT/raw/scontrol_partitions.txt" scontrol show partition -o
run_optional "$OUT/raw/sacctmgr_assoc.txt" sacctmgr -n -P show assoc user="$(id -un)" format=Account,Partition,QOS
for cmd in srun mpirun mpiexec mpiexec.hydra; do
  if command -v "$cmd" >/dev/null 2>&1; then run_optional "$OUT/raw/${cmd//./_}_version.txt" "$cmd" --version; fi
done
env | grep -E '^(SLURM|MODULE|LMOD|PATH|SHELL|TMPDIR|SCRATCH|HOME|USER)=' | grep -Evi '(TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL|COOKIE)' | head -n 200 >"$OUT/raw/environment_redacted.txt" || true
python3 "$ROOT/scripts/build_login_summary.py" --raw "$OUT/raw" --output "$OUT/summary.json"
echo "LOGIN_PROBE_COMPLETE:$OUT"
"""


def _build_login_summary() -> str:
    return r'''#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from scheduler_resolution import model_dicts,parse_sacctmgr_associations,parse_scontrol_partitions,parse_sinfo_partitions
p=argparse.ArgumentParser(); p.add_argument('--raw',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
def read(name):
    q=a.raw/name
    return q.read_text(encoding='utf-8',errors='replace').strip() if q.is_file() else None
commands={}
for q in a.raw.glob('command_*.txt'):
    commands[q.stem.removeprefix('command_').replace('_','.')]=read(q.name) or None
environment={}
for line in (read('environment_redacted.txt') or '').splitlines():
    if '=' in line:
        k,v=line.split('=',1); environment[k]=v
observed=read('observed_at.txt')
associations,assoc_diagnostics=parse_sacctmgr_associations(read('sacctmgr_assoc.txt') or '',observed_at=observed)
visible,sinfo_diagnostics=parse_sinfo_partitions(read('sinfo.txt') or '')
policies,scontrol_diagnostics=parse_scontrol_partitions(read('scontrol_partitions.txt') or '')
module_text='\n'.join(filter(None,[read('module_spider_siesta.txt'),read('module_avail_siesta.txt'),read('module_show_siesta.txt')]))
import re
versions=sorted(set(re.findall(r'(?<!\d)(5\.\d+(?:\.\d+)?)(?!\d)',module_text)))
summary={'observed_at':observed,'hostname':read('hostname.txt'),'user':read('user.txt'),'system':read('system.txt'),'shell':read('shell.txt'),'module_available':read('module_available.txt')=='true','commands':commands,'environment':environment,'slurm_commands_available':all(commands.get(x) for x in ('sbatch','squeue','sinfo','sacct','scontrol')),'eligible_associations':model_dicts(associations),'visible_partitions':model_dicts(visible),'partition_policies':model_dicts(policies),'scheduler_diagnostics':assoc_diagnostics+sinfo_diagnostics+scontrol_diagnostics,'module_commands':[],'siesta_module_candidates':(read('module_siesta_candidates.txt') or '').splitlines()[:10],'siesta_version_candidates':versions,'siesta_discovery_status':'SIESTA_EXECUTABLE_DISCOVERED_VERSION_COMMAND_UNVERIFIED' if commands.get('siesta') or commands.get('siesta-5.4.2') else 'SIESTA_EXECUTABLE_NOT_DISCOVERED','scientific_calculation_performed':False}
a.output.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n',encoding='utf-8')
'''


def _prepare_scheduler_probe_legacy() -> str:
    return r"""#!/usr/bin/env python3
import argparse,json,os,re,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--login-evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
data=json.loads(a.login_evidence.read_text(encoding='utf-8'));candidates=data.get('eligible_associations',[])
unique={(x.get('account'),x.get('partition'),x.get('qos')) for x in candidates if x.get('account') and x.get('partition')}
if len(unique)!=1:raise SystemExit('SCHEDULER_PROBE_BLOCKED_NO_UNIQUE_EVIDENCE_BACKED_ASSOCIATION')
account,partition,qos=next(iter(unique));safe=re.compile(r'^[A-Za-z0-9._-]+$')
if not safe.fullmatch(account) or not safe.fullmatch(partition) or (qos and not safe.fullmatch(qos)):raise SystemExit('SCHEDULER_PROBE_BLOCKED_UNSAFE_ASSOCIATION_VALUE')
a.output.parent.mkdir(parents=True,exist_ok=True)
if a.output.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(a.output))
temporary=a.output.with_name(a.output.name+'.tmp')
if temporary.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(temporary))
qos_line=f'#SBATCH --qos={qos}\n' if qos else ''
script=f'''#!/usr/bin/env bash
# Values account/partition/QoS: OBSERVED in {a.login_evidence}
# Probe minima origin: M3R_NON_SCIENTIFIC_MINIMAL_RESOURCE_POLICY
#SBATCH --job-name=m3-yoltla-env
#SBATCH --partition={partition}
#SBATCH --account={account}
{qos_line}#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:02:00
#SBATCH --signal=B:USR1@60
#SBATCH --output=evidence/stdout/scheduler-%j.out
#SBATCH --error=evidence/stderr/scheduler-%j.err
set -euo pipefail
[[ -n "${{SLURM_SUBMIT_DIR:-}}" ]] || {{ echo SLURM_SUBMIT_DIR_NOT_SET >&2; exit 2; }}
[[ -d "$SLURM_SUBMIT_DIR" ]] || {{ echo "INVALID_SLURM_SUBMIT_DIR:$SLURM_SUBMIT_DIR" >&2; exit 2; }}
ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
[[ -f "$ROOT/probe_manifest.json" ]] || {{ echo "INVALID_SLURM_SUBMIT_DIR:$ROOT" >&2; exit 2; }}
OUT="$ROOT/evidence/scheduler_probe"
mkdir -p "$OUT" "$ROOT/evidence/stdout" "$ROOT/evidence/stderr"
[[ ! -e "$OUT/summary.json" ]] || {{ echo "REFUSING_OVERWRITE:$OUT/summary.json" >&2; exit 2; }}
trap 'date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/signal_received.txt"' USR1
env | grep '^SLURM_' | grep -Evi '(TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL|COOKIE)' | head -n 200 >"$OUT/slurm_environment.txt" || true
hostname >"$OUT/hostname.txt"
module list >"$OUT/module_list.txt" 2>&1 || true
for c in siesta siesta-5.4.2 srun mpirun mpiexec mpiexec.hydra; do command -v "$c" >>"$OUT/executables.txt" 2>/dev/null || true; done
for c in srun mpirun mpiexec mpiexec.hydra; do command -v "$c" >/dev/null 2>&1 && "$c" --version >>"$OUT/mpi_versions.txt" 2>&1 || true; done
df -Pk "$ROOT" >"$OUT/filesystem.txt"
kill -USR1 $$
python3 - "$OUT" <<'PY'
import json,os,sys,datetime,pathlib
o=pathlib.Path(sys.argv[1]); e=os.environ
d={{'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':e.get('SLURM_JOB_ID'),'partition':e.get('SLURM_JOB_PARTITION'),'account':e.get('SLURM_JOB_ACCOUNT'),'qos':e.get('SLURM_JOB_QOS'),'nodes':int(e.get('SLURM_NNODES','0')) or None,'ntasks':int(e.get('SLURM_NTASKS','0')) or None,'cpus_per_task':int(e.get('SLURM_CPUS_PER_TASK','0')) or None,'memory':None,'walltime':'00:02:00','signal':'B:USR1@60','signal_received':(o/'signal_received.txt').is_file(),'job_end_time':e.get('SLURM_JOB_END_TIME'),'scientific_calculation_performed':False}}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\\n',encoding='utf-8')
PY
echo NON_SCIENTIFIC_ENVIRONMENT_PROBE_COMPLETE
'''
temporary.write_text(script,encoding='utf-8',newline='\n')
validator=Path(__file__).resolve().parent/'scripts'/'validate_embedded_python.py'
checks=((['bash','-n',temporary.name],temporary.parent),([sys.executable,str(validator),str(temporary)],None))
for command,cwd in checks:
 result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,check=False)
 if result.returncode!=0:
  temporary.unlink(missing_ok=True)
  print(result.stdout,end='',file=sys.stderr);print(result.stderr,end='',file=sys.stderr)
  raise SystemExit('GENERATED_SCHEDULER_SCRIPT_INVALID')
os.replace(temporary,a.output);print(a.output)
"""


def _prepare_scheduler_probe() -> str:
    return r"""#!/usr/bin/env python3
import argparse,json,os,re,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'scripts'))
from scheduler_resolution import ResourceRequest,SchedulerAssociation,VisiblePartition,PartitionPolicy,apply_human_selection,resolve_scheduler_candidates
p=argparse.ArgumentParser();p.add_argument('--login-evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--account');p.add_argument('--partition');p.add_argument('--qos');a=p.parse_args()
data=json.loads(a.login_evidence.read_text(encoding='utf-8'))
associations=[SchedulerAssociation(**x) for x in data.get('eligible_associations',[])]
visible=[VisiblePartition(**x) for x in data.get('visible_partitions',[])]
policies=[PartitionPolicy(**x) for x in data.get('partition_policies',[])]
request=ResourceRequest();resolution=resolve_scheduler_candidates(associations,visible,policies,request)
manual=any(x is not None for x in (a.account,a.partition,a.qos))
if manual:
 if not a.account or not a.partition:raise SystemExit('USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE')
 try:resolution=apply_human_selection(resolution,a.account,a.partition,a.qos)
 except ValueError as exc:raise SystemExit(str(exc))
selected=resolution.get('selected')
if not selected:raise SystemExit(resolution['status'])
account,partition,qos=selected['account'],selected['partition'],selected.get('qos');safe=re.compile(r'^[A-Za-z0-9._-]+$')
if not safe.fullmatch(account) or not safe.fullmatch(partition) or (qos and not safe.fullmatch(qos)):raise SystemExit('SCHEDULER_PROBE_BLOCKED_UNSAFE_ASSOCIATION_VALUE')
a.output.parent.mkdir(parents=True,exist_ok=True)
if a.output.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(a.output))
selection_path=a.output.parent/'scheduler_selection.json'
if selection_path.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(selection_path))
qos_line=f'#SBATCH --qos={qos}\n' if qos else ''
script=f'''#!/usr/bin/env bash
# account: value origin = sacctmgr association; evidence status = OBSERVED
# partition: value origin = sinfo default marker + scontrol policy; evidence status = VERIFIED_BY_CROSS_SOURCE
# qos: value origin = sacctmgr association; evidence status = OBSERVED
# Probe minima origin: M3_NON_SCIENTIFIC_MINIMAL_RESOURCE_POLICY
#SBATCH --job-name=m3-environment-probe
#SBATCH --partition={partition}
#SBATCH --account={account}
{qos_line}#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:02:00
#SBATCH --signal=B:USR1@60
#SBATCH --output=evidence/stdout/scheduler-%j.out
#SBATCH --error=evidence/stderr/scheduler-%j.err
set -euo pipefail
[[ -n "${{SLURM_SUBMIT_DIR:-}}" ]] || {{ echo SLURM_SUBMIT_DIR_NOT_SET >&2; exit 2; }}
[[ -d "$SLURM_SUBMIT_DIR" ]] || {{ echo "INVALID_SLURM_SUBMIT_DIR:$SLURM_SUBMIT_DIR" >&2; exit 2; }}
ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)
[[ -f "$ROOT/probe_manifest.json" ]] || {{ echo "INVALID_SLURM_SUBMIT_DIR:$ROOT" >&2; exit 2; }}
OUT="$ROOT/evidence/scheduler_probe"
mkdir -p "$OUT" "$ROOT/evidence/stdout" "$ROOT/evidence/stderr"
[[ ! -e "$OUT/summary.json" ]] || {{ echo "REFUSING_OVERWRITE:$OUT/summary.json" >&2; exit 2; }}
trap 'date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/signal_received.txt"' USR1
env | grep '^SLURM_' | grep -Evi '(TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL|COOKIE)' | head -n 200 >"$OUT/slurm_environment.txt" || true
hostname >"$OUT/hostname.txt"
kill -USR1 $$
python3 - "$OUT" <<'PY'
import json,os,sys,datetime,pathlib
o=pathlib.Path(sys.argv[1]);e=os.environ
d={{'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':e.get('SLURM_JOB_ID'),'partition':e.get('SLURM_JOB_PARTITION'),'account':e.get('SLURM_JOB_ACCOUNT'),'qos':e.get('SLURM_JOB_QOS'),'nodes':int(e.get('SLURM_NNODES','0')) or None,'ntasks':int(e.get('SLURM_NTASKS','0')) or None,'cpus_per_task':int(e.get('SLURM_CPUS_PER_TASK','0')) or None,'memory':None,'walltime':'00:02:00','signal':'B:USR1@60','signal_received':(o/'signal_received.txt').is_file(),'job_end_time':e.get('SLURM_JOB_END_TIME'),'scientific_calculation_performed':False}}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\\n',encoding='utf-8')
PY
echo NON_SCIENTIFIC_ENVIRONMENT_PROBE_COMPLETE
'''
temporary=a.output.with_name(a.output.name+'.tmp');temporary.write_text(script,encoding='utf-8',newline='\n')
validator=Path(__file__).resolve().parent/'scripts'/'validate_embedded_python.py'
for command,cwd in ((['bash','-n',temporary.name],temporary.parent),([sys.executable,str(validator),str(temporary)],None)):
 result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,check=False)
 if result.returncode!=0:
  temporary.unlink(missing_ok=True);raise SystemExit('GENERATED_SCHEDULER_SCRIPT_INVALID:'+(result.stderr or result.stdout))
selection={'account':account,'partition':partition,'qos':qos,'nodes':request.nodes,'ntasks':request.ntasks,'cpus_per_task':request.cpus_per_task,'walltime':request.walltime,'association_scope':selected['association_scope'],'candidate_partitions':[x['partition'] for x in resolution['candidates']],'selection_policy':resolution['selection_policy'],'source_files':selected['source_files'],'evidence_status_by_field':{'account':'OBSERVED','partition':'VERIFIED_BY_CROSS_SOURCE','qos':'OBSERVED' if qos else 'MISSING'}}
selection_tmp=selection_path.with_name(selection_path.name+'.tmp');selection_tmp.write_text(json.dumps(selection,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
os.replace(temporary,a.output);os.replace(selection_tmp,selection_path);print(a.output);print(selection_path)
"""


def _unprepared_slurm() -> str:
    return """#!/usr/bin/env bash
#SBATCH --signal=B:USR1@60
set -euo pipefail
echo SCHEDULER_PROBE_NOT_PREPARED_USE_PREPARE_SCHEDULER_PROBE_PY >&2
exit 2
"""


def _inspect_job() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || { echo 'usage: inspect_probe_job.sh JOB_ID' >&2; exit 2; }
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
OUT="$ROOT/evidence/slurm_accounting"
mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
[[ ! -e "$OUT/squeue_${STAMP}.txt" && ! -e "$OUT/sacct_${STAMP}.txt" ]] || { echo REFUSING_TIMESTAMP_COLLISION >&2; exit 2; }
set +e
squeue -h -j "$1" -o '%i|%T|%P|%a|%q|%M|%N' >"$OUT/squeue_${STAMP}.txt" 2>"$OUT/squeue_${STAMP}.err"
SQUEUE_CODE=$?
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,AllocTRES,MaxRSS,NodeList,Partition,Account,QOS >"$OUT/sacct_${STAMP}.txt" 2>"$OUT/sacct_${STAMP}.err"
SACCT_CODE=$?
set -e
printf '%s\n' "$SQUEUE_CODE" >"$OUT/squeue_${STAMP}.exit_code"
printf '%s\n' "$SACCT_CODE" >"$OUT/sacct_${STAMP}.exit_code"
python3 - "$OUT" "$1" "$STAMP" "$SQUEUE_CODE" "$SACCT_CODE" <<'PY'
import json,pathlib,sys,datetime
o=pathlib.Path(sys.argv[1]);jid=sys.argv[2];stamp=sys.argv[3];sq_code=int(sys.argv[4]);sa_code=int(sys.argv[5])
sq=(o/f'squeue_{stamp}.txt').read_text(encoding='utf-8',errors='replace').strip()
lines=[x for x in (o/f'sacct_{stamp}.txt').read_text(encoding='utf-8',errors='replace').splitlines() if x.strip()]
rows=[line.split('|') for line in lines]
row=next((items for items in rows if items and items[0].strip()==jid),None)
values=(row or [])+['']*(10-len(row or []))
raw_state=values[1].strip() if row else ''
state=raw_state.split()[0].rstrip('+').upper() if raw_state else None
exit_code=(values[2].strip() or None) if row else None
terminal_states={'COMPLETED','FAILED','CANCELLED','TIMEOUT','NODE_FAIL','OUT_OF_MEMORY','PREEMPTED','BOOT_FAIL','DEADLINE'}
nonterminal_states={'PENDING','RUNNING','CONFIGURING','COMPLETING','SUSPENDED','RESIZING'}
terminal=state in terminal_states and bool(exit_code)
review=bool(state and not terminal and state not in nonterminal_states) or (bool(lines) and row is None)
d={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':jid,'squeue_present':bool(sq),'squeue_exit_code':sq_code,'sacct_command_exit_code':sa_code,'sacct_available':bool(lines) and sa_code==0,'main_job_row_found':row is not None,'terminal_evidence':terminal,'review_required':review,'state':state,'exit_code':exit_code,'elapsed':(values[3].strip() or None) if row else None,'alloc_tres':(values[4].strip() or None) if row else None,'max_rss':(values[5].strip() or None) if row else None,'node_list':(values[6].strip() or None) if row else None,'partition':(values[7].strip() or None) if row else None,'account':(values[8].strip() or None) if row else None,'qos':(values[9].strip() or None) if row else None}
target=o/'summary.json';temporary=o/f'summary_{stamp}.json.tmp'
temporary.write_text(json.dumps(d,sort_keys=True,indent=2)+'\\n',encoding='utf-8')
temporary.replace(target)
PY
echo "ACCOUNTING_EVIDENCE_CAPTURED:$OUT"
"""


def _verify_pseudos_script(requirements: Mapping[str, str], status_labels: Mapping[str, str]) -> str:
    encoded = json.dumps(dict(requirements), sort_keys=True, separators=(",", ":"))
    labels = json.dumps(dict(status_labels), sort_keys=True, separators=(",", ":"))
    return rf'''#!/usr/bin/env python3
import argparse,hashlib,json,stat
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
try:root=a.root.resolve(strict=True)
except OSError:root=a.root
expected=json.loads({encoded!r});labels=json.loads({labels!r});result={{'root':str(root),'observed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'entries':{{}}}};states=[]
for name,digest in expected.items():
 candidates=sorted(root.rglob(name))[:20] if root.is_dir() else []; q=candidates[0] if len(candidates)==1 else root/name
 item={{'filename':name,'candidate_count':len(candidates),'candidate_path':str(q) if len(candidates)==1 else None,'expected_sha256':digest,'exists':len(candidates)==1 and q.is_file() and not q.is_symlink(),'readable':False,'size':None,'sha256':None,'format':'UNKNOWN','format_valid':False,'verified':False,'error':'UNSAFE_SYMLINK' if len(candidates)==1 and q.is_symlink() else None}}
 if item['exists']:
  try:
   if not stat.S_IMODE(q.stat().st_mode)&0o444:raise PermissionError('no read permission bits')
   data=q.read_bytes();fmt=b'<psml' in data[:8192].lower();item.update(readable=True,size=len(data),sha256=hashlib.sha256(data).hexdigest(),format='PSML' if fmt else 'UNKNOWN',format_valid=fmt);item['verified']=item['sha256']==digest and len(data)>0 and fmt
  except OSError as exc:item['error']=type(exc).__name__
 state='VERIFIED' if item['verified'] else 'REVIEW' if len(candidates)>1 or item['error'] else 'MISMATCH' if item['exists'] else 'MISSING'
 result['entries'][name]=item;states.append(state)
result['status']=labels['verified'] if all(state=='VERIFIED' for state in states) else labels['mismatch'] if 'MISMATCH' in states else labels['review'] if 'REVIEW' in states else labels['missing']
if a.output.exists(): raise SystemExit('REFUSING_OVERWRITE:'+str(a.output))
a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n'); print(result['status'])
'''


def _collect_results() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
[[ $# -eq 2 && "$1" == '--pseudo-root' ]] || { echo 'usage: collect_probe_results.sh --pseudo-root ABSOLUTE_PATH' >&2; exit 2; }
[[ "$2" = /* && "$2" != *'/../'* && "$2" != */.. && "$2" != *'/./'* ]] || { echo PSEUDO_ROOT_MUST_BE_SAFE_ABSOLUTE_PATH >&2; exit 2; }
python3 "$ROOT/scripts/verify_pseudos.py" --root "$2" --output "$ROOT/evidence/pseudo_verification/summary.json"
python3 "$ROOT/scripts/collect_bundle.py" --package-root "$ROOT"
"""


def _collect_bundle_script() -> str:
    return r'''#!/usr/bin/env python3
import argparse,datetime,gzip,hashlib,json,os,re,shutil,tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--package-root',type=Path,required=True);p.add_argument('--timestamp');a=p.parse_args()
root=a.package_root.resolve();evidence=root/'evidence';stamp=a.timestamp or datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z',stamp):raise SystemExit('INVALID_TIMESTAMP')
required=['login_probe/summary.json','scheduler_probe/summary.json','slurm_accounting/summary.json','pseudo_verification/summary.json','stdout/login_probe.log','stderr/login_probe.err']
missing=[name for name in required if not (evidence/name).is_file()]
outs=sorted(evidence.glob('stdout/scheduler-*.out'));errs=sorted(evidence.glob('stderr/scheduler-*.err'))
if not outs:missing.append('stdout/scheduler-*.out')
if not errs:missing.append('stderr/scheduler-*.err')
if missing:raise SystemExit('MISSING_EVIDENCE:'+','.join(missing))
for path in evidence.rglob('*'):
 if path.is_symlink():raise SystemExit('UNSAFE_EVIDENCE_SYMLINK:'+str(path))
 try:path.resolve().relative_to(evidence.resolve())
 except ValueError:raise SystemExit('UNSAFE_EVIDENCE_PATH:'+str(path))
bundle=root/f'M3_YOLTLA_ENVIRONMENT_RESULTS_{stamp}.tar.gz';stage=root/f'.m3_collect_{stamp}'
if bundle.exists() or stage.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(bundle if bundle.exists() else stage))
for name in ['login_probe','scheduler_probe','slurm_accounting','pseudo_verification','stdout','stderr']:shutil.copytree(evidence/name,stage/name)
shutil.copy2(outs[-1],stage/'stdout/scheduler.out');shutil.copy2(errs[-1],stage/'stderr/scheduler.err')
for name in ['siesta_discovery','mpi_discovery','filesystem']:(stage/name).mkdir(parents=True)
login=json.loads((stage/'login_probe/summary.json').read_text(encoding='utf-8'));commands=login.get('commands',{});observed=login.get('observed_at')
write=lambda path,data:path.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
write(stage/'siesta_discovery/summary.json',{'observed_at':observed,'executable':commands.get('siesta') or commands.get('siesta-5.4.2'),'version':(login.get('siesta_version_candidates') or [None])[0],'version_evidence':'controlled module metadata' if login.get('siesta_version_candidates') else None,'status':login.get('siesta_discovery_status')})
launcher=next((x for x in ['mpiexec.hydra','srun','mpiexec','mpirun'] if commands.get(x)),None)
write(stage/'mpi_discovery/summary.json',{'observed_at':observed,'launcher':launcher,'launcher_command':commands.get(launcher) if launcher else None,'version':None})
env=login.get('environment',{});scratch=env.get('SCRATCH') or env.get('TMPDIR')
write(stage/'filesystem/summary.json',{'observed_at':observed,'project_root':str(root),'project_root_visible':root.is_dir(),'scratch_root':scratch,'scratch_writable':bool(scratch and Path(scratch).is_dir() and os.access(scratch,os.W_OK))})
write(stage/'results_manifest.json',{'probe_id':'M3_YOLTLA_ENVIRONMENT_PROBE','package_revision':3,'evidence_type':'REAL_REMOTE_ENVIRONMENT_PROBE','scientific_calculation_performed':False,'synthetic':False,'observed_at':observed})
h=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
(stage/'results_manifest.sha256').write_text(f"{h(stage/'results_manifest.json')}  results_manifest.json\n",encoding='utf-8',newline='\n')
files=sorted(path for path in stage.rglob('*') if path.is_file());(stage/'checksums.sha256').write_text(''.join(f'{h(path)}  {path.relative_to(stage).as_posix()}\n' for path in files),encoding='utf-8',newline='\n')
with bundle.open('xb') as raw:
 with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed:
  with tarfile.open(fileobj=compressed,mode='w',format=tarfile.PAX_FORMAT) as archive:
   for path in sorted(stage.rglob('*')):
    info=archive.gettarinfo(str(path),arcname=path.relative_to(stage).as_posix());info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
    if path.is_file():
     with path.open('rb') as stream:archive.addfile(info,stream)
    elif path.is_dir():archive.addfile(info)
shutil.rmtree(stage);print(bundle)
'''


def _verify_package() -> str:
    return r'''#!/usr/bin/env python3
import hashlib,json,os,re,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
required={'README_RUN.md','EXACT_COMMANDS.md','PROBE_CHECKLIST.md','expected_evidence.json','probe_manifest.json','probe_manifest.sha256','checksums.sha256','run_login_probe.sh','prepare_scheduler_probe.py','submit_environment_probe.slurm','inspect_probe_job.sh','collect_probe_results.sh','scripts/probe_common.sh','scripts/build_login_summary.py','scripts/scheduler_resolution.py','scripts/verify_pseudos.py','scripts/collect_bundle.py','scripts/validate_embedded_python.py'}
def fail(code,detail):raise SystemExit(f'{code}:{detail}')
for name in required:
 path=root/name
 if not path.is_file() or path.is_symlink() or not os.access(path,os.R_OK):fail('PACKAGE_STRUCTURE_FAILURE',name)
try:manifest=json.loads((root/'probe_manifest.json').read_text(encoding='utf-8'))
except (OSError,json.JSONDecodeError) as exc:fail('PROBE_MANIFEST_INVALID',str(exc))
if manifest.get('package_revision')!=3 or manifest.get('reproducibility_epoch')!='M3_STATIC_V3' or manifest.get('supersedes')!='M3_STATIC_V2':fail('PROBE_MANIFEST_REVISION_INVALID','expected V3')
record=(root/'probe_manifest.sha256').read_text(encoding='utf-8').strip().split(None,1)
if len(record)!=2 or record[1].lstrip('*')!='probe_manifest.json' or hashlib.sha256((root/'probe_manifest.json').read_bytes()).hexdigest()!=record[0]:fail('PROBE_MANIFEST_HASH_FAILURE','probe_manifest.json')
seen=set()
for number,line in enumerate((root/'checksums.sha256').read_text(encoding='utf-8').splitlines(),1):
 match=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not match:fail('PACKAGE_HASH_FAILURE',f'invalid record line {number}')
 digest,name=match.groups();parts=Path(name).parts
 if Path(name).is_absolute() or '..' in parts or name in seen:fail('PACKAGE_PATH_FAILURE',name)
 seen.add(name);path=root.joinpath(*parts)
 try:path.resolve().relative_to(root)
 except ValueError:fail('PACKAGE_PATH_FAILURE',name)
 if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:fail('PACKAGE_HASH_FAILURE',name)
actual={path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}-{'checksums.sha256'}
if seen!=actual:fail('PACKAGE_STRUCTURE_FAILURE','checksum coverage mismatch')
for name,digest in manifest.get('files',{}).items():
 path=root.joinpath(*Path(name).parts)
 if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:fail('PROBE_MANIFEST_FILE_HASH_FAILURE',name)
assignment=re.compile(r'(?im)^\s*(?:export\s+)?(?:PASSWORD|TOKEN|SECRET|AWS_SECRET_ACCESS_KEY|COOKIE|CREDENTIAL)\s*=\s*[^\s#][^\r\n]*$')
private_key=re.compile(r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----')
for path in root.rglob('*'):
 if path.is_symlink():fail('PACKAGE_PATH_FAILURE',str(path.relative_to(root)))
 if not path.is_file():continue
 if path.suffix.lower() in {'.fdf','.psml','.psf','.xyz'}:fail('FORBIDDEN_SCIENTIFIC_FILE',str(path.relative_to(root)))
 try:text=path.read_text(encoding='utf-8')
 except UnicodeDecodeError:continue
 for number,line in enumerate(text.splitlines(),1):
  if assignment.search(line) or private_key.search(line):fail('PACKAGE_SECRET_FAILURE',f'{path.relative_to(root)}:{number}')
python_files=sorted(str(path) for path in root.rglob('*.py'))
shell_paths=sorted((path for path in root.rglob('*') if path.suffix in {'.sh','.slurm'}),key=str)
with tempfile.TemporaryDirectory() as cache:
 env=dict(os.environ);env['PYTHONPYCACHEPREFIX']=cache
 result=subprocess.run([sys.executable,'-m','py_compile',*python_files],capture_output=True,text=True,env=env,check=False)
 if result.returncode:fail('DIRECT_PYTHON_SYNTAX_FAILURE',(result.stderr or result.stdout).strip())
for path in shell_paths:
 result=subprocess.run(['bash','-n',path.relative_to(root).as_posix()],cwd=root,capture_output=True,text=True,check=False)
 if result.returncode:fail('BASH_SYNTAX_FAILURE',f'{path}:{(result.stderr or result.stdout).strip()}')
result=subprocess.run([sys.executable,str(root/'scripts/validate_embedded_python.py'),*[str(path) for path in shell_paths]],capture_output=True,text=True,check=False)
if result.returncode:fail('EMBEDDED_PYTHON_SYNTAX_FAILURE',(result.stdout+result.stderr).strip())
print('M3_PACKAGE_HASHES_VERIFIED')
print('M3_PACKAGE_RUNTIME_SYNTAX_VERIFIED')
print('M3_PACKAGE_STRUCTURE_VERIFIED')
'''
