"""Typed, opt-in integration metadata; availability/admission is not engine state."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
import re


SUPPORT_METADATA_KEY = 'qraft.integration'


class CapabilityTarget(str, Enum):
    LOCAL_LINUX = 'LOCAL_LINUX'
    LOCAL_WSL2 = 'LOCAL_WSL2'
    SSH_HOST = 'SSH_HOST'
    SLURM = 'SLURM'
    WEB = 'WEB'
    KUBERNETES = 'KUBERNETES'


class CancellationSupport(str, Enum):
    NONE = 'NONE'
    SCHEDULER = 'SCHEDULER'
    COOPERATIVE = 'COOPERATIVE'


class ResumeSupport(str, Enum):
    NONE = 'NONE'
    NATIVE_VERIFIED = 'NATIVE_VERIFIED'
    NATIVE_ASSERTED = 'NATIVE_ASSERTED'


@dataclass(frozen=True)
class CapabilitySupport:
    modes: tuple[str, ...]
    targets: tuple[CapabilityTarget, ...]
    cancel: CancellationSupport = CancellationSupport.NONE
    resume: ResumeSupport = ResumeSupport.NONE
    test_refs: tuple[str, ...] = ()
    schema_version: str = '1.0'

    def __post_init__(self):
        if self.schema_version != '1.0':
            raise ValueError('unsupported integration metadata version')
        if not isinstance(self.modes, tuple) or any(
            not isinstance(mode, str) or re.fullmatch(r'[A-Z][A-Z0-9_-]*', mode) is None
            for mode in self.modes
        ):
            raise ValueError('capability modes must be explicit uppercase code strings')
        if not isinstance(self.targets, tuple) or any(not isinstance(target, CapabilityTarget) for target in self.targets):
            raise TypeError('capability targets must be typed CapabilityTarget values')
        if not isinstance(self.cancel, CancellationSupport) or not isinstance(self.resume, ResumeSupport):
            raise TypeError('cancel/resume support must use typed enums')
        if not isinstance(self.test_refs, tuple) or any(not isinstance(ref, str) or not ref.strip() for ref in self.test_refs):
            raise ValueError('test references must be non-empty strings')
        for values in (self.modes, self.targets, self.test_refs):
            if len(set(values)) != len(values):
                raise ValueError('capability support lists must not contain duplicates')

    def to_mapping(self) -> dict[str, Any]:
        return {'schema_version': self.schema_version, 'modes': list(self.modes),
                'targets': [target.value for target in self.targets],
                'supports': {'cancel': self.cancel.value, 'resume': self.resume.value},
                'test_refs': list(self.test_refs)}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> 'CapabilitySupport':
        if not isinstance(value, Mapping) or set(value) != {'schema_version', 'modes', 'targets', 'supports', 'test_refs'}:
            raise ValueError('integration metadata fields are missing or unknown')
        supports = value['supports']
        if not isinstance(supports, Mapping) or set(supports) != {'cancel', 'resume'}:
            raise ValueError('integration supports fields are missing or unknown')
        if any(not isinstance(value[field], list) for field in ('modes', 'targets', 'test_refs')):
            raise TypeError('integration modes/targets/test_refs must be JSON arrays')
        return cls(tuple(value['modes']), tuple(CapabilityTarget(target) for target in value['targets']),
                   CancellationSupport(supports['cancel']), ResumeSupport(supports['resume']),
                   tuple(value['test_refs']), value['schema_version'])


def capability_support(descriptor) -> CapabilitySupport | None:
    """Absent means not declared, never automatic qualification or execution grant."""
    if SUPPORT_METADATA_KEY not in descriptor.metadata:
        return None
    return CapabilitySupport.from_mapping(descriptor.metadata[SUPPORT_METADATA_KEY])
