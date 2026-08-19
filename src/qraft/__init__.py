"""QRAFT public Python API.

Only names exported by this module are covered by the documented public API
policy. Submodules remain internal unless their documentation says otherwise.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .version import __version__

__all__ = [
    "ApplicationConfiguration",
    "EngineAdapter",
    "ExecutionProfile",
    "ExecutionSpec",
    "LauncherAdapter",
    "OutputModel",
    "ProfileStore",
    "QraftApplication",
    "SchedulerAdapter",
    "ScientificIdentity",
    "__version__",
]

_PUBLIC_MODULES = {
    "ApplicationConfiguration": "qraft.application",
    "QraftApplication": "qraft.application",
    "ExecutionSpec": "qraft.core",
    "ScientificIdentity": "qraft.core",
    "EngineAdapter": "qraft.engines.base",
    "LauncherAdapter": "qraft.execution.adapters",
    "SchedulerAdapter": "qraft.execution.adapters",
    "ExecutionProfile": "qraft.execution_profiles",
    "ProfileStore": "qraft.execution_profiles",
    "OutputModel": "qraft.output",
}


def __getattr__(name: str) -> Any:
    """Load public classes lazily so subset standalone runtimes remain viable."""
    try:
        module_name = _PUBLIC_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module 'qraft' has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
