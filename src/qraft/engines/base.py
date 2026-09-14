"""Engine-neutral adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable


class EngineAdapter(ABC):
    @abstractmethod
    def inspect_input(self, path: Path) -> Any: ...

    @abstractmethod
    def validate_input(self, inspected: Any, **kwargs: Any) -> Any: ...

    @abstractmethod
    def prepare_task(self, inspected: Any, workspace: Path, **kwargs: Any) -> Any: ...

    @abstractmethod
    def build_command(self, input_path: Path, **kwargs: Any) -> tuple[str, ...]: ...

    @abstractmethod
    def parse_output(self, lines: Iterable[str], **kwargs: Any) -> Any: ...

    @abstractmethod
    def discover_artifacts(self, workspace: Path, **kwargs: Any) -> Any: ...

    @abstractmethod
    def classify_result(self, parsed: Any, **kwargs: Any) -> Any: ...
