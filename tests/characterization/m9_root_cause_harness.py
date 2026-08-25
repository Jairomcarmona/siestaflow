"""M9-R1 persistence/concurrency characterization on the canonical runtime.

This is validation-only instrumentation.  It creates ordinary compiled workflow
nodes and executes them with the existing synthetic capability/launcher fixture;
it does not alter QRAFT's production persistence, scheduler, or allocation code.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qraft.core import ExecutionSpec
from qraft.execution.capability_runtime import CompiledWorkflowRuntime
from qraft.execution.resource_coordinator import RuntimeAllocation
from qraft.filesystem import FileSystem, RealFileSystem

from tests.characterization.m9_mass_screening_harness import (
    BASELINE_SHA,
    CandidateTrackingCapability,
    MetricRecordingLauncher,
    _evidence_bytes,
    _result_counts,
    _tree_metrics,
    candidate_ids,
    candidate_identity,
    candidate_summary,
    compile_campaign,
    peak_rss_bytes,
    registry_for,
    summary_digest,
)


MATRIX = ((25, 1), (25, 4), (100, 1), (100, 4))
CPUS_PER_TASK = 4
LAUNCH_DELAY_SECONDS = 0.02


@dataclass
class TimedFilesystem(FileSystem):
    """Delegating I/O observer; it never changes persistence behavior or retries."""

    state_path: Path
    events_path: Path
    journal_path: Path
    delegate: FileSystem = field(default_factory=RealFileSystem)
    state_write_count: int = 0
    state_bytes_rewritten: int = 0
    state_atomic_seconds: float = 0.0
    state_atomic_failures: int = 0
    state_atomic_winerror_5: int = 0
    peak_concurrent_state_writes: int = 0
    attempt_manifest_write_count: int = 0
    attempt_manifest_bytes: int = 0
    atomic_failures: int = 0
    atomic_winerror_5: int = 0
    event_append_count: int = 0
    event_bytes: int = 0
    event_append_seconds: float = 0.0
    journal_append_count: int = 0
    journal_bytes: int = 0
    journal_append_seconds: float = 0.0

    def __post_init__(self) -> None:
        self.state_path = self.state_path.resolve()
        self.events_path = self.events_path.resolve()
        self.journal_path = self.journal_path.resolve()
        self._lock = threading.Lock()
        self._active_state_writes = 0

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
        encoded_bytes = len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")) + 1
        is_state = path.resolve() == self.state_path
        with self._lock:
            if is_state:
                self.state_write_count += 1
                self.state_bytes_rewritten += encoded_bytes
                self._active_state_writes += 1
                self.peak_concurrent_state_writes = max(
                    self.peak_concurrent_state_writes, self._active_state_writes
                )
            else:
                self.attempt_manifest_write_count += 1
                self.attempt_manifest_bytes += encoded_bytes
        started = time.perf_counter()
        try:
            self.delegate.atomic_write_json(path, payload)
        except OSError as exc:
            with self._lock:
                self.atomic_failures += 1
                if is_state:
                    self.state_atomic_failures += 1
                if getattr(exc, "winerror", None) == 5:
                    self.atomic_winerror_5 += 1
                    if is_state:
                        self.state_atomic_winerror_5 += 1
            raise
        finally:
            elapsed = time.perf_counter() - started
            with self._lock:
                if is_state:
                    self.state_atomic_seconds += elapsed
                    self._active_state_writes -= 1

    def append_text(self, path: Path, content: str) -> None:
        is_event = path.resolve() == self.events_path
        is_journal = path.resolve() == self.journal_path
        if is_event:
            with self._lock:
                self.event_append_count += 1
                self.event_bytes += len(content.encode("utf-8"))
        if is_journal:
            with self._lock:
                self.journal_append_count += 1
                self.journal_bytes += len(content.encode("utf-8"))
        started = time.perf_counter()
        self.delegate.append_text(path, content)
        if is_event:
            with self._lock:
                self.event_append_seconds += time.perf_counter() - started
        if is_journal:
            with self._lock:
                self.journal_append_seconds += time.perf_counter() - started


class DelayedMetricRecordingLauncher(MetricRecordingLauncher):
    """Existing recording launcher plus constant delay to expose concurrent leases."""

    def __init__(
        self,
        task_candidates: dict[str, str],
        *,
        delay_seconds: float,
        expected_parallelism: int,
    ) -> None:
        super().__init__(task_candidates)
        self.delay_seconds = delay_seconds
        self.expected_parallelism = expected_parallelism
        self._lock = threading.Lock()
        self._active = 0
        self._launch_number = 0
        self._first_parallel_group = (
            threading.Barrier(expected_parallelism)
            if expected_parallelism > 1
            else None
        )
        self.peak_active_launches = 0
        self.launch_spans: list[dict[str, object]] = []

    def launch(self, spec):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        with self._lock:
            self._active += 1
            self.peak_active_launches = max(self.peak_active_launches, self._active)
            self._launch_number += 1
            launch_number = self._launch_number
        try:
            # RecordingLauncher mutates a small fixture list; keep that fixture
            # bookkeeping deterministic while the intentionally delayed work overlaps.
            with self._lock:
                outcome = super().launch(spec)
            if launch_number <= self.expected_parallelism and self._first_parallel_group is not None:
                # Validation-only rendezvous: proves that the four canonical
                # worker leases coexist before their constant synthetic delay.
                self._first_parallel_group.wait(timeout=5.0)
            time.sleep(self.delay_seconds)
            return outcome
        finally:
            finished = time.perf_counter()
            with self._lock:
                self._active -= 1
                self.launch_spans.append(
                    {"task_id": spec.task_id, "started": started, "finished": finished}
                )


@dataclass
class RuntimeObservers:
    save_state_calls: int = 0
    save_state_seconds: float = 0.0
    block_descendants_calls: int = 0
    block_descendants_seconds: float = 0.0
    is_ready_calls: int = 0
    is_ready_seconds: float = 0.0


def _instrument_runtime(runtime: CompiledWorkflowRuntime) -> RuntimeObservers:
    observers = RuntimeObservers()
    original_save_state = runtime._save_state
    original_block_descendants = runtime._block_descendants
    original_is_ready = runtime._is_ready

    def save_state() -> None:
        started = time.perf_counter()
        try:
            original_save_state()
        finally:
            observers.save_state_calls += 1
            observers.save_state_seconds += time.perf_counter() - started

    def block_descendants() -> None:
        started = time.perf_counter()
        try:
            original_block_descendants()
        finally:
            observers.block_descendants_calls += 1
            observers.block_descendants_seconds += time.perf_counter() - started

    def is_ready(task) -> bool:  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        try:
            return original_is_ready(task)
        finally:
            observers.is_ready_calls += 1
            observers.is_ready_seconds += time.perf_counter() - started

    runtime._save_state = save_state  # type: ignore[method-assign]
    runtime._block_descendants = block_descendants  # type: ignore[method-assign]
    runtime._is_ready = is_ready  # type: ignore[method-assign]
    return observers


@dataclass(frozen=True)
class CharacterizationRun:
    metric: dict[str, object]
    rows: list[dict[str, object]]


def _execution_spec() -> ExecutionSpec:
    return ExecutionSpec(
        partition="local",
        nodes=1,
        mpi_ranks=1,
        cpus_per_rank=CPUS_PER_TASK,
        memory_mb=128,
        launcher="fixture",
        executable="synthetic-capability",
        walltime_seconds=60,
    )


def _runtime(
    source_root: Path,
    runtime_root: Path,
    compiled,
    task_candidates: dict[str, str],
    launcher: DelayedMetricRecordingLauncher,
    parallelism: int,
) -> tuple[CompiledWorkflowRuntime, TimedFilesystem, CandidateTrackingCapability, RuntimeObservers]:
    if parallelism not in {1, 4}:
        raise ValueError("M9-R1 only characterizes P=1 and P=4")
    capability = CandidateTrackingCapability()
    # Non-exclusive one-node tasks share the one physical node while competing
    # for CPU capacity; the fixture has no host-exclusive placement.
    runtime = CompiledWorkflowRuntime(
        workflow=compiled,
        registry=registry_for(capability),
        root=runtime_root,
        source_root=source_root,
        scientific_identities={
            task.task_id: candidate_identity(task_candidates[task.task_id])
            for task in compiled.tasks
        },
        execution_specs=_execution_spec(),
        launcher=launcher,
        allocation=RuntimeAllocation(
            total_cpus=CPUS_PER_TASK * parallelism,
            total_nodes=1,
            max_parallel_steps=parallelism,
            allocation_id=f"m9-r1-p{parallelism}",
        ),
    )
    filesystem = TimedFilesystem(
        runtime.state_path, runtime.events_path, runtime.journal_path
    )
    runtime.filesystem = filesystem
    return runtime, filesystem, capability, _instrument_runtime(runtime)


def characterize_case(workspace: Path, *, candidates: int, parallelism: int) -> CharacterizationRun:
    """Run one new, clean N/P case once through the canonical runtime."""

    if (candidates, parallelism) not in MATRIX:
        raise ValueError(f"unsupported M9-R1 matrix point: N={candidates}, P={parallelism}")
    case_root = workspace / f"n{candidates}-p{parallelism}"
    source_root = case_root / "source"
    ids = candidate_ids(candidates)
    compile_started = time.perf_counter()
    compiled, task_candidates = compile_campaign(source_root, ids, two_stage=False)
    compile_seconds = time.perf_counter() - compile_started
    launcher = DelayedMetricRecordingLauncher(
        task_candidates,
        delay_seconds=LAUNCH_DELAY_SECONDS,
        expected_parallelism=parallelism,
    )
    runtime, filesystem, capability, observers = _runtime(
        source_root, case_root / "runtime", compiled, task_candidates, launcher, parallelism
    )
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    result = runtime.run()
    wall_seconds = time.perf_counter() - started_wall
    cpu_seconds = time.process_time() - started_cpu
    root = case_root / "runtime"
    summary_started = time.perf_counter()
    rows = candidate_summary(root, ids, two_stage=False)
    summary_seconds = time.perf_counter() - summary_started
    counts = _result_counts(root)
    file_count, filesystem_bytes = _tree_metrics(root)
    peak_rss, peak_rss_source = peak_rss_bytes()
    if result.status != "COMPLETED" or counts["completed_count"] != candidates:
        raise AssertionError(f"M9-R1 did not complete N={candidates}, P={parallelism}: {counts}")
    if any(row["status"] != "COMPLETED" for row in rows):
        raise AssertionError("M9-R1 summary contains non-completed candidates")
    if parallelism == 4 and result.peak_parallel_steps < 4:
        raise AssertionError(f"P=4 did not obtain four runtime leases: {result.peak_parallel_steps}")
    if parallelism == 4 and launcher.peak_active_launches < 4:
        raise AssertionError(f"P=4 did not overlap four synthetic launches: {launcher.peak_active_launches}")
    if filesystem.atomic_failures:
        raise AssertionError(
            f"atomic persistence failed ({filesystem.atomic_failures}, WinError5={filesystem.atomic_winerror_5})"
        )
    metric: dict[str, object] = {
        "workload": "independent-synthetic-canonical-runtime",
        "candidates": candidates,
        "parallelism": parallelism,
        "execution_spec": {"mpi_ranks": 1, "cpus_per_task": CPUS_PER_TASK, "nodes_per_task": 1},
        "allocation": {"total_cpus": CPUS_PER_TASK * parallelism, "total_nodes": 1, "max_parallel_steps": parallelism, "hosts": []},
        "compile_seconds": compile_seconds,
        "wall_seconds": wall_seconds,
        "process_cpu_seconds": cpu_seconds,
        "peak_rss_bytes": peak_rss,
        "peak_rss_source": peak_rss_source,
        "throughput_candidates_per_second": candidates / wall_seconds,
        "attempts": counts["attempts_started"],
        "completed": counts["completed_count"],
        "failed": counts["failed_count"],
        "blocked": counts["blocked_count"],
        "reused": len(result.reused_nodes),
        "peak_parallel_steps": result.peak_parallel_steps,
        "peak_cpus": result.peak_cpus,
        "peak_nodes": result.peak_nodes,
        "peak_active_launches": launcher.peak_active_launches,
        "file_count": file_count,
        "filesystem_bytes": filesystem_bytes,
        "evidence_bytes": _evidence_bytes(root),
        "evidence_bytes_per_candidate": _evidence_bytes(root) / candidates,
        "state_write_count": filesystem.state_write_count,
        "state_bytes_rewritten": filesystem.state_bytes_rewritten,
        "full_snapshot_write_count": filesystem.state_write_count,
        "full_snapshot_bytes": filesystem.state_bytes_rewritten,
        "journal_append_count": filesystem.journal_append_count,
        "journal_bytes": filesystem.journal_bytes,
        "total_state_persistence_bytes": (
            filesystem.state_bytes_rewritten + filesystem.journal_bytes
        ),
        "state_save_calls": observers.save_state_calls,
        "state_save_seconds": observers.save_state_seconds,
        "state_atomic_write_seconds": filesystem.state_atomic_seconds,
        "state_serialization_hash_wrapper_seconds_estimate": max(0.0, observers.save_state_seconds - filesystem.state_atomic_seconds),
        "peak_concurrent_state_writes": filesystem.peak_concurrent_state_writes,
        "state_atomic_failures": filesystem.state_atomic_failures,
        "atomic_failures": filesystem.atomic_failures,
        "atomic_winerror_5": filesystem.atomic_winerror_5,
        "event_append_count": filesystem.event_append_count,
        "event_bytes": filesystem.event_bytes,
        "event_append_seconds": filesystem.event_append_seconds,
        "scheduler_block_descendants_calls": observers.block_descendants_calls,
        "scheduler_block_descendants_seconds": observers.block_descendants_seconds,
        "scheduler_is_ready_calls": observers.is_ready_calls,
        "scheduler_is_ready_seconds": observers.is_ready_seconds,
        "scheduler_scan_seconds": observers.block_descendants_seconds + observers.is_ready_seconds,
        "summary_generation_seconds": summary_seconds,
        "summary_sha256": summary_digest(rows),
        "summary_bytes": len(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "runtime_status": result.status,
    }
    return CharacterizationRun(metric, rows)


def run_matrix(workspace: Path) -> list[CharacterizationRun]:
    """Execute precisely the four M9-R1 matrix cases in a new external workspace."""

    if workspace.exists():
        allowed_bootstrap_files = {"m9-r1.stdout.txt", "m9-r1.stderr.txt", "m9-r1.result.txt"}
        unexpected = [path.name for path in workspace.iterdir() if path.name not in allowed_bootstrap_files]
        if unexpected:
            raise FileExistsError(f"M9-R1 workspace must be new and empty: {workspace}")
    else:
        workspace.mkdir(parents=True)
    runs = [characterize_case(workspace, candidates=n, parallelism=p) for n, p in MATRIX]
    by_key = {(int(run.metric["candidates"]), int(run.metric["parallelism"])): run for run in runs}
    for n in (25, 100):
        if summary_digest(by_key[(n, 1)].rows) != summary_digest(by_key[(n, 4)].rows):
            raise AssertionError(f"summary differs between P=1 and P=4 for N={n}")
    return runs


def write_evidence(evidence_root: Path, runs: list[CharacterizationRun], *, command: str) -> None:
    """Persist compact, reviewable R1 evidence without modifying production code."""

    evidence_root.mkdir(parents=True, exist_ok=True)
    measurements = [run.metric for run in runs]
    hashes = {
        f"N{metric['candidates']}-P{metric['parallelism']}": metric["summary_sha256"]
        for metric in measurements
    }
    (evidence_root / "measurements.json").write_text(
        json.dumps(
            {
                "baseline_sha": BASELINE_SHA,
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "matrix": [{"candidates": n, "parallelism": p} for n, p in MATRIX],
                "resource_model": {
                    "mpi_ranks": 1,
                    "cpus_per_synthetic_task": CPUS_PER_TASK,
                    "nodes_per_synthetic_task": 1,
                    "p1_allocation": {"cpus": 4, "nodes": 1, "max_parallel_steps": 1},
                    "p4_allocation": {"cpus": 16, "nodes": 4, "max_parallel_steps": 4},
                    "host_model": "no hosts: fixture launcher does not require exclusive host placement",
                },
                "measurements": measurements,
            },
            sort_keys=True,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    columns = [
        "candidates", "parallelism", "wall_seconds", "process_cpu_seconds", "throughput_candidates_per_second",
        "attempts", "completed", "failed", "blocked", "reused", "peak_parallel_steps", "peak_active_launches",
        "state_write_count", "state_bytes_rewritten", "state_save_seconds", "state_atomic_write_seconds",
        "state_serialization_hash_wrapper_seconds_estimate", "event_append_count", "event_bytes", "event_append_seconds",
        "scheduler_block_descendants_calls", "scheduler_is_ready_calls", "scheduler_scan_seconds", "file_count",
        "filesystem_bytes", "evidence_bytes", "summary_generation_seconds", "summary_sha256", "atomic_winerror_5",
    ]
    lines = [",".join(columns)]
    for metric in measurements:
        lines.append(",".join(str(metric[column]) for column in columns))
    (evidence_root / "measurements.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = [
        {**row, "workload": f"N{run.metric['candidates']}-P{run.metric['parallelism']}"}
        for run in runs
        for row in run.rows
    ]
    (evidence_root / "summaries.json").write_text(
        json.dumps({"schema_version": "1.0", "rows": rows}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (evidence_root / "summary_hashes.json").write_text(
        json.dumps(hashes, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (evidence_root / "commands.txt").write_text(command.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="new external persistent workspace")
    parser.add_argument("--evidence-dir", type=Path, required=True, help="versioned validation evidence directory")
    args = parser.parse_args()
    runs = run_matrix(args.workspace)
    write_evidence(args.evidence_dir, runs, command=" ".join(sys.argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
