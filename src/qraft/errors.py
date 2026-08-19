"""Typed errors used at kernel trust boundaries."""


class QraftError(Exception):
    """Base class for expected kernel errors."""


class PathSafetyError(QraftError):
    """An identifier or resolved path escaped its authorized root."""


class AlreadyExistsError(QraftError):
    """A no-overwrite operation targeted an existing record."""


class IntegrityError(QraftError):
    """Persisted content is corrupt, inconsistent, or has a bad hash."""


class AuthorizationError(QraftError):
    """An authorization envelope is invalid or cannot authorize a task."""


class StateConflictError(QraftError):
    """Materialized state does not agree with its append-only events."""


class PreflightError(QraftError):
    """The installed environment cannot execute the resolved plan safely."""

    def __init__(self, message: str, report: object | None = None) -> None:
        super().__init__(message)
        self.report = report

