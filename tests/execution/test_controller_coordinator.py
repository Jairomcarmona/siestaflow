"""Controller host ownership uses the existing coordinator, including gates."""

import pytest

from qraft.execution.resource_coordinator import ResourceCoordinator, ResourceRequest, RuntimeAllocation


def coordinator():
    return ResourceCoordinator(RuntimeAllocation(16, 2, 3, hosts=("remote", "runtime")))


def test_controller_reserves_runtime_host_even_when_it_is_not_first():
    arbiter = coordinator()
    lease = arbiter.try_acquire(ResourceRequest("hf1", 8, 1, True), required_hosts=("runtime",))
    assert lease.hosts == ("runtime",)
    assert arbiter.used_cpus == 8
    assert arbiter.try_acquire(ResourceRequest("gate", 1, 1), local_host="runtime") is None
    # Other-host capacity remains usable by a host-aware scientific task.
    other = arbiter.try_acquire(ResourceRequest("scf", 8, 1, True))
    assert other.hosts == ("remote",)
    arbiter.release(other)
    arbiter.release(lease)
    gate = arbiter.try_acquire(ResourceRequest("gate", 1, 1), local_host="runtime")
    assert gate is not None and gate.hosts == ()  # Preserve the direct-launch contract.
    arbiter.release(gate)
    arbiter.assert_released()


def test_local_gate_prevents_controller_grant_until_its_lease_is_released():
    arbiter = coordinator()
    one = arbiter.try_acquire(ResourceRequest("gate1", 1, 1), local_host="runtime")
    two = arbiter.try_acquire(ResourceRequest("gate2", 1, 1), local_host="runtime")
    request = ResourceRequest("hf1", 8, 1, True)
    assert arbiter.try_acquire(request, required_hosts=("runtime",)) is None
    arbiter.release(one)
    assert arbiter.try_acquire(request, required_hosts=("runtime",)) is None
    arbiter.release(two)
    lease = arbiter.try_acquire(request, required_hosts=("runtime",))
    assert lease.hosts == ("runtime",)
    arbiter.release(lease)
    arbiter.assert_released()


@pytest.mark.parametrize("hosts", [("foreign",), ("runtime", "runtime"), ("remote", "runtime")])
def test_required_host_selection_cannot_escape_or_double_charge_allocation(hosts):
    with pytest.raises(ValueError):
        coordinator().try_acquire(ResourceRequest("hf1", 8, 1, True), required_hosts=hosts)


def test_unreleased_controller_lease_keeps_its_host_and_charged_cpus():
    arbiter = coordinator()
    arbiter.try_acquire(ResourceRequest("hf1", 8, 1, True), required_hosts=("runtime",))
    assert arbiter.active_task_ids == ("hf1",) and arbiter.used_hosts == ("runtime",)
    assert arbiter.try_acquire(ResourceRequest("gate", 1, 1), local_host="runtime") is None
    with pytest.raises(RuntimeError, match="leases remain active"):
        arbiter.assert_released()
