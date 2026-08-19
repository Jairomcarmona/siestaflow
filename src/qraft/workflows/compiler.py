"""Public orchestration service for deterministic workflow compilation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .diagnostics import compilation_result
from .models import WorkflowCompilation
from .parser import WorkflowDefinitionParser
from .resolver import WorkflowResolver


class WorkflowCompiler:
    """Compile a definition through strict parsing and DAG resolution."""

    def __init__(
        self,
        *,
        parser: WorkflowDefinitionParser | None = None,
        resolver: WorkflowResolver | None = None,
    ) -> None:
        self.parser = parser or WorkflowDefinitionParser()
        self.resolver = resolver or WorkflowResolver()

    def compile(self, path: Path) -> WorkflowCompilation:
        source = path.resolve()
        parsed, findings = self.parser.parse(source)
        compiled = (
            self.resolver.resolve(parsed, findings)
            if parsed is not None
            else None
        )
        workflow_id = parsed.workflow_id if parsed is not None else None
        return compilation_result(source, workflow_id, findings, compiled)


def write_workflow_lock(
    compilation: WorkflowCompilation,
    output: Path,
    *,
    overwrite: bool = False,
) -> str:
    """Atomically write a compiled lock and return its content hash."""
    data = compilation.lock_dict()
    if output.exists() and not overwrite:
        raise FileExistsError(f"workflow lock already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            data,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return str(data["content_sha256"])
