"""Installed package version.

The distribution metadata in :mod:`pyproject.toml` is QRAFT's sole version
source.  Keeping this lookup in a tiny module lets source checkouts remain
importable without introducing a second manually maintained value.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("qraft")
except PackageNotFoundError:  # pragma: no cover - only an uninstalled checkout.
    __version__ = "0+unknown"
