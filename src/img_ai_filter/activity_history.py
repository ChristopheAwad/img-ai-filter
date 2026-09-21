"""GUI-neutral persistence helpers for scan and quarantine activity."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import json
import re
from typing import Any, TypeAlias


SCAN_HISTORY_KEY = "scan_history"
SCAN_HISTORY_SCHEMA_VERSION = 2
SCAN_HISTORY_LIMIT = 100

_OUTCOMES = frozenset(
    {"completed", "completed_with_skips", "cancelled", "failed"}
)
_COUNT_FIELDS = (
    "discovered",
    "analyzed",
    "candidates",
    "ordinary",
    "uncertain",
    "failed",
    "skipped_directories",
)
_QUARANTINE_OUTCOMES = frozenset({"completed", "completed_with_failures", "failed"})
_FILE_STATUSES = frozenset({"moved", "conflict", "failed", "unknown"})
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _is_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_absolute_path(value: str) -> bool:
    return (
        value.startswith("/")
        or value.startswith("\\\\")
        or value.startswith("//")
        or _WINDOWS_DRIVE_PATH.match(value) is not None
    )


@dataclass(frozen=True, slots=True)
class ScanHistoryRecord:
    started_at_utc: str
    source_folder: str
    model: str
    outcome: str
    duration_ms: int
    discovered: int | None
    analyzed: int | None
    candidates: int | None
    ordinary: int | None
    uncertain: int | None
    failed: int | None
    skipped_directories: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.started_at_utc, str) or not self.started_at_utc.strip():
            raise ValueError("started_at_utc must be nonblank UTC ISO 8601 text")
        if not self.started_at_utc.endswith("Z"):
            raise ValueError("started_at_utc must end in Z")
        try:
            parsed_timestamp = datetime.fromisoformat(
                self.started_at_utc[:-1] + "+00:00"
            )
        except (TypeError, ValueError) as error:
            raise ValueError("started_at_utc must be valid ISO 8601 text") from error
        if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("started_at_utc must be UTC")

        if not isinstance(self.source_folder, str) or not self.source_folder.strip():
            raise ValueError("source_folder must be nonblank text")
        if not _is_absolute_path(self.source_folder):
            raise ValueError("source_folder must be an absolute path")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must be nonblank text")
        if self.outcome not in _OUTCOMES:
            raise ValueError("outcome is invalid")
        if not _is_nonnegative_integer(self.duration_ms):
            raise ValueError("duration_ms must be a nonnegative integer")

        counts = tuple(getattr(self, name) for name in _COUNT_FIELDS)
        if all(value is None for value in counts):
            return
        if not all(_is_nonnegative_integer(value) for value in counts):
            raise ValueError("counts must all be nonnegative integers or all be None")


@dataclass(frozen=True, slots=True)
class QuarantineFileHistory:
    source: str
    destination: str
    status: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip() or not _is_absolute_path(self.source):
            raise ValueError("source must be a nonblank absolute path")
        if not isinstance(self.destination, str) or not self.destination.strip() or not _is_absolute_path(self.destination):
            raise ValueError("destination must be a nonblank absolute path")
        if self.status not in _FILE_STATUSES:
            raise ValueError("status is invalid")
        if not isinstance(self.message, str):
            raise ValueError("message must be text")


@dataclass(frozen=True, slots=True)
class QuarantineHistoryRecord:
    started_at_utc: str
    source_folder: str
    quarantine_folder: str
    batch_id: str
    outcome: str
    duration_ms: int
    moved: int | None
    conflicts: int | None
    failed: int | None
    files: tuple[QuarantineFileHistory, ...]

    def __post_init__(self) -> None:
        _validate_timestamp(self.started_at_utc)
        for name in ("source_folder", "quarantine_folder"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or not _is_absolute_path(value):
                raise ValueError(f"{name} must be a nonblank absolute path")
        if not isinstance(self.batch_id, str) or not self.batch_id.strip():
            raise ValueError("batch_id must be nonblank text")
        if self.outcome not in _QUARANTINE_OUTCOMES:
            raise ValueError("outcome is invalid")
        if not _is_nonnegative_integer(self.duration_ms):
            raise ValueError("duration_ms must be a nonnegative integer")
        if not isinstance(self.files, tuple) or not self.files or not all(isinstance(item, QuarantineFileHistory) for item in self.files):
            raise ValueError("files must be a nonempty tuple of quarantine file records")

        counts = (self.moved, self.conflicts, self.failed)
        if all(value is None for value in counts):
            if self.outcome != "failed" or any(item.status != "unknown" for item in self.files):
                raise ValueError("unavailable counts require failed unknown outcomes")
            return
        if not all(_is_nonnegative_integer(value) for value in counts):
            raise ValueError("counts must all be nonnegative integers or all be None")
        expected = {
            "moved": sum(item.status == "moved" for item in self.files),
            "conflict": sum(item.status == "conflict" for item in self.files),
            "failed": sum(item.status == "failed" for item in self.files),
        }
        if any(item.status == "unknown" for item in self.files) or counts != (expected["moved"], expected["conflict"], expected["failed"]):
            raise ValueError("counts must match file statuses")


HistoryRecord: TypeAlias = ScanHistoryRecord | QuarantineHistoryRecord


def _validate_timestamp(value: object) -> None:
    if not isinstance(value, str) or not value.strip() or not value.endswith("Z"):
        raise ValueError("started_at_utc must be nonblank UTC ISO 8601 text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError) as error:
        raise ValueError("started_at_utc must be valid ISO 8601 text") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("started_at_utc must be UTC")


_RECORD_FIELDS = tuple(field.name for field in fields(ScanHistoryRecord))
_RECORD_FIELD_SET = frozenset(_RECORD_FIELDS)
_FILE_FIELDS = tuple(field.name for field in fields(QuarantineFileHistory))
_FILE_FIELD_SET = frozenset(_FILE_FIELDS)
_QUARANTINE_FIELDS = tuple(field.name for field in fields(QuarantineHistoryRecord))
_QUARANTINE_FIELD_SET = frozenset(_QUARANTINE_FIELDS)


def _record_to_dict(record: HistoryRecord) -> dict[str, object]:
    if isinstance(record, ScanHistoryRecord):
        return {"type": "scan", **{name: getattr(record, name) for name in _RECORD_FIELDS}}
    return {
        "type": "quarantine",
        **{
            name: (
                [{field: getattr(item, field) for field in _FILE_FIELDS} for item in record.files]
                if name == "files"
                else getattr(record, name)
            )
            for name in _QUARANTINE_FIELDS
        },
    }


def _validated_record(record: object) -> HistoryRecord:
    try:
        if isinstance(record, ScanHistoryRecord):
            values = {name: getattr(record, name) for name in _RECORD_FIELDS}
            return ScanHistoryRecord(**values)
        if isinstance(record, QuarantineHistoryRecord):
            files = tuple(QuarantineFileHistory(**{name: getattr(item, name) for name in _FILE_FIELDS}) for item in record.files)
            values = {name: getattr(record, name) for name in _QUARANTINE_FIELDS if name != "files"}
            return QuarantineHistoryRecord(**values, files=files)
        raise ValueError("record must be an activity history record")
    except (TypeError, ValueError) as error:
        raise ValueError("record is invalid") from error


def _decode_history(raw: object) -> tuple[HistoryRecord, ...]:
    if not isinstance(raw, str) or not raw.strip():
        return ()
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "records"}:
        return ()
    version = payload["schema_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version not in (1, 2) or not isinstance(payload["records"], list):
        return ()

    valid: list[HistoryRecord] = []
    for item in payload["records"]:
        if not isinstance(item, dict):
            continue
        try:
            if version == 1 and set(item) == _RECORD_FIELD_SET:
                valid.append(ScanHistoryRecord(**item))
            elif version == 2 and item.get("type") == "scan" and set(item) == _RECORD_FIELD_SET | {"type"}:
                valid.append(ScanHistoryRecord(**{name: item[name] for name in _RECORD_FIELDS}))
            elif version == 2 and item.get("type") == "quarantine" and set(item) == _QUARANTINE_FIELD_SET | {"type"}:
                raw_files = item["files"]
                if not isinstance(raw_files, list):
                    continue
                files = tuple(QuarantineFileHistory(**child) for child in raw_files if isinstance(child, dict) and set(child) == _FILE_FIELD_SET)
                if len(files) != len(raw_files):
                    continue
                valid.append(QuarantineHistoryRecord(**{name: item[name] for name in _QUARANTINE_FIELDS if name != "files"}, files=files))
        except (TypeError, ValueError):
            continue
    return tuple(valid[-SCAN_HISTORY_LIMIT:])


def load_activity_history(store: Any) -> tuple[HistoryRecord, ...]:
    """Load valid records without exposing malformed data or store failures."""
    try:
        raw = store.read(SCAN_HISTORY_KEY)
    except Exception:
        return ()
    return _decode_history(raw)


def append_activity_history(store: Any, record: HistoryRecord) -> bool:
    """Append one record and retain only the newest bounded history."""
    validated = _validated_record(record)
    try:
        raw = store.read(SCAN_HISTORY_KEY)
    except Exception:
        return False

    records = (*_decode_history(raw), validated)[-SCAN_HISTORY_LIMIT:]
    payload = {
        "schema_version": SCAN_HISTORY_SCHEMA_VERSION,
        "records": [_record_to_dict(item) for item in records],
    }
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        store.write(SCAN_HISTORY_KEY, serialized)
    except Exception:
        return False
    return True


def clear_activity_history(store: Any) -> bool:
    """Delete only activity history, treating an absent value as success."""
    try:
        store.delete(SCAN_HISTORY_KEY)
    except Exception:
        return False
    return True


def format_duration(duration_ms: int) -> str:
    """Format milliseconds without rounding beyond measured whole seconds."""
    if not _is_nonnegative_integer(duration_ms):
        raise ValueError("duration_ms must be a nonnegative integer")
    if duration_ms < 1000:
        return "<1 sec"

    total_seconds = duration_ms // 1000
    if total_seconds < 60:
        return f"{total_seconds} sec"
    if total_seconds < 3600:
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes} min {seconds} sec"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours} hr {minutes} min {seconds} sec"
