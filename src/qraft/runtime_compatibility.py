"""Pure compatibility decisions for selected runtime components."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"
UNKNOWN = "UNKNOWN"


def evaluate_runtime_compatibility(
    components: Mapping[str, Mapping[str, str]],
    conflicts: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Compare strict facts without assigning meaning to their technology."""

    normalized: dict[str, dict[str, str]] = {}
    for component, facts in components.items():
        if not isinstance(component, str) or not component or not isinstance(facts, Mapping):
            raise ValueError("runtime compatibility components must be named fact mappings")
        normalized[component] = {}
        for name, value in facts.items():
            if not isinstance(name, str) or not name or not isinstance(value, str) or not value:
                raise ValueError("runtime compatibility facts must be non-empty strings")
            normalized[component][name] = value

    normalized_conflicts: dict[str, list[str]] = {}
    for component, values in (conflicts or {}).items():
        if (
            component not in normalized
            or not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError("runtime compatibility conflicts are invalid")
        if values:
            normalized_conflicts[component] = list(values)

    contradictions: dict[str, Any] = {}
    if normalized_conflicts:
        contradictions["component_evidence"] = normalized_conflicts
    matched: dict[str, str] = {}
    missing: dict[str, list[str]] = {}
    properties = sorted({name for facts in normalized.values() for name in facts})
    for name in properties:
        observed = {
            component: facts[name]
            for component, facts in normalized.items()
            if name in facts
        }
        if len(set(observed.values())) > 1:
            contradictions[name] = observed
            continue
        absent = sorted(set(normalized) - set(observed))
        if absent:
            missing[name] = absent
        elif observed:
            matched[name] = next(iter(observed.values()))

    if contradictions:
        status = INCOMPATIBLE
    elif not properties or missing:
        status = UNKNOWN
    else:
        status = COMPATIBLE
    return {
        "status": status,
        "matched_facts": matched,
        "missing_facts": missing,
        "contradictions": contradictions,
    }
