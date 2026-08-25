from __future__ import annotations

from pathlib import Path

from tests.characterization.m9_root_cause_harness import characterize_case, summary_digest


def test_p4_uses_four_canonical_runtime_leases_and_preserves_summary(tmp_path: Path) -> None:
    serial = characterize_case(tmp_path / "serial", candidates=25, parallelism=1)
    parallel = characterize_case(tmp_path / "parallel", candidates=25, parallelism=4)

    assert serial.metric["peak_parallel_steps"] == 1
    assert parallel.metric["peak_parallel_steps"] == 4
    assert parallel.metric["peak_active_launches"] == 4
    assert parallel.metric["peak_cpus"] == 16
    assert parallel.metric["peak_nodes"] == 1
    assert parallel.metric["atomic_failures"] == 0
    assert parallel.metric["atomic_winerror_5"] == 0
    assert parallel.metric["peak_concurrent_state_writes"] == 1
    assert summary_digest(serial.rows) == summary_digest(parallel.rows)
