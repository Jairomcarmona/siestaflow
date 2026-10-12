import pytest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from qraft.contracts import CapabilityDescriptor, CapabilityKind, EXECUTION_REQUEST
from qraft.core import ExecutionSpec
from qraft.execution import controller_admission as module
from qraft.execution.controller_admission import admit_controller, expand_scheduler_cpus
from qraft.execution.controller_reservation import ControllerReservation
from qraft.execution.resource_coordinator import RuntimeAllocation


def test_scheduler_cpu_expansion_preserves_host_order():
    assert expand_scheduler_cpus("8(x2),4,12(x3)", 6) == (8, 8, 4, 12, 12, 12)


@pytest.mark.parametrize("value,nodes", [("", 1), ("4", 2), ("4(x1000000000)", 1),
                                        ("0", 1), ("4(x0)", 1), ("4(x-1)", 1),
                                        ("4,,8", 2), ("4.0", 1), ("NaN", 1)])
def test_scheduler_observations_fail_closed(value, nodes):
    with pytest.raises(ValueError, match="ALLOCATION_MISMATCH"):
        expand_scheduler_cpus(value, nodes)


@pytest.fixture
def admission(monkeypatch):
    probes = []
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(module.socket, "gethostname", lambda: "allocated.local")
    monkeypatch.setattr(module.socket, "getfqdn", lambda: "allocated.local")
    monkeypatch.setattr(module, "resolve_controller_entrypoint", lambda extension: Path("/installed/controller"))
    monkeypatch.setattr(module, "probe_controller_containment", lambda: probes.append("positive"))
    descriptor = CapabilityDescriptor("consumer.controller", CapabilityKind.EXECUTABLE,
        "1.0", (EXECUTION_REQUEST,), (), metadata={"qraft.controller": {
            "schema_version": "1.0", "distribution": "consumer-controller",
            "entrypoint": "consumer-controller", "inner_launchers": ["openmpi"], "resume": "NONE",
        }})
    execution = ExecutionSpec("local", 1, 1, 1, None, "controller", "unused", 300,
                              launcher_command=("/installed/mpirun",))
    reservation = ControllerReservation(1, "openmpi", 4, 1, 1)
    allocation = RuntimeAllocation(16, 2, hosts=("remote", "allocated.local"), allocation_id="123")
    return reservation, descriptor, allocation, execution, probes


def test_observed_scheduler_cpus_follow_local_host_not_first_host(admission):
    reservation, descriptor, allocation, execution, probes = admission
    result = admit_controller(reservation, descriptor, allocation, execution, scheduler="slurm",
                              environment={"SLURM_JOB_ID": "123", "SLURM_JOB_CPUS_PER_NODE": "4,12"})
    assert (result.runtime_host, result.runtime_cpus, result.scheduler_cpus_on_host) == ("allocated.local", 8, 12)
    assert result.scheduler_cpu_source == "SLURM_JOB_CPUS_PER_NODE"
    assert probes == ["positive"]


def test_local_capacity_is_profile_declaration_without_physical_discovery(admission):
    reservation, descriptor, allocation, execution, probes = admission
    result = admit_controller(reservation, descriptor, allocation, execution, scheduler="local",
                              environment={"SLURM_JOB_CPUS_PER_NODE": "999"})
    assert (result.runtime_cpus, result.scheduler_cpus_on_host) == (8, 8)
    assert result.scheduler_cpu_source == "LOCAL_PROFILE_DECLARATION"
    assert probes == ["positive"]


@pytest.mark.parametrize("environment", [
    {}, {"SLURM_JOB_ID": "other", "SLURM_JOB_CPUS_PER_NODE": "8,8"},
    {"SLURM_JOB_ID": "123", "SLURM_JOB_CPUS_PER_NODE": "12,4"},
    {"SLURM_JOB_ID": "123", "SLURM_JOB_CPUS_PER_NODE": "16"},
])
def test_scheduler_identity_and_capacity_fail_before_containment_probe(admission, environment):
    reservation, descriptor, allocation, execution, probes = admission
    with pytest.raises(ValueError, match="ALLOCATION_MISMATCH"):
        admit_controller(reservation, descriptor, allocation, execution,
                         scheduler="slurm", environment=environment)
    assert not probes


@pytest.mark.parametrize("hosts", [("a", "b"), ("localhost", "allocated.local")])
def test_unknown_or_ambiguous_runtime_host_is_not_guessed(admission, hosts):
    reservation, descriptor, allocation, execution, probes = admission
    with pytest.raises(ValueError, match="CONTAINMENT_UNAVAILABLE"):
        admit_controller(reservation, descriptor, replace(allocation, hosts=hosts), execution,
                         scheduler="local", environment={})
    assert not probes


@pytest.mark.parametrize("changes", [
    {"environment": {"SLURM_JOB_ID": "forged"}}, {"launcher": "srun"},
    {"launcher_command": ("mpirun",)}, {"launcher_command": ("/bin/mpirun", "--oversubscribe")},
])
def test_profile_cannot_rewrite_grant_or_choose_arbitrary_launcher(admission, changes):
    reservation, descriptor, allocation, execution, probes = admission
    with pytest.raises(ValueError):
        admit_controller(reservation, descriptor, allocation, replace(execution, **changes),
                         scheduler="local", environment={})
    assert not probes


def test_missing_entrypoint_fails_without_containment_or_lease(admission, monkeypatch):
    reservation, descriptor, allocation, execution, probes = admission
    def unavailable(extension):
        raise ValueError("CONTROLLER_ENTRYPOINT_MISSING")
    monkeypatch.setattr(module, "resolve_controller_entrypoint", unavailable)
    with pytest.raises(ValueError, match="ENTRYPOINT_MISSING"):
        admit_controller(reservation, descriptor, allocation, execution, scheduler="local", environment={})
    assert not probes


def test_windows_rejects_before_distribution_resolution(admission, monkeypatch):
    reservation, descriptor, allocation, execution, probes = admission
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(module, "resolve_controller_entrypoint", lambda value: pytest.fail("metadata on Windows"))
    with pytest.raises(ValueError, match="CONTROLLER_REQUIRES_POSIX"):
        admit_controller(reservation, descriptor, allocation, execution, scheduler="local", environment={})
    assert not probes


@pytest.mark.parametrize("failure", [OSError("pidfd unavailable"), ValueError("prctl denied")])
def test_missing_pidfd_has_stable_containment_rejection(monkeypatch, failure):
    def unavailable():
        raise failure
    monkeypatch.setattr(module, "PidfdSignals", unavailable)
    with pytest.raises(ValueError, match="CONTROLLER_CONTAINMENT_UNAVAILABLE"):
        module.probe_controller_containment()


def test_subreaper_rejection_is_not_a_positive_probe(monkeypatch):
    monkeypatch.setattr(module, "PidfdSignals", lambda: None)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError, match="CONTROLLER_CONTAINMENT_UNAVAILABLE"):
        module.probe_controller_containment()
