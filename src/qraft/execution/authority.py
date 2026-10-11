"""Public fail-closed authority boundary; ownership remains outside the engine."""
from dataclasses import dataclass
from typing import Callable


class AuthorityLost(RuntimeError):
    """The current controller generation cannot launch or publish evidence."""


@dataclass(frozen=True)
class AuthorityBoundary:
    runtime_fingerprint: str
    generation: str
    action: str
    task_id: str | None = None
    attempt_id: str | None = None


AuthorityCheck = Callable[[AuthorityBoundary], bool]
