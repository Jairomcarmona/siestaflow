import copy
from dataclasses import asdict

import pytest

from qraft.contracts import (
    CapabilityDescriptor, CapabilityKind, EXECUTION_REQUEST, EXECUTION_EVIDENCE,
    CapabilitySupport, CapabilityTarget, CancellationSupport, ResumeSupport,
    SUPPORT_METADATA_KEY, capability_support, contract_sha256,
)


def descriptor(metadata=None):
    return CapabilityDescriptor('consumer.hubbard', CapabilityKind.ENGINE, '1.0.0',
                                (EXECUTION_REQUEST,), (EXECUTION_EVIDENCE,), metadata=metadata or {})


def support():
    return CapabilitySupport(('HF-1',), (CapabilityTarget.SLURM, CapabilityTarget.LOCAL_WSL2),
                             CancellationSupport.COOPERATIVE, ResumeSupport.NATIVE_VERIFIED,
                             ('tests/consumer/test_capability_support.py::test_round_trip',))


def test_round_trip_and_no_automatic_qualification():
    expected = support()
    native = descriptor({SUPPORT_METADATA_KEY: expected.to_mapping()})
    assert capability_support(native) == expected
    assert CapabilitySupport.from_mapping(expected.to_mapping()).to_mapping() == expected.to_mapping()
    assert 'catalog_state' not in native.metadata and 'admitted_for' not in native.metadata


def test_absent_extension_preserves_legacy_descriptor_and_digest():
    native = descriptor()
    assert capability_support(native) is None
    legacy_payload = {
        'capability_id': 'consumer.hubbard', 'kind': 'ENGINE', 'implementation_version': '1.0.0',
        'input_contracts': [{'name': 'siestaflow.execution-request', 'version': {'major': 1, 'minor': 0}}],
        'output_contracts': [{'name': 'siestaflow.execution-evidence', 'version': {'major': 1, 'minor': 0}}],
        'engine': None, 'metadata': {},
    }
    # No newly defaulted fields: old native payloads/hashes retain their shape.
    assert set(asdict(native)) == set(legacy_payload)
    assert contract_sha256(asdict(native)) == contract_sha256(legacy_payload)


@pytest.mark.parametrize('mutate', [
    lambda data: data.update(schema_version='2.0'),
    lambda data: data.update(targets=['FUTURE_TARGET']),
    lambda data: data['supports'].update(resume='FUTURE_RESUME'),
    lambda data: data.update(modes=[True]),
    lambda data: data.update(modes=['HF-1', 'HF-1']),
    lambda data: data.update(test_refs=['']),
    lambda data: data.update(qualified=True),
    lambda data: data['supports'].update(cancel=True),
])
def test_future_invalid_or_claimed_qualification_rejected(mutate):
    data = copy.deepcopy(support().to_mapping())
    mutate(data)
    with pytest.raises((ValueError, TypeError)):
        descriptor({SUPPORT_METADATA_KEY: data})
