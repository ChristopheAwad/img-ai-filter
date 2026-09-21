"""GUI-neutral activity duration and local history tests."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from img_ai_filter.activity_history import (
    SCAN_HISTORY_KEY,
    SCAN_HISTORY_LIMIT,
    SCAN_HISTORY_SCHEMA_VERSION,
    QuarantineFileHistory,
    QuarantineHistoryRecord,
    ScanHistoryRecord,
    append_activity_history,
    clear_activity_history,
    format_duration,
    load_activity_history,
)


class MemoryStore:
    def __init__(self, value: str | None = None) -> None:
        self.values: dict[str, str] = {}
        if value is not None:
            self.values[SCAN_HISTORY_KEY] = value
        self.read_error = False
        self.write_error = False
        self.delete_error = False
        self.reads = 0
        self.writes = 0
        self.deletes: list[str] = []

    def read(self, key: str) -> str | None:
        self.reads += 1
        if self.read_error:
            raise OSError("private read failure")
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.writes += 1
        if self.write_error:
            raise OSError("private write failure")
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.deletes.append(key)
        if self.delete_error:
            raise OSError("private delete failure")
        self.values.pop(key, None)


def _record(index: int = 0, **changes) -> ScanHistoryRecord:
    record = ScanHistoryRecord(
        started_at_utc=f"2026-09-20T12:00:{index % 60:02d}Z",
        source_folder=f"/example/images-{index}",
        model=f"vision-model-{index}",
        outcome="completed",
        duration_ms=index * 1000,
        discovered=index,
        analyzed=index,
        candidates=index,
        ordinary=index,
        uncertain=index,
        failed=index,
        skipped_directories=index,
    )
    return replace(record, **changes)


def _payload(*records: dict, version: object = 1) -> str:
    return json.dumps({"schema_version": version, "records": list(records)})


def _record_dict(record: ScanHistoryRecord) -> dict[str, object]:
    return {
        "started_at_utc": record.started_at_utc,
        "source_folder": record.source_folder,
        "model": record.model,
        "outcome": record.outcome,
        "duration_ms": record.duration_ms,
        "discovered": record.discovered,
        "analyzed": record.analyzed,
        "candidates": record.candidates,
        "ordinary": record.ordinary,
        "uncertain": record.uncertain,
        "failed": record.failed,
        "skipped_directories": record.skipped_directories,
    }


def _file(index: int = 0, **changes) -> QuarantineFileHistory:
    record = QuarantineFileHistory(
        source=f"/source/file-{index}.png",
        destination=f"/quarantine/file-{index}.png",
        status="moved",
        message="Moved successfully.",
    )
    return replace(record, **changes)


def _quarantine(index: int = 0, **changes) -> QuarantineHistoryRecord:
    record = QuarantineHistoryRecord(
        started_at_utc=f"2026-09-20T13:00:{index % 60:02d}Z",
        source_folder=f"/source-{index}",
        quarantine_folder=f"/quarantine-{index}",
        batch_id=f"batch-{index}",
        outcome="completed",
        duration_ms=index * 1000,
        moved=1,
        conflicts=0,
        failed=0,
        files=(_file(index),),
    )
    return replace(record, **changes)


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (0, "<1 sec"),
        (1, "<1 sec"),
        (998, "<1 sec"),
        (999, "<1 sec"),
        (1000, "1 sec"),
        (1001, "1 sec"),
        (1999, "1 sec"),
        (59_999, "59 sec"),
        (60_000, "1 min 0 sec"),
        (60_001, "1 min 0 sec"),
        (61_000, "1 min 1 sec"),
        (3_599_999, "59 min 59 sec"),
        (3_600_000, "1 hr 0 min 0 sec"),
        (3_601_000, "1 hr 0 min 1 sec"),
        (90_061_000, "25 hr 1 min 1 sec"),
    ],
)
def test_format_scan_duration(milliseconds: int, expected: str) -> None:
    assert format_duration(milliseconds) == expected


@pytest.mark.parametrize("value", [-1, True, False, 1.0, "1000", "", None])
def test_format_scan_duration_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        format_duration(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "outcome",
    ["completed", "completed_with_skips", "cancelled", "failed"],
)
def test_record_accepts_each_outcome(outcome: str) -> None:
    assert _record(outcome=outcome).outcome == outcome


def test_record_accepts_zero_counts_and_all_unavailable_counts() -> None:
    assert _record().duration_ms == 0
    unavailable = _record(
        discovered=None,
        analyzed=None,
        candidates=None,
        ordinary=None,
        uncertain=None,
        failed=None,
        skipped_directories=None,
    )
    assert unavailable.discovered is None


@pytest.mark.parametrize(
    "changes",
    [
        {"started_at_utc": ""},
        {"started_at_utc": "2026-09-20T12:00:00"},
        {"started_at_utc": "not-a-timeZ"},
        {"source_folder": ""},
        {"source_folder": "relative/images"},
        {"model": ""},
        {"outcome": "unknown"},
        {"duration_ms": -1},
        {"duration_ms": True},
        {"discovered": -1},
        {"analyzed": True},
        {"discovered": None},
    ],
)
def test_record_rejects_invalid_contract(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _record(**changes)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "not json",
        "null",
        "[]",
        "1",
        json.dumps({"schema_version": 1}),
        json.dumps({"schema_version": 1, "records": [], "extra": True}),
        json.dumps({"schema_version": 1, "records": {}}),
        _payload(version=3),
        _payload(version=True),
        _payload(version="1"),
        _payload(version=-1),
    ],
)
def test_load_invalid_or_missing_history_returns_empty(raw: str | None) -> None:
    assert load_activity_history(MemoryStore(raw)) == ()


def test_load_read_failure_returns_empty() -> None:
    store = MemoryStore()
    store.read_error = True
    assert load_activity_history(store) == ()


def test_load_keeps_valid_records_and_omits_invalid_records() -> None:
    first = _record(1)
    second = _record(2)
    invalid = _record_dict(_record(3))
    invalid["duration_ms"] = -1
    store = MemoryStore(
        _payload(_record_dict(first), invalid, _record_dict(second))
    )

    assert load_activity_history(store) == (first, second)


def test_load_rejects_missing_and_extra_record_fields() -> None:
    missing = _record_dict(_record(1))
    missing.pop("model")
    extra = _record_dict(_record(2))
    extra["endpoint"] = "http://private-server/"

    assert load_activity_history(MemoryStore(_payload(missing, extra))) == ()


def test_load_returns_only_newest_limit_in_stored_order() -> None:
    records = [_record(index) for index in range(SCAN_HISTORY_LIMIT + 5)]
    loaded = load_activity_history(
        MemoryStore(_payload(*(_record_dict(record) for record in records)))
    )
    assert loaded == tuple(records[-SCAN_HISTORY_LIMIT:])


def test_unicode_record_round_trips() -> None:
    record = _record(source_folder="/照片/画像", model="视觉模型")
    store = MemoryStore()
    assert append_activity_history(store, record)
    assert load_activity_history(store) == (record,)
    assert "照片" in store.values[SCAN_HISTORY_KEY]


def test_append_preserves_records_and_writes_once() -> None:
    first = _record(1)
    second = _record(2)
    store = MemoryStore(_payload(_record_dict(first)))

    assert append_activity_history(store, second)
    assert store.writes == 1
    assert load_activity_history(store) == (first, second)


@pytest.mark.parametrize("raw", ["", "not json", _payload(version=99)])
def test_append_repairs_invalid_history(raw: str) -> None:
    record = _record(1)
    store = MemoryStore(raw)
    assert append_activity_history(store, record)
    assert load_activity_history(store) == (record,)


def test_append_retains_valid_parts_of_supported_history() -> None:
    valid = _record(1)
    invalid = _record_dict(_record(2))
    invalid["outcome"] = "bad"
    newest = _record(3)
    store = MemoryStore(_payload(_record_dict(valid), invalid))

    assert append_activity_history(store, newest)
    assert load_activity_history(store) == (valid, newest)


def test_append_trims_only_oldest_records() -> None:
    records = [_record(index) for index in range(SCAN_HISTORY_LIMIT)]
    store = MemoryStore(_payload(*(_record_dict(record) for record in records)))
    newest = _record(1000)

    assert append_activity_history(store, newest)
    assert load_activity_history(store) == tuple(records[1:] + [newest])


def test_append_uses_exact_compact_schema_and_excludes_private_data() -> None:
    marker = "SECRET-MARKER"
    store = MemoryStore()
    record = _record(source_folder="/source", model="model")
    store.values["endpoint_url"] = f"http://{marker}/"
    store.values["quarantine_folder"] = f"/{marker}/quarantine"

    assert append_activity_history(store, record)

    raw = store.values[SCAN_HISTORY_KEY]
    decoded = json.loads(raw)
    assert decoded == {
        "schema_version": 2,
        "records": [{"type": "scan", **_record_dict(record)}],
    }
    assert ": " not in raw
    assert ", " not in raw
    assert marker not in raw
    assert "endpoint" not in raw
    assert "thumbnail" not in raw
    assert "reason" not in raw
    assert "data_url" not in raw


def test_append_read_failure_does_not_write() -> None:
    store = MemoryStore(_payload(_record_dict(_record(1))))
    store.read_error = True
    assert not append_activity_history(store, _record(2))
    assert store.writes == 0


def test_append_write_failure_returns_false_without_changing_value() -> None:
    original = _payload(_record_dict(_record(1)))
    store = MemoryStore(original)
    store.write_error = True
    assert not append_activity_history(store, _record(2))
    assert store.values[SCAN_HISTORY_KEY] == original


def test_append_invalid_record_fails_before_read_or_write() -> None:
    store = MemoryStore()
    object.__setattr__(record := _record(), "duration_ms", -1)
    with pytest.raises(ValueError):
        append_activity_history(store, record)
    assert store.reads == 0
    assert store.writes == 0


def test_clear_deletes_only_history_and_preserves_other_settings() -> None:
    store = MemoryStore(_payload(_record_dict(_record())))
    store.values.update(
        endpoint_url="http://127.0.0.1/",
        endpoint_model="model",
        quarantine_folder="/quarantine",
    )

    assert clear_activity_history(store)
    assert store.deletes == [SCAN_HISTORY_KEY]
    assert SCAN_HISTORY_KEY not in store.values
    assert store.values == {
        "endpoint_url": "http://127.0.0.1/",
        "endpoint_model": "model",
        "quarantine_folder": "/quarantine",
    }


def test_clear_missing_history_succeeds_and_delete_failure_is_safe() -> None:
    store = MemoryStore()
    assert clear_activity_history(store)
    store.delete_error = True
    assert not clear_activity_history(store)


def test_quarantine_models_accept_complete_and_unavailable_outcomes() -> None:
    assert _quarantine().outcome == "completed"
    conflict = _file(status="conflict", message="Destination exists.")
    failed = _file(2, status="failed", message="Move failed.")
    partial = _quarantine(
        outcome="completed_with_failures",
        moved=0,
        conflicts=1,
        failed=1,
        files=(conflict, failed),
    )
    assert partial.conflicts == 1
    unknown = _file(status="unknown", message="Outcome unavailable. Check the quarantine move log.")
    unavailable = _quarantine(
        outcome="failed",
        moved=None,
        conflicts=None,
        failed=None,
        files=(unknown,),
    )
    assert unavailable.moved is None


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "relative.png"},
        {"destination": ""},
        {"status": "bad"},
        {"message": None},
    ],
)
def test_quarantine_file_rejects_invalid_contract(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _file(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"quarantine_folder": "relative"},
        {"batch_id": ""},
        {"outcome": "cancelled"},
        {"files": ()},
        {"moved": True},
        {"moved": None},
        {"moved": 0},
    ],
)
def test_quarantine_record_rejects_invalid_contract(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _quarantine(**changes)


def test_version_one_scan_history_loads_without_rewrite_and_migrates_on_append() -> None:
    old_scan = _record(1)
    store = MemoryStore(_payload(_record_dict(old_scan), version=1))

    assert load_activity_history(store) == (old_scan,)
    assert store.writes == 0

    quarantine = _quarantine(2)
    assert append_activity_history(store, quarantine)
    decoded = json.loads(store.values[SCAN_HISTORY_KEY])
    assert decoded["schema_version"] == 2
    assert [item["type"] for item in decoded["records"]] == ["scan", "quarantine"]
    assert load_activity_history(store) == (old_scan, quarantine)


def test_mixed_activity_history_uses_one_top_level_retention_limit() -> None:
    records = [
        _record(index) if index % 2 == 0 else _quarantine(index)
        for index in range(SCAN_HISTORY_LIMIT + 1)
    ]
    store = MemoryStore()
    for record in records:
        assert append_activity_history(store, record)

    assert load_activity_history(store) == tuple(records[-SCAN_HISTORY_LIMIT:])


def test_quarantine_serialization_has_exact_tagged_schema_and_unicode_paths() -> None:
    record = _quarantine(
        source_folder="/照片",
        quarantine_folder="/隔离",
        files=(_file(source="/照片/图.png", destination="/隔离/图.png"),),
    )
    store = MemoryStore()

    assert append_activity_history(store, record)
    decoded = json.loads(store.values[SCAN_HISTORY_KEY])
    item = decoded["records"][0]
    assert decoded["schema_version"] == 2
    assert set(item) == {
        "type", "started_at_utc", "source_folder", "quarantine_folder",
        "batch_id", "outcome", "duration_ms", "moved", "conflicts",
        "failed", "files",
    }
    assert item["type"] == "quarantine"
    assert item["files"] == [{
        "source": "/照片/图.png",
        "destination": "/隔离/图.png",
        "status": "moved",
        "message": "Moved successfully.",
    }]
    assert load_activity_history(store) == (record,)


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        (r"C:\images\shot.png", r"D:\quarantine\shot.png"),
        (r"\\server\images\shot.png", r"\\server\quarantine\shot.png"),
    ],
)
def test_quarantine_file_accepts_windows_absolute_paths(
    source: str, destination: str
) -> None:
    record = _file(source=source, destination=destination)
    assert record.source == source
    assert record.destination == destination


def test_version_two_load_keeps_valid_mixed_records_and_omits_corruption() -> None:
    scan = _record(1)
    quarantine = _quarantine(2)
    valid_scan = {"type": "scan", **_record_dict(scan)}
    invalid_scan = dict(valid_scan, duration_ms=-1)
    valid_quarantine = {
        "type": "quarantine",
        "started_at_utc": quarantine.started_at_utc,
        "source_folder": quarantine.source_folder,
        "quarantine_folder": quarantine.quarantine_folder,
        "batch_id": quarantine.batch_id,
        "outcome": quarantine.outcome,
        "duration_ms": quarantine.duration_ms,
        "moved": quarantine.moved,
        "conflicts": quarantine.conflicts,
        "failed": quarantine.failed,
        "files": [
            {
                "source": item.source,
                "destination": item.destination,
                "status": item.status,
                "message": item.message,
            }
            for item in quarantine.files
        ],
    }
    invalid_quarantine = dict(valid_quarantine, moved=0)
    raw = json.dumps(
        {
            "schema_version": 2,
            "records": [valid_scan, invalid_scan, invalid_quarantine, valid_quarantine],
        }
    )

    assert load_activity_history(MemoryStore(raw)) == (scan, quarantine)
