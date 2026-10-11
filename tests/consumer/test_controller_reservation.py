"""ADR-017 value validation only; no controller execution is enabled."""

from dataclasses import FrozenInstanceError

import pytest

from qraft.api import ControllerReservation, RuntimeAllocation


def reservation(**changes):
    values = dict(nodes=1, cpus=8, inner_launcher="openmpi",
                  inner_processes_per_node=4, inner_cpus_per_process=1,
                  max_concurrent_inner_launches=1)
    return ControllerReservation.from_mapping(values | changes)


def test_value_is_immutable_and_roundtrips_without_adding_fields():
    value = reservation()
    assert ControllerReservation.from_mapping(value.to_mapping()) == value
    with pytest.raises(FrozenInstanceError):
        value.cpus = 1
    external = value.to_mapping()
    external["cpus"] = 1
    assert value.cpus == 8


@pytest.mark.parametrize("field", [
    "nodes", "cpus", "inner_processes_per_node", "inner_cpus_per_process",
    "max_concurrent_inner_launches",
])
@pytest.mark.parametrize("invalid", [True, False, 0, -1, 1.5, "1", None])
def test_numeric_fields_never_coerce_boolean_float_string_or_empty(field, invalid):
    with pytest.raises(ValueError):
        reservation(**{field: invalid})


@pytest.mark.parametrize("invalid", ["srun", "direct", "OPENMPI", "openmpi ", None, []])
def test_only_declared_inner_launcher_kinds(invalid):
    with pytest.raises(ValueError):
        reservation(inner_launcher=invalid)


@pytest.mark.parametrize("change", [
    {"inner_cpus_per_process": 2}, {"inner_processes_per_node": 9},
    {"max_concurrent_inner_launches": 3}, {"nodes": 3},
])
def test_invalid_per_node_inner_shape(change):
    with pytest.raises(ValueError):
        reservation(**change)


def test_all_fields_required_and_no_extra_fields():
    values = reservation().to_mapping()
    for name in values:
        with pytest.raises(ValueError):
            ControllerReservation.from_mapping({k: v for k, v in values.items() if k != name})
    with pytest.raises(ValueError):
        ControllerReservation.from_mapping(values | {"command": ["anything"]})
    with pytest.raises(ValueError):
        ControllerReservation.from_mapping(None)


def test_charged_allocation_cpus_are_separate_from_inner_ranks():
    allocation = RuntimeAllocation(8, 1, hosts=("allocated-host",))
    request = reservation().resource_request("hf1", allocation)
    assert request.cpus == 8  # Four ranks do not rewrite charged capacity.
    assert request.nodes == 1 and request.exclusive_hosts is True
    assert request.task_id == "hf1"


@pytest.mark.parametrize("cpus", [4, 12])
def test_partial_or_physical_host_capacity_cannot_replace_allocation(cpus):
    with pytest.raises(ValueError, match="whole allocation nodes"):
        reservation(cpus=cpus).resource_request(
            "hf1", RuntimeAllocation(8, 1, hosts=("allocated-host",)),
        )


def test_multi_node_shape_is_arithmetic_only_and_request_is_ungranted():
    allocation = RuntimeAllocation(24, 3, hosts=("a", "b", "c"))
    request = reservation(nodes=2, cpus=16).resource_request("hf1", allocation)
    assert (request.cpus, request.nodes, request.exclusive_hosts) == (16, 2, True)


@pytest.mark.parametrize("allocation", [
    RuntimeAllocation(8, 1), RuntimeAllocation(9, 2, hosts=("a", "b")),
])
def test_no_implicit_hosts_or_fractional_allocation_capacity(allocation):
    with pytest.raises(ValueError):
        reservation().resource_request("hf1", allocation)


def test_cannot_reserve_more_nodes_than_allocation():
    with pytest.raises(ValueError, match="exceeds allocated nodes"):
        reservation(nodes=2, cpus=16).resource_request(
            "hf1", RuntimeAllocation(8, 1, hosts=("a",)),
        )
