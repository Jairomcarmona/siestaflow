"""Extension contract for protocol-owned output contributions."""

from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable

from .model import OutputMessage, OutputModel


@runtime_checkable
class OutputContributor(Protocol):
    """Return structured output data without writing ``qraft.out`` directly."""

    def build_output(self, context: Any) -> OutputModel: ...


def collect_output(
    contributors: Iterable[OutputContributor], context: Any
) -> OutputModel:
    """Collect optional protocol views without coupling them to the writer."""

    models: list[OutputModel] = []
    for contributor in contributors:
        try:
            model = contributor.build_output(context)
            if not isinstance(model, OutputModel):
                raise TypeError("contributor did not return OutputModel")
            models.append(model)
        except Exception as exc:
            models.append(OutputModel(messages=(OutputMessage(
                "WARNING",
                f"optional output contributor failed: {type(exc).__name__}: {exc}",
                code="OUTPUT_CONTRIBUTOR_FAILURE",
            ),)))
    return OutputModel.combine(models)
