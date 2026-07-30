from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SANDBOX = REPO / "integration" / "local_slurm"


def test_slurm_template_is_explicitly_local_and_non_yoltla():
    content = (SANDBOX / "slurm.conf.in").read_text(encoding="utf-8")
    assert "ClusterName=siestaflow-local" in content
    assert "PartitionName=local" in content
    assert "SlurmctldHost=@HOSTNAME@" in content
    assert "ncz[" not in content.casefold()
    assert "tt[" not in content.casefold()


def test_bootstrap_refuses_unmanaged_existing_config():
    content = (SANDBOX / "bootstrap_wsl.sh").read_text(encoding="utf-8")
    assert "REFUSING_TO_REPLACE_UNMANAGED_SLURM_CONFIG" in content
    assert "slurmd -C" in content
    assert "real_memory_mb=\"$((detected_memory * 9 / 10))\"" in content


def test_acceptance_keeps_local_scope_out_of_scientific_results():
    content = (SANDBOX / "verify_acceptance.py").read_text(encoding="utf-8")
    assert '"scientific_results_allowed": False' in content
    assert '"yoltla_runtime_verified": False' in content
    assert "LOCAL_SLURM_INTEGRATION_PASS" in content


def test_controller_runner_keeps_wsl_client_open_until_sbatch_finishes():
    content = (
        SANDBOX / "run_controller_acceptance.ps1"
    ).read_text(encoding="utf-8")
    assert "sbatch --wait submit.slurm" in content
    assert "Start-Process" not in content
    assert "YOLTLA_RUNTIME" not in content


def test_workload_module_is_importable_and_payload_is_stable():
    path = SANDBOX / "workload.py"
    spec = importlib.util.spec_from_file_location("local_slurm_workload", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PAYLOAD == b"SIESTAFLOW_LOCAL_SLURM_PARENT_DM\n"
