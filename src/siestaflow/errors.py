"""Typed errors used at kernel trust boundaries."""


class SiestaFlowError(Exception):
    """Base class for expected kernel errors."""


class PathSafetyError(SiestaFlowError):
    """An identifier or resolved path escaped its authorized root."""


class AlreadyExistsError(SiestaFlowError):
    """A no-overwrite operation targeted an existing record."""


class IntegrityError(SiestaFlowError):
    """Persisted content is corrupt, inconsistent, or has a bad hash."""


class AuthorizationError(SiestaFlowError):
    """An authorization envelope is invalid or cannot authorize a task."""


class StateConflictError(SiestaFlowError):
    """Materialized state does not agree with its append-only events."""

