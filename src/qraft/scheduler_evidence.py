"""Signed scheduler observation boundary; verification keys stay in the platform."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Callable

from .contracts.serialization import canonical_json


TERMINAL_SLURM_STATES = frozenset({
    'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'NODE_FAIL', 'OUT_OF_MEMORY',
    'PREEMPTED', 'BOOT_FAIL', 'DEADLINE', 'REVOKED',
})


@dataclass(frozen=True)
class SchedulerJobIdentity:
    job_id: str
    cluster: str
    remote_user: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.job_id, self.cluster, self.remote_user)):
            raise ValueError('scheduler identity fields must be explicit strings')


@dataclass(frozen=True)
class TerminalSchedulerEvidence:
    run_id: str
    workflow_lock_sha256: str
    run_lock_sha256: str
    job: SchedulerJobIdentity
    state: str
    observed_at: str
    expires_at: str
    signer_id: str
    signature: str
    active_allocation_absent: bool
    source: str = 'sacct'
    schema_version: str = '1.0'

    def __post_init__(self):
        if self.schema_version != '1.0' or self.source != 'sacct':
            raise ValueError('unsupported scheduler evidence schema/source')
        if not isinstance(self.job, SchedulerJobIdentity):
            raise TypeError('scheduler job identity must be typed')
        for value in (self.run_id, self.signer_id, self.signature):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('scheduler evidence requires run, signer and signature')
        for digest in (self.workflow_lock_sha256, self.run_lock_sha256):
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('scheduler evidence digests must be SHA-256')
        if self.state not in TERMINAL_SLURM_STATES:
            raise ValueError('scheduler observation does not prove a terminal allocation')
        if self.active_allocation_absent is not True:
            raise ValueError('scheduler evidence must rule out a requeued/live allocation')
        if self.timestamp(self.expires_at) <= self.timestamp(self.observed_at):
            raise ValueError('scheduler evidence expiry must follow observation')

    @staticmethod
    def timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError('scheduler observation timestamp must have a timezone')
        return parsed.astimezone(timezone.utc)

    def signed_bytes(self) -> bytes:
        """QRAFT native canonical bytes, excluding the signature itself."""
        payload = asdict(self)
        del payload['signature']
        return canonical_json(payload).encode('utf-8')


TerminalEvidenceVerifier = Callable[[TerminalSchedulerEvidence], bool]
