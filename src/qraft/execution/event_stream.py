"""Durable native event identities and replay for one controller per run."""
import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Any

from ..filesystem import RealFileSystem


class NativeCursorError(ValueError):
    """Cursor or preserved stream is not consistent; refresh from a snapshot."""


def _strict_json(data):
    def invalid_constant(value):
        raise ValueError('non-finite JSON number is forbidden')
    try:
        return json.loads(data, parse_constant=invalid_constant)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise NativeCursorError('invalid native event JSON') from exc


@dataclass(frozen=True)
class NativeEventPage:
    stream_id: str
    events: tuple[Mapping[str, Any], ...]
    cursor: str


def _cursor(stream_id: str, sequence: int) -> str:
    return base64.urlsafe_b64encode(json.dumps([stream_id, sequence], separators=(',', ':')).encode()).decode()


class NativeEventStream:
    """No automatic rotation. Metadata and complete JSONL must be retained together.

    Legacy lines are exposed with stable derived IDs without rewriting bytes.
    Incomplete lines and external deletion/rotation fail closed, never rewind IDs.
    This is not a multi-writer lock; controller ownership belongs to the platform.
    """
    def __init__(self, path: Path, runtime_fingerprint: str, *,
                 check_publish: Callable[[], None] = lambda: None,
                 expected_stream_id: str | None = None):
        self.path = path
        self.metadata_path = path.with_suffix('.stream.json')
        self.fingerprint = runtime_fingerprint
        self.check_publish = check_publish
        self.expected_stream_id = expected_stream_id
        self.filesystem = RealFileSystem()
        self._cached_metadata = None
        self._next_sequence = None
        self._last_stat = None
        self._last_metadata_bytes = None

    def _metadata(self, *, create: bool) -> dict:
        if self.metadata_path.exists():
            metadata = _strict_json(self.metadata_path.read_bytes())
            try:
                valid = (isinstance(metadata, dict) and metadata.get('schema_version') == '1.0'
                    and metadata.get('runtime_fingerprint') == self.fingerprint
                    and isinstance(metadata.get('high_water'), int)
                    and not isinstance(metadata.get('high_water'), bool)
                    and metadata['high_water'] >= 0
                    and isinstance(metadata['stream_id'], str)
                    and str(uuid.UUID(metadata['stream_id'])) == metadata['stream_id']
                    and (self.expected_stream_id is None or metadata['stream_id'] == self.expected_stream_id))
            except (KeyError, ValueError, TypeError, AttributeError):
                valid = False
            if not valid:
                raise NativeCursorError('event stream identity is invalid')
            return metadata
        if self.expected_stream_id is not None or not create:
            raise NativeCursorError('stream metadata absent; no stable replay is available')
        metadata = {'schema_version': '1.0', 'runtime_fingerprint': self.fingerprint,
                    'stream_id': str(uuid.uuid4()), 'high_water': 0}
        metadata['high_water'] = len(self._records(metadata))
        self.check_publish()
        self.filesystem.atomic_write_json(self.metadata_path, metadata)
        return metadata

    def ensure_identity(self) -> str:
        """Initialize/adopt legacy once; a persisted expected ID cannot be replaced."""
        metadata = self._metadata(create=True)
        self._records(metadata)
        return metadata['stream_id']

    @staticmethod
    def _event_id(stream_id: str, sequence: int) -> str:
        return hashlib.sha256(f'{stream_id}:{sequence}'.encode('ascii')).hexdigest()

    def _records(self, metadata: dict) -> list[dict]:
        if not self.path.exists():
            if metadata['high_water']:
                raise NativeCursorError('preserved event log was deleted or rotated')
            return []
        data = self.path.read_bytes()
        if data and not data.endswith(b'\n'):
            raise NativeCursorError('incomplete event tail; evidence must be reconciled')
        records = []
        for sequence, line in enumerate(data.splitlines(), 1):
            record = _strict_json(line)
            if not isinstance(record, dict):
                raise NativeCursorError('native event must be a mapping')
            identity = {'stream_id': metadata['stream_id'], 'sequence': sequence,
                        'event_id': self._event_id(metadata['stream_id'], sequence)}
            if set(identity) & set(record) and (
                not set(identity).issubset(record) or not isinstance(record.get('sequence'), int)
                or isinstance(record.get('sequence'), bool)
                or not isinstance(record.get('stream_id'), str)
                or not isinstance(record.get('event_id'), str)
            ):
                raise NativeCursorError('native event identity fields have invalid types')
            if any(key in record and record[key] != value for key, value in identity.items()):
                raise NativeCursorError('event sequence or identity changed')
            records.append({**record, **identity})
        if len(records) < metadata['high_water']:
            raise NativeCursorError('event log cannot be truncated or rotated')
        return records

    def append(self, record: Mapping[str, Any]) -> dict:
        if self._cached_metadata is None:
            metadata = self._metadata(create=True)
            records = self._records(metadata)
            self._next_sequence = len(records) + 1
            self._cached_metadata = metadata
            self._last_stat = self._stat()
            self._last_metadata_bytes = self.metadata_path.read_bytes()
        metadata = self._cached_metadata
        if (self._stat() != self._last_stat or not self.metadata_path.exists()
                or self.metadata_path.read_bytes() != self._last_metadata_bytes):
            raise NativeCursorError('native event log was changed by another writer')
        sequence = self._next_sequence
        identity = {'stream_id': metadata['stream_id'], 'sequence': sequence,
                    'event_id': self._event_id(metadata['stream_id'], sequence)}
        if set(identity) & set(record):
            raise ValueError('native identity fields are owned by the event stream')
        event = {**record, **identity}
        encoded = json.dumps(event, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        self.check_publish()
        self.filesystem.append_text(self.path, encoded + '\n')
        self._last_stat = self._stat()
        self._next_sequence += 1
        self.check_publish()
        self.filesystem.atomic_write_json(self.metadata_path, {**metadata, 'high_water': sequence})
        self._last_metadata_bytes = self.metadata_path.read_bytes()
        return event

    def _stat(self):
        if not self.path.exists():
            return None
        stat = self.path.stat()
        return stat.st_size, stat.st_mtime_ns

    def read(self, *, after: str | None = None, limit: int = 100) -> NativeEventPage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError('event page limit must be between 1 and 10000')
        metadata = self._metadata(create=False)
        records = self._records(metadata)
        position = 0
        if after is not None:
            try:
                stream_id, position = _strict_json(base64.b64decode(after, altchars=b'-_', validate=True))
                if (stream_id != metadata['stream_id'] or isinstance(position, bool)
                        or not isinstance(position, int) or not 0 <= position <= len(records)):
                    raise ValueError('cursor is outside this native stream')
            except (ValueError, TypeError, UnicodeDecodeError) as exc:
                raise NativeCursorError('invalid or expired native cursor') from exc
        selected = tuple(records[position:position + limit])
        return NativeEventPage(metadata['stream_id'], selected,
                               _cursor(metadata['stream_id'], position + len(selected)))
