"""Observed, non-submitting behavior of the donor SLURM renderer."""

from qef.legacy.model import QESystem
from slurm import SlurmConfig, generate_slurm_script, validate_steps


def _system(prefix: str = "sample") -> QESystem:
    system = QESystem()
    system.prefix = prefix
    return system


def test_renderer_places_many_registered_steps_in_one_sequential_script():
    config = SlurmConfig(
        partition="test-partition",
        nproc=8,
        npool=2,
        time="01:00:00",
        module="qe/test",
        mpi="custom-launcher",
    )
    steps = validate_steps(["dos", "nscf"])

    script = generate_slurm_script(_system(), steps, config, "/tmp/run")

    assert script.count("#!/bin/bash") == 1
    assert script.index("nscf.in") < script.index("dos.in")
    assert script.count("EXIT_CODE=$?") == 2
    assert 'grep -q "JOB DONE" nscf.out' in script
    assert "custom-launcher -np 8 pw.x" in script
    assert "custom-launcher -np 8 dos.x" in script


def test_renderer_has_allocation_headers_but_no_persistent_worker_contract():
    script = generate_slurm_script(
        _system("m0"),
        ["scf"],
        SlurmConfig(nproc=4),
        "/tmp/run",
    )

    assert "#SBATCH --ntasks=4" in script
    assert "#SBATCH --output=/tmp/run/OUT.post_m0.%j" in script
    assert "#SBATCH --error=/tmp/run/ERR.post_m0.%j" in script
    assert "module purge" in script
    assert "module load" in script
    lowered = script.lower()
    assert "checkpoint" not in lowered
    assert "remaining_time" not in lowered
    assert "gate" not in lowered


def test_step_validation_reorders_and_deduplicates_by_registry_order():
    assert validate_steps(["dos", "nscf", "dos"]) == ["nscf", "dos"]

