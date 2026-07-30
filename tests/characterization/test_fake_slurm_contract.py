"""Characterize the scope of the donor Fake SLURM monkey-patch."""

import subprocess

from fake_slurm import FakeSlurmEnvironment


def test_fake_slurm_globally_swallow_unrecognized_check_output_calls():
    with FakeSlurmEnvironment():
        result = subprocess.check_output(["an-unrelated-command", "--version"])

    assert result == b""

