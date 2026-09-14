"""Durable state, append-only events, and immutable artifact manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import IntegrityError, StateConflictError
from .filesystem import FileSystem
from .models import ArtifactRecord, CampaignState, EventRecord, TaskState, primitive


def canonical_json(payload: object) -> str:
    return json.dumps(primitive(payload), sort_keys=True, separators=(",", ":"))


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class StateStore:
    SCHEMA_VERSION = "1.0"

    def __init__(self, path: Path, filesystem: FileSystem) -> None:
        self.path = path
        self.fs = filesystem

    def save(self, state: CampaignState) -> None:
        state.revision += 1
        from .models import utc_now

        state.updated_at = utc_now()
        payload = primitive(state)
        wrapper = {
            "schema_version": self.SCHEMA_VERSION,
            "payload": payload,
            "sha256": sha256_text(canonical_json(payload)),
        }
        self.fs.atomic_write_json(self.path, wrapper)

    def load(self) -> CampaignState:
        try:
            wrapper = json.loads(self.fs.read_text(self.path))
            if wrapper["schema_version"] != self.SCHEMA_VERSION:
                raise IntegrityError("unsupported state schema")
            payload = wrapper["payload"]
            expected = sha256_text(canonical_json(payload))
            if wrapper.get("sha256") != expected:
                raise IntegrityError("state checksum mismatch")
            return CampaignState.from_dict(payload)
        except IntegrityError:
            raise
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"corrupt state file: {self.path}") from exc


class EventStore:
    """JSONL event log with append as its only mutation."""

    def __init__(self, path: Path, filesystem: FileSystem) -> None:
        self.path = path
        self.fs = filesystem

    def append(self, event: EventRecord) -> None:
        self.fs.append_text(self.path, canonical_json(event) + "\n")

    def read_all(self) -> list[EventRecord]:
        if not self.fs.exists(self.path):
            return []
        events: list[EventRecord] = []
        try:
            for line in self.fs.read_text(self.path).splitlines():
                if not line.strip():
                    continue
                events.append(EventRecord(**json.loads(line)))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise IntegrityError(f"corrupt event log: {self.path}") from exc
        return events

    def reconstructed_states(self) -> dict[str, TaskState]:
        states: dict[str, TaskState] = {}
        for event in self.read_all():
            previous = states.get(event.task_id)
            if event.previous_state is not None:
                expected = previous.value if previous else None
                if event.previous_state != expected:
                    raise StateConflictError(
                        f"event chain mismatch for {event.task_id}: "
                        f"expected {expected}, got {event.previous_state}"
                    )
            if event.new_state is not None:
                states[event.task_id] = TaskState(event.new_state)
        return states

    def assert_matches(self, state: CampaignState) -> None:
        reconstructed = self.reconstructed_states()
        for task_id, event_state in reconstructed.items():
            if state.task_states.get(task_id) != event_state:
                raise StateConflictError(f"state/events disagree for {task_id}")


class ArtifactStore:
    def __init__(self, path: Path, filesystem: FileSystem) -> None:
        self.path = path
        self.fs = filesystem

    def register_text(
        self,
        *,
        campaign_id: str,
        task_id: str,
        attempt_id: str,
        relative_path: str,
        content: str,
    ) -> ArtifactRecord:
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        record = ArtifactRecord(
            artifact_id=f"{task_id}:{attempt_id}:{digest[:12]}",
            campaign_id=campaign_id,
            task_id=task_id,
            attempt_id=attempt_id,
            relative_path=relative_path,
            size_bytes=len(encoded),
            sha256=digest,
        )
        self.fs.append_text(self.path, canonical_json(record) + "\n")
        return record

