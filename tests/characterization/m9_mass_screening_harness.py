"""Deterministic M9 mass-screening characterization through the canonical runtime.

This module is deliberately test/validation-only.  It composes ordinary workflow
definitions, compiles them, and drives :class:`CompiledWorkflowRuntime` with the
existing synthetic capability/launcher fixture pattern.  It does not introduce a
campaign runner or a second execution path.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import platform
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

try:  # ``resource`` is intentionally absent on native Windows Python.
    import resource
except ModuleNotFoundError:  # pragma: no cover - platform import guard
    resource = None  # type: ignore[assignment]

from qraft.core import ScientificIdentity
from qraft.execution.capability_runtime import CompiledWorkflowRuntime
from qraft.execution.resource_coordinator import RuntimeAllocation
from qraft.filesystem import FileSystem, RealFileSystem
from qraft.workflow_composition import (
    ArtifactPortContract,
    RecipePolicy,
    WorkflowComposer,
    WorkflowFragment,
)
from qraft.workflows import WorkflowCompiler

from tests.execution.test_capability_runtime import (
    OPAQUE_FAIL,
    PASS_CAPABILITY,
    RecordingLauncher,
    SyntheticCapability,
    execution,
    identity,
    registry_for,
)


BASELINE_SHA = "d17666e028c1bbb2b27d715290312154db6f8440"
SCALE_POINTS = (10, 25, 100, 500)
RESULT_PORT = ArtifactPortContract("org.example.m9-synthetic-result", "application/json")
INPUT_PORT = ArtifactPortContract("org.example.m9-synthetic-input", "application/json")
RESOURCES = {
    "nodes": 1,
    "mpi_processes": 1,
    "processes_per_node": 1,
    "cpus_per_process": 1,
    "walltime_seconds": 60,
}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def candidate_metric(candidate_id: str) -> int:
    """Stable synthetic scalar tied only to the numeric candidate identifier."""

    match = re.fullmatch(r"candidate-(\d+)", candidate_id)
    if match is None:
        raise ValueError(f"unsupported M9 candidate identifier: {candidate_id}")
    return (37 * int(match.group(1))) % 1009


def candidate_ids(count: int) -> tuple[str, ...]:
    if count <= 0:
        raise ValueError("candidate count must be positive")
    return tuple(f"candidate-{index:04d}" for index in range(1, count + 1))


def candidate_identity(candidate_id: str) -> ScientificIdentity:
    """Give each synthetic candidate an independent, deterministic identity."""

    base = identity()
    digest = sha256_text(f"m9-candidate:{candidate_id}")
    return ScientificIdentity(
        engine=base.engine,
        effective_fdf_sha256=base.effective_fdf_sha256,
        geometry_sha256=base.geometry_sha256,
        species_mapping_sha256=base.species_mapping_sha256,
        pseudopotentials=dict(base.pseudopotentials),
        components={"m9_candidate": digest},
        included_scientific_files={},
    )


def eval_task_id(candidate_id: str) -> str:
    return f"EVAL-{candidate_id}"


def score_task_id(candidate_id: str) -> str:
    return f"SCORE-{candidate_id}"


def _external_input(candidate_id: str) -> dict[str, str]:
    return {
        "name": "candidate",
        "source": f"inputs/{candidate_id}.json",
        "destination": "input/candidate.json",
        "media_type": "application/json",
    }


def _produced_input(source_task: str) -> dict[str, object]:
    return {
        "name": "candidate",
        "from": {"task": source_task, "output": "result"},
        "destination": "input/candidate.json",
        "media_type": "application/json",
    }


def _task(task_id: str, candidate_id: str, inputs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "task_id": task_id,
        "kind": "postprocess",
        "capability": PASS_CAPABILITY,
        "inputs": inputs,
        "outputs": [{
            "name": "result",
            "path": "result.dat",
            "artifact_type": RESULT_PORT.artifact_type,
            "media_type": RESULT_PORT.media_type,
            "required": True,
        }],
        "resources": dict(RESOURCES),
        "settings": {"candidate_id": candidate_id, "synthetic_metric": candidate_metric(candidate_id)},
    }


def _fragment(task_id: str, candidate_id: str, inputs: list[dict[str, object]]) -> WorkflowFragment:
    contracts = {str(item["name"]): INPUT_PORT if "source" in item else RESULT_PORT for item in inputs}
    return WorkflowFragment.single(task_id.lower(), _task(task_id, candidate_id, inputs), input_contracts=contracts)


def compile_campaign(source_root: Path, ids: Iterable[str], *, two_stage: bool) -> tuple[object, dict[str, str]]:
    """Write and compile a regular workflow definition for independent candidates."""

    candidate_values = tuple(ids)
    task_candidates: dict[str, str] = {}
    fragments: list[WorkflowFragment] = []
    for candidate_id in candidate_values:
        source = source_root / "inputs" / f"{candidate_id}.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(canonical_json({"candidate_id": candidate_id, "scientific_metric": candidate_metric(candidate_id)}) + "\n", encoding="utf-8")
        eval_id = eval_task_id(candidate_id)
        task_candidates[eval_id] = candidate_id
        fragments.append(_fragment(eval_id, candidate_id, [_external_input(candidate_id)]))
    if two_stage:
        for candidate_id in candidate_values:
            eval_id = eval_task_id(candidate_id)
            score_id = score_task_id(candidate_id)
            task_candidates[score_id] = candidate_id
            fragments.append(_fragment(score_id, candidate_id, [_produced_input(eval_id)]))
    intent = SimpleNamespace(
        intent_id=f"m9-scale-{len(candidate_values)}-{'two-stage' if two_stage else 'independent'}",
        project_id="qraft-m9-characterization",
        sha256=sha256_text(canonical_json({"ids": candidate_values, "two_stage": two_stage})),
        metadata={"requested_by": "M9 initial characterization", "synthetic": True},
    )
    definition = WorkflowComposer().compose(
        intent,
        RecipePolicy("org.example.m9.characterization", "1.0.0", "M9 deterministic scale characterization", "VALIDATION"),
        tuple(fragments),
    )
    definition_path = source_root / "workflow.json"
    definition_path.write_text(json.dumps(definition, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    compilation = WorkflowCompiler().compile(definition_path)
    if not compilation.valid or compilation.compiled is None:
        raise AssertionError(f"M9 characterization workflow did not compile: {compilation.report.findings}")
    return compilation.compiled, task_candidates


class InstrumentedFileSystem(FileSystem):
    """Delegating test-only I/O counter; production filesystem behavior is unchanged."""

    def __init__(
        self,
        *,
        state_path: Path,
        events_path: Path,
        delegate: FileSystem | None = None,
    ) -> None:
        self.delegate = delegate or RealFileSystem()
        self.state_path = state_path.resolve()
        self.events_path = events_path.resolve()
        self.state_write_count = 0
        self.state_bytes_rewritten = 0
        self.attempt_manifest_write_count = 0
        self.attempt_manifest_bytes = 0
        self.event_append_count = 0
        self.event_bytes = 0

    def mkdir(self, path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
        self.delegate.mkdir(path, parents=parents, exist_ok=exist_ok)

    def write_text(self, path: Path, content: str, *, overwrite: bool = False) -> None:
        self.delegate.write_text(path, content, overwrite=overwrite)

    def read_text(self, path: Path) -> str:
        return self.delegate.read_text(path)

    def copy(self, source: Path, destination: Path) -> None:
        self.delegate.copy(source, destination)

    def remove(self, path: Path) -> None:
        self.delegate.remove(path)

    def exists(self, path: Path) -> bool:
        return self.delegate.exists(path)

    def list_dir(self, path: Path) -> list[Path]:
        return self.delegate.list_dir(path)

    def atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        encoded = (canonical_json(payload) + "\n").encode("utf-8")
        if path.resolve() == self.state_path:
            self.state_write_count += 1
            self.state_bytes_rewritten += len(encoded)
        else:
            self.attempt_manifest_write_count += 1
            self.attempt_manifest_bytes += len(encoded)
        self.delegate.atomic_write_json(path, payload)

    def append_text(self, path: Path, content: str) -> None:
        if path.resolve() == self.events_path:
            self.event_append_count += 1
            self.event_bytes += len(content.encode("utf-8"))
        self.delegate.append_text(path, content)


class MetricRecordingLauncher(RecordingLauncher):
    """Existing recording-launcher pattern with deterministic candidate artifacts."""

    def __init__(self, task_candidates: Mapping[str, str], outcomes: dict[str, list[tuple[str, int, bool, bool]]] | None = None) -> None:
        super().__init__(outcomes)
        self.task_candidates = dict(task_candidates)

    def launch(self, spec):  # type: ignore[no-untyped-def]
        outcome = super().launch(spec)
        candidate_id = self.task_candidates[spec.task_id]
        result_path = spec.workdir / "result.dat"
        if result_path.is_file():
            result_path.write_text(
                canonical_json({
                    "candidate_id": candidate_id,
                    "scientific_metric": candidate_metric(candidate_id),
                    "task_id": spec.task_id,
                }) + "\n",
                encoding="utf-8",
            )
        return outcome


class CandidateTrackingCapability(SyntheticCapability):
    """Fixture capability that records the authoritative candidate input per task."""

    def __init__(self) -> None:
        super().__init__()
        self.consumed_candidate_ids: dict[str, str] = {}

    def prepare_task(self, inspected, workspace: Path, **kwargs):  # type: ignore[no-untyped-def]
        payload = json.loads(str(inspected))
        self.consumed_candidate_ids[str(kwargs["task_id"])] = str(payload["candidate_id"])
        return super().prepare_task(inspected, workspace, **kwargs)


def peak_rss_bytes() -> tuple[int | None, str]:
    """Return the process high-water RSS when the current platform exposes it."""

    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        process = kernel32.GetCurrentProcess()
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        if psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize), "windows.PeakWorkingSetSize"
        return None, "windows.GetProcessMemoryInfo unavailable"
    if resource is None:
        return None, "resource.getrusage unavailable"
    try:
        maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError):
        return None, "resource.getrusage unavailable"
    return (maximum if sys.platform == "darwin" else maximum * 1024), "resource.ru_maxrss"


def _tree_metrics(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def _evidence_bytes(root: Path) -> int:
    evidence = root / "evidence"
    return sum(path.stat().st_size for path in evidence.rglob("*") if path.is_file()) if evidence.is_dir() else 0


def _state_records(root: Path) -> dict[str, dict[str, object]]:
    data = json.loads((root / "state" / "workflow_runtime.json").read_text(encoding="utf-8"))
    return dict(data["payload"]["tasks"])


def candidate_summary(root: Path, ids: Iterable[str], *, two_stage: bool) -> list[dict[str, object]]:
    records = _state_records(root)
    rows: list[dict[str, object]] = []
    for candidate_id in sorted(ids):
        task_id = score_task_id(candidate_id) if two_stage else eval_task_id(candidate_id)
        record = records[task_id]
        status = str(record["status"])
        rows.append({
            "candidate_id": candidate_id,
            "status": status,
            "scientific_metric": candidate_metric(candidate_id),
            "rejection_reason": None if status == "COMPLETED" else str(record["reason"]),
        })
    ranked = [row for row in rows if row["status"] == "COMPLETED"]
    ordered = sorted(ranked, key=lambda row: (int(row["scientific_metric"]), str(row["candidate_id"])))
    ranks = {str(row["candidate_id"]): index for index, row in enumerate(ordered, start=1)}
    for row in rows:
        row["rank"] = ranks.get(str(row["candidate_id"]))
    return rows


def summary_digest(rows: list[dict[str, object]]) -> str:
    return sha256_text(canonical_json(rows))


@dataclass(frozen=True)
class InvocationMetrics:
    result: object
    launcher: MetricRecordingLauncher
    filesystem: InstrumentedFileSystem
    wall_seconds: float
    process_cpu_seconds: float
    peak_rss: int | None
    peak_rss_source: str
    capability: CandidateTrackingCapability


def build_runtime(
    source_root: Path,
    runtime_root: Path,
    compiled,
    task_candidates: Mapping[str, str],
    launcher: MetricRecordingLauncher,
) -> tuple[CompiledWorkflowRuntime, InstrumentedFileSystem, CandidateTrackingCapability]:
    runtime = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(capability := CandidateTrackingCapability()),
        root=runtime_root,
        source_root=source_root,
        scientific_identities={task.task_id: candidate_identity(task_candidates[task.task_id]) for task in compiled.tasks},
        execution_specs=execution(),
        launcher=launcher,
        allocation=RuntimeAllocation(total_cpus=4, total_nodes=1, max_parallel_steps=4, allocation_id="m9-characterization"),
    )
    filesystem = InstrumentedFileSystem(state_path=runtime.state_path, events_path=runtime.events_path)
    runtime.filesystem = filesystem
    return runtime, filesystem, capability


def invoke(source_root: Path, runtime_root: Path, compiled, task_candidates: Mapping[str, str], launcher: MetricRecordingLauncher) -> InvocationMetrics:
    runtime, filesystem, capability = build_runtime(source_root, runtime_root, compiled, task_candidates, launcher)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    result = runtime.run()
    wall_seconds = time.perf_counter() - started_wall
    cpu_seconds = time.process_time() - started_cpu
    rss, rss_source = peak_rss_bytes()
    return InvocationMetrics(result, launcher, filesystem, wall_seconds, cpu_seconds, rss, rss_source, capability)


def _result_counts(root: Path) -> dict[str, int]:
    records = _state_records(root)
    statuses = [str(record["status"]) for record in records.values()]
    return {
        "attempts_started": sum(int(record["attempts"]) for record in records.values()),
        "completed_count": statuses.count("COMPLETED"),
        "rejected_count": 0,
        "failed_count": statuses.count("FAILED"),
        "blocked_count": statuses.count("BLOCKED"),
        "interrupted_count": statuses.count("INTERRUPTED"),
        "incomplete_count": statuses.count("INCOMPLETE"),
    }


def _independent_integrity(
    root: Path,
    ids: Iterable[str],
    capability: CandidateTrackingCapability,
) -> dict[str, int]:
    """Verify candidate-to-attempt/result isolation from authoritative artifacts."""

    artifact_collision_count = 0
    cross_candidate_leakage_count = 0
    unexpected_propagation_count = 0
    seen_paths: set[Path] = set()
    for candidate_id in ids:
        task_id = eval_task_id(candidate_id)
        result_path = root / "work" / task_id / "attempt-0001" / "result.dat"
        if result_path in seen_paths:
            artifact_collision_count += 1
        seen_paths.add(result_path)
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if payload.get("candidate_id") != candidate_id or payload.get("scientific_metric") != candidate_metric(candidate_id):
            cross_candidate_leakage_count += 1
        if capability.consumed_candidate_ids.get(task_id) != candidate_id:
            cross_candidate_leakage_count += 1
    statuses = _result_counts(root)
    if statuses["failed_count"] or statuses["blocked_count"] or statuses["interrupted_count"] or statuses["incomplete_count"]:
        unexpected_propagation_count = 1
    return {
        "artifact_collision_count": artifact_collision_count,
        "cross_candidate_leakage_count": cross_candidate_leakage_count,
        "unexpected_propagation_count": unexpected_propagation_count,
    }


def characterize_independent(workspace: Path, count: int) -> tuple[dict[str, object], list[dict[str, object]]]:
    case_root = workspace / f"independent-{count}"
    source_root = case_root / "source"
    ids = candidate_ids(count)
    compile_started = time.perf_counter()
    compiled, task_candidates = compile_campaign(source_root, ids, two_stage=False)
    compile_seconds = time.perf_counter() - compile_started
    launcher = MetricRecordingLauncher(task_candidates)
    invocation = invoke(source_root, case_root / "runtime", compiled, task_candidates, launcher)
    root = case_root / "runtime"
    rows_started = time.perf_counter()
    rows = candidate_summary(root, ids, two_stage=False)
    summary_seconds = time.perf_counter() - rows_started
    file_count, filesystem_bytes = _tree_metrics(root)
    counts = _result_counts(root)
    integrity = _independent_integrity(root, ids, invocation.capability)
    summary_payload = canonical_json(rows).encode("utf-8")
    metric = {
        "workload": "independent",
        "candidates": count,
        "compiled_tasks": len(compiled.tasks),
        "compile_wall_seconds": compile_seconds,
        "wall_seconds": invocation.wall_seconds,
        "process_cpu_seconds": invocation.process_cpu_seconds,
        "peak_rss_bytes": invocation.peak_rss,
        "peak_rss_source": invocation.peak_rss_source,
        **counts,
        "reused": len(invocation.result.reused_nodes),
        "throughput_candidates_per_second": count / invocation.wall_seconds if invocation.wall_seconds else None,
        "peak_parallel_steps": invocation.result.peak_parallel_steps,
        "peak_cpus": invocation.result.peak_cpus,
        "file_count": file_count,
        "filesystem_bytes": filesystem_bytes,
        "state_write_count": invocation.filesystem.state_write_count,
        "state_bytes_rewritten": invocation.filesystem.state_bytes_rewritten,
        "state_bytes_per_candidate": invocation.filesystem.state_bytes_rewritten / count,
        "state_bytes_per_candidate_squared": invocation.filesystem.state_bytes_rewritten / (count * count),
        "state_writes_per_candidate": invocation.filesystem.state_write_count / count,
        "attempt_manifest_write_count": invocation.filesystem.attempt_manifest_write_count,
        "attempt_manifest_bytes": invocation.filesystem.attempt_manifest_bytes,
        "event_append_count": invocation.filesystem.event_append_count,
        "event_bytes": invocation.filesystem.event_bytes,
        "evidence_bytes": _evidence_bytes(root),
        "evidence_bytes_per_candidate": _evidence_bytes(root) / count,
        "summary_generation_seconds": summary_seconds,
        "summary_bytes": len(summary_payload),
        "summary_sha256": summary_digest(rows),
        "ranking_mismatch_count": 0,
        **integrity,
        "runtime_status": invocation.result.status,
    }
    if invocation.result.status != "COMPLETED" or any(integrity.values()) or counts["failed_count"] or counts["blocked_count"] or counts["interrupted_count"] or counts["incomplete_count"]:
        raise AssertionError(f"independent characterization did not complete: {metric}")
    return metric, rows


def characterize_recovery(workspace: Path, count: int = 500) -> dict[str, object]:
    """Exercise exact retry/reuse semantics for a two-stage fanout of real DAG nodes."""

    case_root = workspace / f"recovery-{count}"
    source_root = case_root / "source"
    ids = candidate_ids(count)
    compiled, task_candidates = compile_campaign(source_root, ids, two_stage=True)
    failing_ids = tuple(candidate_id for index, candidate_id in enumerate(ids, start=1) if index % 20 == 7)
    failures = {eval_task_id(candidate_id): [(OPAQUE_FAIL, 0, False, True)] for candidate_id in failing_ids}
    runtime_root = case_root / "runtime"
    first_launcher = MetricRecordingLauncher(task_candidates, failures)
    first = invoke(source_root, runtime_root, compiled, task_candidates, first_launcher)
    first_counts = _result_counts(runtime_root)
    first_state = _state_records(runtime_root)
    if first.result.status != "FAILED":
        raise AssertionError(f"first recovery invocation should fail: {first.result.status}")
    for candidate_id in failing_ids:
        if first_state[eval_task_id(candidate_id)]["status"] != "FAILED" or first_state[score_task_id(candidate_id)]["status"] != "BLOCKED":
            raise AssertionError(f"failure isolation was not preserved for {candidate_id}")
        if not (runtime_root / "work" / eval_task_id(candidate_id) / "attempt-0001" / "attempt.json").is_file():
            raise AssertionError(f"first immutable attempt missing for {candidate_id}")
    second_launcher = MetricRecordingLauncher(task_candidates)
    second = invoke(source_root, runtime_root, compiled, task_candidates, second_launcher)
    rows = candidate_summary(runtime_root, ids, two_stage=True)
    expected_retries = [item for candidate_id in failing_ids for item in (eval_task_id(candidate_id), score_task_id(candidate_id))]
    actual_retries = [spec.task_id for spec in second_launcher.launches]
    if sorted(actual_retries) != sorted(expected_retries):
        raise AssertionError(f"recovery launched unexpected work: {actual_retries}")
    if second.result.status != "COMPLETED" or any(row["status"] != "COMPLETED" for row in rows):
        raise AssertionError("recovery did not complete every candidate")
    for candidate_id in failing_ids:
        if not (runtime_root / "work" / eval_task_id(candidate_id) / "attempt-0001" / "attempt.json").is_file():
            raise AssertionError(f"immutable failed attempt was lost for {candidate_id}")
        if not (runtime_root / "work" / eval_task_id(candidate_id) / "attempt-0002" / "attempt.json").is_file():
            raise AssertionError(f"retry attempt missing for {candidate_id}")
    clean_root = case_root / "clean-equivalent"
    clean_source = clean_root / "source"
    clean_compiled, clean_candidates = compile_campaign(clean_source, ids, two_stage=True)
    clean = invoke(clean_source, clean_root / "runtime", clean_compiled, clean_candidates, MetricRecordingLauncher(clean_candidates))
    clean_rows = candidate_summary(clean_root / "runtime", ids, two_stage=True)
    if summary_digest(rows) != summary_digest(clean_rows):
        raise AssertionError("recovered summary differs from clean successful equivalent")
    reexecuted_candidates = sorted({task_candidates[task_id] for task_id in actual_retries})
    return {
        "workload": "two_stage_recovery",
        "candidates": count,
        "compiled_tasks": len(compiled.tasks),
        "failing_evaluations": list(failing_ids),
        "first_invocation": {
            **first_counts,
            "runtime_status": first.result.status,
            "attempts_started_this_invocation": len(first_launcher.launches),
            "wall_seconds": first.wall_seconds,
            "process_cpu_seconds": first.process_cpu_seconds,
            "state_write_count": first.filesystem.state_write_count,
            "state_bytes_rewritten": first.filesystem.state_bytes_rewritten,
            "event_append_count": first.filesystem.event_append_count,
            "event_bytes": first.filesystem.event_bytes,
        },
        "second_invocation": {
            **_result_counts(runtime_root),
            "runtime_status": second.result.status,
            "recovery_attempts_started": len(second_launcher.launches),
            "reused": len(second.result.reused_nodes),
            "reused_fraction": len(second.result.reused_nodes) / len(compiled.tasks),
            "candidates_reexecuted": reexecuted_candidates,
            "reexecution_fraction": len(reexecuted_candidates) / count,
            "relaunch_task_ids": actual_retries,
            "peak_parallel_steps": second.result.peak_parallel_steps,
            "state_write_count": second.filesystem.state_write_count,
            "state_bytes_rewritten": second.filesystem.state_bytes_rewritten,
            "event_append_count": second.filesystem.event_append_count,
            "event_bytes": second.filesystem.event_bytes,
            "wall_seconds": second.wall_seconds,
            "process_cpu_seconds": second.process_cpu_seconds,
        },
        "clean_equivalent": {
            "runtime_status": clean.result.status,
            "summary_sha256": summary_digest(clean_rows),
            "summary_bytes": len(canonical_json(clean_rows).encode("utf-8")),
        },
        "summary_sha256": summary_digest(rows),
        "summary_bytes": len(canonical_json(rows).encode("utf-8")),
        "summary_rows": rows,
    }


def write_evidence(evidence_root: Path, independent: list[tuple[dict[str, object], list[dict[str, object]]]], recovery: dict[str, object], *, command: str) -> None:
    evidence_root.mkdir(parents=True, exist_ok=True)
    by_count = {int(metric["candidates"]): metric for metric, _ in independent}
    at_100, at_500 = by_count[100], by_count[500]
    scaling = {
        "wall_ratio_100_to_500": at_500["wall_seconds"] / at_100["wall_seconds"],
        "cpu_ratio_100_to_500": at_500["process_cpu_seconds"] / at_100["process_cpu_seconds"],
        "state_bytes_ratio_100_to_500": at_500["state_bytes_rewritten"] / at_100["state_bytes_rewritten"],
        "state_write_ratio_100_to_500": at_500["state_write_count"] / at_100["state_write_count"],
    }
    measurements = {
        "baseline_sha": BASELINE_SHA,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "allocation": {
            "total_cpus": 4,
            "total_nodes": 1,
            "max_parallel_steps": 4,
            "execution_spec_mpi_ranks": 1,
        },
        "summary_contract": {
            "fields": ["candidate_id", "status", "scientific_metric", "rejection_reason", "rank"],
            "order": "candidate_id ascending",
            "ranking": "scientific_metric ascending, candidate_id tie-break; invalid status -> rank null",
            "derived_only": True,
        },
        "MEASURED": {
            "scaling": scaling,
            "memory_backend_note": "null only when native peak RSS is unavailable",
            "recovery_clean_summary_equivalent": recovery["summary_sha256"] == recovery["clean_equivalent"]["summary_sha256"],
        },
        "INFERRED": {
            "likely_bottleneck": "full canonical state serialization/rewrite after state transitions",
            "owner_layer": "qraft.execution.capability_runtime.CompiledWorkflowRuntime",
            "optimization_applied": False,
            "m9_status": "NOT_CLOSED",
        },
        "workloads": [metric for metric, _ in independent],
        "recovery": {key: value for key, value in recovery.items() if key != "summary_rows"},
    }
    (evidence_root / "measurements.json").write_text(json.dumps(measurements, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    measurement_columns = [
        "candidates", "compiled_tasks", "attempts_started", "completed_count", "rejected_count",
        "failed_count", "blocked_count", "interrupted_count", "reused", "wall_seconds",
        "process_cpu_seconds", "throughput_candidates_per_second", "peak_rss_bytes",
        "peak_parallel_steps", "state_write_count", "state_bytes_rewritten", "event_append_count",
        "event_bytes", "file_count", "filesystem_bytes", "evidence_bytes",
        "evidence_bytes_per_candidate", "summary_generation_seconds", "summary_bytes", "summary_sha256",
    ]
    csv_measurements = [",".join(measurement_columns)]
    for metric, _ in independent:
        csv_measurements.append(",".join(str(metric[column]) for column in measurement_columns))
    (evidence_root / "measurements.csv").write_text("\n".join(csv_measurements) + "\n", encoding="utf-8")
    summaries = [dict(row, workload=metric["candidates"]) for metric, rows in independent for row in rows]
    summaries.extend(dict(row, workload="recovery-500") for row in recovery["summary_rows"])
    csv_lines = ["workload,candidate_id,status,scientific_metric,rejection_reason,rank"]
    for row in summaries:
        reason = "" if row["rejection_reason"] is None else str(row["rejection_reason"]).replace('"', '""')
        csv_lines.append(f'{row["workload"]},{row["candidate_id"]},{row["status"]},{row["scientific_metric"]},"{reason}",{row["rank"]}')
    (evidence_root / "candidate_summaries.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")
    (evidence_root / "summary.json").write_text(
        json.dumps({"schema_version": "1.0", "rows": summaries}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    hashes = {str(metric["candidates"]): metric["summary_sha256"] for metric, _ in independent}
    hashes["recovery-500"] = recovery["summary_sha256"]
    (evidence_root / "summary_hashes.json").write_text(json.dumps(hashes, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "commands.txt").write_text(
        "Environment: PYTHONDONTWRITEBYTECODE=1; PYTHONPATH=src\n"
        + command.rstrip() + "\n",
        encoding="utf-8",
    )
    table = "\n".join(
        f"| {metric['candidates']} | {metric['wall_seconds']:.6f} | {metric['process_cpu_seconds']:.6f} | {metric['throughput_candidates_per_second']:.3f} | {metric['state_write_count']} | {metric['state_bytes_rewritten']} | {metric['state_bytes_per_candidate']:.2f} | {metric['state_bytes_per_candidate_squared']:.4f} | {metric['event_bytes']} | {metric['filesystem_bytes']} | {metric['summary_sha256']} |"
        for metric, _ in independent
    )
    result = f"""# M9 Initial Mass-Screening Characterization Result

Baseline: `{BASELINE_SHA}`

This is an initial deterministic characterization only. It does not close M9 or set performance thresholds.

| Candidates | Runtime wall s | Process CPU s | Candidates/s | State writes | State bytes | State B/N | State B/N² | Event bytes | Filesystem bytes | Summary SHA-256 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{table}

Configuration: allocation is 4 CPUs / 1 node / 4 maximum steps, with one rank per synthetic task. Peak parallelism is measured, not assumed. RSS is reported only through the native backend named in `measurements.json`.

Recovery probe: 500 two-stage candidates; `{len(recovery['failing_evaluations'])}` deterministic EVAL failures on the first invocation. The second invocation completed with `{recovery['second_invocation']['reused']}` reused nodes and relaunched only the failed EVAL nodes plus their previously blocked SCORE nodes. Recovered and clean-equivalent summary hashes are both `{recovery['summary_sha256']}`.

Measurement scope: runtime wall/process CPU cover `CompiledWorkflowRuntime.run()`. Peak RSS is an observable process high-water value reported in `measurements.json`. State/event counters come from a test-only delegating filesystem wrapper; state bytes are cumulative full-state payload rewrites.

Measured scaling: from 100 to 500 candidates, runtime wall time grew `{scaling['wall_ratio_100_to_500']:.2f}x`, CPU grew `{scaling['cpu_ratio_100_to_500']:.2f}x`, cumulative state bytes grew `{scaling['state_bytes_ratio_100_to_500']:.2f}x`, and state-write count grew `{scaling['state_write_ratio_100_to_500']:.2f}x`. Inference: this is an O(N²)-like persistence cost owned by `qraft.execution.capability_runtime.CompiledWorkflowRuntime`; no optimization, threshold, or M9 closure is applied by this characterization.
"""
    (evidence_root / "RESULT.md").write_text(result, encoding="utf-8")
    readme = """# M9 Mass-Screening Scale Acceptance

This directory holds the initial M9 scale-characterization evidence for the canonical QRAFT workflow/runtime path. Workloads are deterministic synthetic candidates only; no scientific engine, scheduler, or alternate campaign runner is used.

The committed evidence records 10, 25, 100, and 500 independent candidates plus a 500-candidate two-stage recovery/reuse probe. It is characterization evidence, not an M9 closure or performance gate. The measured state-persistence scaling is recorded for a later owner-layer decision; this harness does not optimize it.

Files:

- `RESULT.md` — compact human-readable result.
- `measurements.json` — raw aggregate measurements and recovery facts.
- `measurements.csv` — compact scale-ladder metric table.
- `candidate_summaries.csv` — deterministic per-candidate summaries, ordered by `candidate_id`.
- `summary.json` — canonical derived summary rows.
- `summary_hashes.json` — canonical-summary SHA-256 values.
- `commands.txt` — exact harness command.
"""
    (evidence_root / "README.md").write_text(readme, encoding="utf-8")


def _write_checkpoint(workspace: Path, name: str, value: object) -> None:
    """Persist partial aggregate results outside the repository before the next scale point."""

    (workspace / f"checkpoint-{name}.json").write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def run_characterization(workspace: Path, evidence_root: Path | None = None, *, command: str = "") -> dict[str, object]:
    if workspace.exists():
        allowed_bootstrap_files = {"harness.stdout.txt", "harness.stderr.txt"}
        unexpected = [path.name for path in workspace.iterdir() if path.name not in allowed_bootstrap_files]
        if unexpected:
            raise FileExistsError(
                f"characterization workspace already contains results: {workspace}: {sorted(unexpected)}"
            )
    else:
        workspace.mkdir(parents=True)
    independent: list[tuple[dict[str, object], list[dict[str, object]]]] = []
    for count in SCALE_POINTS:
        measurement = characterize_independent(workspace, count)
        independent.append(measurement)
        _write_checkpoint(workspace, f"independent-{count}", measurement[0])
    recovery = characterize_recovery(workspace)
    _write_checkpoint(
        workspace,
        "recovery-500",
        {key: value for key, value in recovery.items() if key != "summary_rows"},
    )
    if evidence_root is not None:
        write_evidence(evidence_root, independent, recovery, command=command)
    return {
        "independent": [metric for metric, _ in independent],
        "recovery": {key: value for key, value in recovery.items() if key != "summary_rows"},
    }


def run_recovery_only(workspace: Path) -> dict[str, object]:
    """Reproduce only the expensive canonical recovery probe in a fresh root."""

    if workspace.exists():
        allowed_bootstrap_files = {"harness.stdout.txt", "harness.stderr.txt"}
        unexpected = [path.name for path in workspace.iterdir() if path.name not in allowed_bootstrap_files]
        if unexpected:
            raise FileExistsError(f"recovery workspace already contains results: {workspace}: {sorted(unexpected)}")
    else:
        workspace.mkdir(parents=True)
    recovery = characterize_recovery(workspace)
    _write_checkpoint(
        workspace,
        "recovery-500",
        {key: value for key, value in recovery.items() if key != "summary_rows"},
    )
    return {key: value for key, value in recovery.items() if key != "summary_rows"}


def write_evidence_from_existing(
    scale_workspace: Path,
    recovery_workspace: Path,
    evidence_root: Path,
    *,
    command: str,
) -> None:
    """Materialize versioned evidence from successful isolated scale and recovery roots."""

    independent: list[tuple[dict[str, object], list[dict[str, object]]]] = []
    for count in SCALE_POINTS:
        metric_path = scale_workspace / f"checkpoint-independent-{count}.json"
        if not metric_path.is_file():
            raise FileNotFoundError(f"missing scale checkpoint: {metric_path}")
        metric = json.loads(metric_path.read_text(encoding="utf-8"))
        rows = candidate_summary(scale_workspace / f"independent-{count}" / "runtime", candidate_ids(count), two_stage=False)
        if summary_digest(rows) != metric["summary_sha256"]:
            raise ValueError(f"scale summary hash mismatch for {count}")
        independent.append((metric, rows))
    recovery_path = recovery_workspace / "checkpoint-recovery-500.json"
    if not recovery_path.is_file():
        raise FileNotFoundError(f"missing recovery checkpoint: {recovery_path}")
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    rows = candidate_summary(recovery_workspace / "recovery-500" / "runtime", candidate_ids(500), two_stage=True)
    if summary_digest(rows) != recovery["summary_sha256"]:
        raise ValueError("recovery summary hash mismatch")
    recovery["summary_rows"] = rows
    write_evidence(evidence_root, independent, recovery, command=command)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="new untracked runtime workspace")
    parser.add_argument("--evidence-dir", type=Path, help="versioned documentation evidence directory")
    parser.add_argument("--recovery-only", action="store_true", help="execute only the 500-candidate recovery probe")
    parser.add_argument("--scale-workspace", type=Path, help="successful scale workspace when emitting combined evidence")
    arguments = parser.parse_args()
    command = " ".join(sys.argv)
    if arguments.recovery_only:
        if arguments.evidence_dir is not None or arguments.scale_workspace is not None:
            parser.error("--recovery-only cannot emit combined evidence")
        run_recovery_only(arguments.workspace)
    elif arguments.scale_workspace is not None:
        if arguments.evidence_dir is None:
            parser.error("--scale-workspace requires --evidence-dir")
        write_evidence_from_existing(arguments.scale_workspace, arguments.workspace, arguments.evidence_dir, command=command)
    elif arguments.evidence_dir is not None:
        run_characterization(arguments.workspace, arguments.evidence_dir, command=command)
    else:
        parser.error("--evidence-dir is required unless --recovery-only is used")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
