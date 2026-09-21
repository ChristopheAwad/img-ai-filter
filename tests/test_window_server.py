"""KoboldCpp settings, consent, worker, and result GUI tests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

import img_ai_filter.window as window_module
from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.image_payload import SourceIdentity
from img_ai_filter.quarantine import (
    MOVE_LOG_NAME,
    MoveOutcome,
    MoveStatus,
    QuarantineState,
    QuarantineSummary,
)
from img_ai_filter.scan_workflow import ScanCandidate, ScanState, ScanSummary
from img_ai_filter.activity_history import (
    SCAN_HISTORY_KEY,
    QuarantineHistoryRecord,
    ScanHistoryRecord,
    append_activity_history,
    load_activity_history,
)
from img_ai_filter.vision_connection import KoboldCppInfo, VisionConnectionError
from img_ai_filter.window import (
    ActivityHistoryDialog,
    CandidateSelectionSettingsDialog,
    DEFAULT_SERVER_URL,
    MainWindow,
)
from img_ai_filter.settings import AUTO_SELECT_CONFIDENCE_KEY, QUARANTINE_FOLDER_KEY


READY_CONFIG = build_vision_endpoint_config(
    "http://192.168.0.239:5001/v1/", model="vision-model"
)

ONE_PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001"
    "08060000001f15c4890000000d49444154789c6360606060"
    "000000050001a5f645400000000049454e44ae426082"
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.write_error = False
        self.delete_error = False

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        if self.write_error:
            raise OSError("private settings write failure")
        self.values[key] = value

    def delete(self, key: str) -> None:
        if self.delete_error:
            raise OSError("private settings delete failure")
        self.values.pop(key, None)


@pytest.fixture(autouse=True)
def isolate_platform_settings(monkeypatch):
    monkeypatch.setattr(window_module, "_QSettingsStore", MemoryStore)


def _identity(data: bytes) -> SourceIdentity:
    return SourceIdentity(len(data), hashlib.sha256(data).hexdigest())


def _candidate(path: Path, category: str = "screenshot") -> ScanCandidate:
    data = path.read_bytes() if path.is_file() else b""
    return ScanCandidate(
        path,
        category,
        f"Visual reason for {category}.",
        0.8,
        _identity(data),
        ONE_PIXEL_PNG,
        1,
        1,
    )


def _move_summary(
    quarantine_root: Path,
    outcomes: tuple[MoveOutcome, ...],
    state: QuarantineState,
) -> QuarantineSummary:
    return QuarantineSummary("test-batch", quarantine_root, outcomes, state)


class FakeTransport:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel_active(self) -> None:
        self.cancel_calls += 1


def _summary(
    state: ScanState = ScanState.COMPLETED,
    candidates: tuple[ScanCandidate, ...] = (),
    *,
    discovered: int = 0,
    analyzed: int = 0,
    ordinary: int = 0,
    uncertain: int = 0,
    failed: int = 0,
    skipped_directories: int = 0,
) -> ScanSummary:
    return ScanSummary(
        state,
        candidates,
        discovered,
        analyzed,
        ordinary,
        uncertain,
        failed,
        skipped_directories,
    )


def _select(window: MainWindow, monkeypatch, folder: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))
    window.select_button.click()


def test_server_url_is_prefilled_and_scan_waits_for_successful_connection(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    window = MainWindow(settings_store=MemoryStore())
    qtbot.addWidget(window)

    assert DEFAULT_SERVER_URL == "http://192.168.0.239:5001/v1/"
    assert window.server_url_input.text() == DEFAULT_SERVER_URL
    assert window.test_connection_button.text() == "Test Connection"
    assert window.connection_label.text() == "Test the server connection before scanning."
    _select(window, monkeypatch, tmp_path)
    assert not window.scan_button.isEnabled()


def test_connection_test_discovers_version_vision_model_and_persists_settings(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    store = MemoryStore()
    transport = FakeTransport()
    calls = []

    def discover(config, received_transport):
        calls.append((config, received_transport))
        return KoboldCppInfo("1.76.1", "loaded-vision-model", True, False)

    window = MainWindow(
        settings_store=store,
        transport_factory=lambda: transport,
        discover=discover,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.test_connection_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert len(calls) == 1
    assert calls[0][0].model is None
    assert calls[0][1] is transport
    assert "KoboldCpp 1.76.1" in window.connection_label.text()
    assert "vision ready" in window.connection_label.text().lower()
    assert window.model_label.text() == "Model: loaded-vision-model"
    assert store.values["endpoint_url"] == DEFAULT_SERVER_URL
    assert store.values["endpoint_model"] == "loaded-vision-model"


def test_connection_failure_is_safe_and_retryable(qtbot) -> None:
    attempts = 0

    def discover(config, transport):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise VisionConnectionError("The KoboldCpp server could not be reached")
        return KoboldCppInfo("1.0", "model", True, False)

    window = MainWindow(
        settings_store=MemoryStore(),
        transport_factory=FakeTransport,
        discover=discover,
    )
    qtbot.addWidget(window)

    window.test_connection_button.click()
    qtbot.waitUntil(lambda: window.test_connection_button.isEnabled())
    assert window.connection_label.text() == "The KoboldCpp server could not be reached"
    assert not window.scan_button.isEnabled()

    window.test_connection_button.click()
    qtbot.waitUntil(lambda: "KoboldCpp 1.0" in window.connection_label.text())
    assert attempts == 2


def test_editing_server_url_invalidates_discovered_model(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    window = MainWindow(initial_config=READY_CONFIG)
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    assert window.scan_button.isEnabled()

    window.server_url_input.setText("http://127.0.0.1:5001/v1/")

    assert not window.scan_button.isEnabled()
    assert window.model_label.text() == "Model: not discovered"
    assert window.connection_label.text() == "Test the server connection before scanning."


def test_invalid_or_public_server_url_never_starts_connection(qtbot) -> None:
    calls = []
    window = MainWindow(
        settings_store=MemoryStore(),
        discover=lambda *args: calls.append(args),
    )
    qtbot.addWidget(window)
    window.server_url_input.setText("http://8.8.8.8/v1/")

    window.test_connection_button.click()

    assert calls == []
    assert "private-network" in window.connection_label.text()
    assert window.test_connection_button.isEnabled()


def test_scan_consent_names_origin_transfer_and_unencrypted_http(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    dialogs = []

    def question(*args):
        dialogs.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    scan_calls = []
    window = MainWindow(
        initial_config=READY_CONFIG,
        run_scan=lambda *args, **kwargs: scan_calls.append(args),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()

    text = dialogs[0][2]
    assert READY_CONFIG.origin in text
    assert "Every supported image will leave this computer" in text
    assert "unencrypted HTTP" in text
    assert scan_calls == []
    assert window.scan_button.isEnabled()
    assert window.status_label.text() == "Folder ready. Select Scan Folder to begin."


def test_https_consent_does_not_claim_transfer_is_unencrypted(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    config = build_vision_endpoint_config("https://127.0.0.1:5443/v1/", model="m")
    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: messages.append(args[2]) or QMessageBox.StandardButton.No,
    )
    window = MainWindow(initial_config=config)
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()

    assert "Every supported image will leave this computer" in messages[0]
    assert "unencrypted HTTP" not in messages[0]


def test_accepting_consent_runs_background_scan_and_shows_exact_summary(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    entered = Event()
    release = Event()

    def run_scan(folder, config, transport, **kwargs):
        entered.set()
        release.wait(2)
        kwargs["progress"](3, 5)
        return _summary(
            ScanState.COMPLETED_WITH_SKIPS,
            discovered=5,
            analyzed=4,
            ordinary=1,
            uncertain=1,
            failed=1,
            skipped_directories=1,
        )

    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)
    assert not window.select_button.isEnabled()
    assert not window.server_url_input.isEnabled()
    assert not window.test_connection_button.isEnabled()
    assert not window.scan_button.isEnabled()
    assert window.cancel_button.isEnabled()
    assert not window.settings_button.isEnabled()
    timer_fired = []
    QTimer.singleShot(0, lambda: timer_fired.append(True))
    qtbot.waitUntil(lambda: timer_fired == [True])
    release.set()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert window.status_label.text() == (
        "Completed with skips: 5 discovered, 4 analyzed, 0 candidates, "
        "1 ordinary, 1 uncertain, 1 failed, 1 unreadable folder. "
        "Elapsed: <1 sec."
    )
    assert not window.cancel_button.isEnabled()
    assert window.settings_button.isEnabled()


def test_completed_operation_thread_is_scheduled_for_deletion(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    deleted = []
    monkeypatch.setattr(
        window_module.OperationThread,
        "deleteLater",
        lambda thread: deleted.append(thread),
    )
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(),
        confirm_transfer=lambda *_: True,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: len(deleted) == 1)

    assert window._thread is None


def test_candidate_rows_include_details_and_start_unchecked(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    candidate_path = tmp_path / "candidate.png"
    summary = _summary(
        candidates=(
            ScanCandidate(
                candidate_path,
                "captioned_meme",
                "Large caption above a reaction image.",
                0.87,
                SourceIdentity(0, "a" * 64),
                ONE_PIXEL_PNG,
                1,
                1,
            ),
        ),
        discovered=3,
        analyzed=3,
        ordinary=1,
        uncertain=1,
    )
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: summary,
        confirm_transfer=lambda *_: True,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)

    item = window.results_list.item(0)
    assert str(candidate_path) in item.text()
    assert "captioned meme" in item.text()
    assert "Large caption above a reaction image." in item.text()
    assert "87%" in item.text()
    assert item.checkState() == Qt.CheckState.Unchecked
    assert window.status_label.text() == (
        "Completed: 3 discovered, 3 analyzed, 1 candidate, 1 ordinary, "
        "1 uncertain, 0 failed, 0 unreadable folders. Elapsed: <1 sec."
    )


def test_retry_replaces_old_rows_and_requests_consent_again(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    candidate = ScanCandidate(
        tmp_path / "old.png",
        "screenshot",
        "Interface.",
        0.9,
        SourceIdentity(0, "a" * 64),
        ONE_PIXEL_PNG,
        1,
        1,
    )
    outcomes = iter(
        [
            _summary(candidates=(candidate,), discovered=1, analyzed=1),
            _summary(discovered=1, analyzed=1, ordinary=1),
        ]
    )
    consents = []
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: next(outcomes),
        confirm_transfer=lambda *args: consents.append(args) or True,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())
    window.scan_button.click()
    qtbot.waitUntil(lambda: "1 ordinary" in window.status_label.text())

    assert len(consents) == 2
    assert window.results_list.count() == 0
    assert "1 ordinary" in window.status_label.text()


def test_cancel_closes_active_transport_and_allows_retry(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    transport = FakeTransport()
    store = MemoryStore()
    clock = [10.0]
    entered = Event()

    def run_scan(folder, config, received_transport, **kwargs):
        entered.set()
        cancel_event = kwargs["cancel_event"]
        while not cancel_event.wait(0.01):
            pass
        return _summary(ScanState.CANCELLED, discovered=2)

    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=lambda: transport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        monotonic=lambda: clock[0],
        utc_now=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)

    window.cancel_button.click()
    assert window.status_label.text() == "Cancelling scan... Elapsed: <1 sec."
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert transport.cancel_calls == 1
    assert window.status_label.text() == (
        "Cancelled: 2 discovered, 0 analyzed, 0 candidates, 0 ordinary, "
        "0 uncertain, 0 failed, 0 unreadable folders. Elapsed: <1 sec."
    )


def test_total_failure_and_worker_exception_are_safe_and_retryable(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    private = "private response body"
    outcomes = iter([RuntimeError(private), _summary(ScanState.FAILED, discovered=2, failed=2)])

    def run_scan(*args, **kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())
    assert window.status_label.text() == (
        "The scan could not be completed. Elapsed: <1 sec."
    )
    assert private not in window.status_label.text()

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.status_label.text().startswith("Failed:"))
    assert "2 failed" in window.status_label.text()
    assert window.scan_button.isEnabled()


def test_close_during_scan_cancels_transport_and_stops_worker(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    transport = FakeTransport()
    store = MemoryStore()
    clock = [10.0]
    entered = Event()
    deleted = []
    monkeypatch.setattr(
        window_module.OperationThread,
        "deleteLater",
        lambda thread: deleted.append(thread),
    )

    def run_scan(*args, **kwargs):
        entered.set()
        kwargs["cancel_event"].wait(2)
        return _summary(ScanState.CANCELLED)

    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=lambda: transport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        monotonic=lambda: clock[0],
        utc_now=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)

    clock[0] = 12.0
    window.close()
    qtbot.waitUntil(lambda: len(deleted) == 1)

    assert transport.cancel_calls == 1
    assert window._thread is None or not window._thread.isRunning()
    records = load_activity_history(store)
    assert len(records) == 1
    assert records[0].outcome == "cancelled"
    assert records[0].duration_ms == 2000
    assert records[0].discovered is None


# ---------------------------------------------------------------------------
# Quarantine folder selection and move workflow
# ---------------------------------------------------------------------------


def _scanned_candidate_window(
    qtbot,
    monkeypatch,
    tmp_path: Path,
    candidates: tuple[ScanCandidate, ...] = (),
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for candidate in candidates:
        candidate.path.write_bytes(b"scan bytes")
    summary = _summary(
        candidates=candidates,
        discovered=len(candidates),
        analyzed=len(candidates),
    )
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: summary,
        confirm_transfer=lambda *_: True,
        settings_store=MemoryStore(),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, source_dir)
    if candidates:
        window.scan_button.click()
        qtbot.waitUntil(lambda: window.results_list.count() == len(candidates))
    return window, source_dir


def _pick_quarantine(window: MainWindow, monkeypatch, folder: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: str(folder)
    )
    window.select_quarantine_button.click()


def test_quarantine_starts_without_folder_and_move_is_disabled(qtbot) -> None:
    window = MainWindow(settings_store=MemoryStore(), initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    assert window.select_quarantine_button.text() == "Select Quarantine Folder"
    assert window.forget_quarantine_button.text() == "Forget Quarantine Folder"
    assert window.move_quarantine_button.text() == "Move Checked to Quarantine"
    assert "No quarantine folder" in window.quarantine_label.text()
    assert not window.move_quarantine_button.isEnabled()
    assert not window.forget_quarantine_button.isEnabled()


def test_stored_quarantine_folder_loads_at_startup(qtbot, tmp_path: Path) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    store = MemoryStore()
    store.write(QUARANTINE_FOLDER_KEY, str(quarantine))

    window = MainWindow(settings_store=store, initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    assert window.quarantine_label.text() == str(quarantine)
    assert window.forget_quarantine_button.isEnabled()


def test_stored_quarantine_folder_that_disappeared_is_flagged(
    qtbot, tmp_path: Path
) -> None:
    store = MemoryStore()
    store.write(QUARANTINE_FOLDER_KEY, str(tmp_path / "gone"))

    window = MainWindow(settings_store=store, initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    assert "not available" in window.quarantine_label.text()
    assert not window.move_quarantine_button.isEnabled()


def test_selecting_quarantine_folder_persists_and_enables_move(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )

    assert not window.move_quarantine_button.isEnabled()
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert not window.move_quarantine_button.isEnabled()
    _pick_quarantine(window, monkeypatch, quarantine)

    assert window.move_quarantine_button.isEnabled()


def test_select_quarantine_persists_uses_store(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    store = MemoryStore()
    window = MainWindow(settings_store=store, initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    _pick_quarantine(window, monkeypatch, quarantine)

    assert store.values[QUARANTINE_FOLDER_KEY] == str(quarantine)
    assert str(quarantine) in window.quarantine_label.text()


def test_cancelling_quarantine_picker_keeps_current_folder(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    store = MemoryStore()
    store.write(QUARANTINE_FOLDER_KEY, str(quarantine))
    window = MainWindow(settings_store=store, initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")
    window.select_quarantine_button.click()

    assert window.quarantine_label.text() == str(quarantine)
    assert store.values[QUARANTINE_FOLDER_KEY] == str(quarantine)


def test_quarantine_picker_rejects_a_file_folder(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    not_a_dir = tmp_path / "note.txt"
    not_a_dir.write_text("not a folder")
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args: warnings.append(args) or QMessageBox.StandardButton.Ok,
    )
    store = MemoryStore()
    window = MainWindow(settings_store=store, initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    _pick_quarantine(window, monkeypatch, not_a_dir)

    assert len(warnings) == 1
    assert QUARANTINE_FOLDER_KEY not in store.values
    assert "No quarantine folder" in window.quarantine_label.text()


def test_quarantine_cannot_be_placed_inside_source_folder(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    inside = source_dir / "quarantine"
    inside.mkdir()
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args: warnings.append(args) or QMessageBox.StandardButton.Ok,
    )
    store = MemoryStore()
    window = MainWindow(settings_store=store, initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: str(source_dir)
    )
    window.select_button.click()
    _pick_quarantine(window, monkeypatch, inside)

    assert len(warnings) == 1
    assert QUARANTINE_FOLDER_KEY not in store.values


def test_overlapping_source_selected_after_quarantine_disables_move(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "shot.png"
    source_file.write_bytes(b"scan bytes")
    quarantine = source_dir / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(
            candidates=(candidate,),
            discovered=1,
            analyzed=1,
        ),
        confirm_transfer=lambda *_: True,
        settings_store=MemoryStore(),
    )
    qtbot.addWidget(window)

    _pick_quarantine(window, monkeypatch, quarantine)
    _select(window, monkeypatch, source_dir)
    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)

    assert not window.move_quarantine_button.isEnabled()


def test_default_confirm_uses_source_and_destination_pairs(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "source"
    source_file = source_dir / "inner" / "shot.png"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"scan bytes")
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(
            candidates=(candidate,),
            discovered=1,
            analyzed=1,
        ),
        confirm_transfer=lambda *_: True,
        settings_store=MemoryStore(),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, source_dir)
    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)
    window._quarantine_folder = quarantine
    captured = {}

    def record_parts(items, folder):
        captured["items"] = tuple(items)
        captured["folder"] = folder
        return ("title", "heading", "detailed")

    monkeypatch.setattr(window_module, "_quarantine_confirm_parts", record_parts)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.DialogCode.Accepted
    )
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window.move_quarantine_button.click()

    assert captured["folder"] == str(quarantine)
    assert captured["items"] == (
        (str(source_file), str(quarantine / "inner" / "shot.png")),
    )


def test_quarantine_confirm_parts_mention_folder_and_every_path() -> None:
    title, heading, detailed = window_module._quarantine_confirm_parts(
        (("a.png", "q/a.png"), ("b.png", "q/b.png")), "/q"
    )
    assert title == "Move checked files to quarantine?"
    assert "2" in heading
    assert "/q" in heading
    assert "a.png" in detailed
    assert "q/a.png" in detailed
    assert "b.png" in detailed
    assert "q/b.png" in detailed


def test_declining_quarantine_confirm_changes_nothing(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    confirmations = []

    def on_confirm(paths, folder):
        confirmations.append((tuple(paths), folder))
        return False

    def on_move(*args, **kwargs):
        raise AssertionError("run_quarantine must not run after decline")

    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)

    window._confirm_quarantine = on_confirm
    window._run_quarantine = on_move
    window.move_quarantine_button.click()

    assert confirmations == [((str(source_file),), str(quarantine))]
    assert not (quarantine / "shot.png").exists()


def test_accepting_confirmation_runs_checked_move_and_reports_summary(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    runs = []

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        runs.append((list(candidates), source_root, quarantine_root))
        progress(1, 1)
        return _move_summary(
            quarantine,
            (
                MoveOutcome(
                    source_file,
                    quarantine / "shot.png",
                    MoveStatus.MOVED,
                    "",
                ),
            ),
            QuarantineState.COMPLETED,
        )

    window, source_dir = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(lambda: "Moved 1 of 1" in window.status_label.text())

    assert runs[0][0] == [candidate]
    assert runs[0][1] == source_dir.resolve()
    assert runs[0][2] == quarantine
    assert window.move_log_label.text() == str(quarantine / MOVE_LOG_NAME)
    assert not window.cancel_button.isEnabled()
    assert window.status_label.text().endswith("Elapsed: <1 sec.")
    record = load_activity_history(window._settings_store)[-1]
    assert isinstance(record, QuarantineHistoryRecord)
    assert record.source_folder == str(source_dir.resolve())
    assert record.quarantine_folder == str(quarantine)
    assert record.outcome == "completed"
    assert (record.moved, record.conflicts, record.failed) == (1, 0, 0)
    assert record.files[0].source == str(source_file)
    assert record.files[0].destination == str(quarantine / "shot.png")
    assert record.files[0].status == "moved"


def test_partial_failure_reports_moved_and_skipped_counts(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate_a = _candidate(source_a)
    candidate_b = _candidate(source_b, category="image_macro")

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        return _move_summary(
            quarantine,
            (
                MoveOutcome(source_a, quarantine / "a.png", MoveStatus.MOVED, ""),
                MoveOutcome(
                    source_b,
                    quarantine / "b.png",
                    MoveStatus.FAILED,
                    "The source file changed after it was scanned.",
                ),
            ),
            QuarantineState.COMPLETED_WITH_FAILURES,
        )

    window, _ = _scanned_candidate_window(
        qtbot,
        monkeypatch,
        tmp_path,
        candidates=(candidate_a, candidate_b),
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window.results_list.item(1).setCheckState(Qt.CheckState.Checked)
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(lambda: "Quarantine finished with failures" in window.status_label.text())

    assert "1 moved" in window.status_label.text()
    assert "1 skipped" in window.status_label.text()


def test_moved_row_is_removed_when_candidate_path_has_symlinked_ancestor(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real_parent, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")
    candidate = _candidate(alias / "shot.png")
    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )
    summary = _move_summary(
        tmp_path / "quarantine",
        (
            MoveOutcome(
                (real_parent / "shot.png").resolve(),
                tmp_path / "quarantine" / "shot.png",
                MoveStatus.MOVED,
                "",
            ),
        ),
        QuarantineState.COMPLETED,
    )

    window._finish_quarantine(summary, None)

    assert window.results_list.count() == 0


def test_total_failure_reports_clean_message(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        return _move_summary(
            quarantine,
            (
                MoveOutcome(
                    source_file,
                    quarantine / "shot.png",
                    MoveStatus.FAILED,
                    "The copy failed.",
                ),
            ),
            QuarantineState.FAILED,
        )

    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(
        lambda: "No checked files could be moved" in window.status_label.text()
    )


def test_move_worker_exception_is_safe_and_not_leaked(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    private = "private move body"

    def on_move(*args, **kwargs):
        raise RuntimeError(private)

    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(
        lambda: "could not be completed" in window.status_label.text()
    )

    assert private not in window.status_label.text()


def test_forgetting_quarantine_folder_clears_it_and_disables_move(
    qtbot, tmp_path: Path
) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    store = MemoryStore()
    store.write(QUARANTINE_FOLDER_KEY, str(quarantine))
    window = MainWindow(settings_store=store, initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    window.forget_quarantine_button.click()

    assert QUARANTINE_FOLDER_KEY not in store.values
    assert "No quarantine folder" in window.quarantine_label.text()
    assert not window.forget_quarantine_button.isEnabled()
    assert not window.move_quarantine_button.isEnabled()


def test_move_button_is_disabled_while_scanning(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    entered = Event()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    def run_scan(*args, **kwargs):
        entered.set()
        kwargs["cancel_event"].wait(2)
        return _summary()

    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        settings_store=MemoryStore(),
    )
    qtbot.addWidget(window)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    _select(window, monkeypatch, source_dir)
    _pick_quarantine(window, monkeypatch, quarantine)

    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)

    assert not window.move_quarantine_button.isEnabled()
    assert not window.select_quarantine_button.isEnabled()

    window.cancel_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())


def test_close_during_quarantine_waits_for_move_then_closes(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    entered = Event()
    release = Event()
    deleted = []
    monkeypatch.setattr(
        window_module.OperationThread,
        "deleteLater",
        lambda thread: deleted.append(thread),
    )

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        entered.set()
        release.wait(2)
        return _move_summary(
            quarantine,
            (
                MoveOutcome(
                    source_file,
                    quarantine / "shot.png",
                    MoveStatus.MOVED,
                    "",
                ),
            ),
            QuarantineState.COMPLETED,
        )

    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(entered.is_set)

    window.close()
    qtbot.waitUntil(lambda: not window.isVisible())
    release.set()
    qtbot.waitUntil(lambda: len(deleted) == 1)

    assert window._thread is None
    assert (quarantine / "shot.png").exists() is False


def test_close_timeout_and_repeated_close_record_quarantine_once(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    entered = Event()
    release = Event()
    store = MemoryStore()

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        entered.set()
        release.wait(2)
        return _move_summary(
            quarantine,
            (
                MoveOutcome(
                    source_file,
                    quarantine / "shot.png",
                    MoveStatus.MOVED,
                    "",
                ),
            ),
            QuarantineState.COMPLETED,
        )

    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )
    window._settings_store = store
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move
    window.move_quarantine_button.click()
    qtbot.waitUntil(entered.is_set)
    thread = window._thread
    assert thread is not None
    monkeypatch.setattr(thread, "wait", lambda *args: False)

    class CloseEvent:
        def __init__(self) -> None:
            self.accepted = False
            self.ignored = False

        def accept(self) -> None:
            self.accepted = True

        def ignore(self) -> None:
            self.ignored = True

    first = CloseEvent()
    second = CloseEvent()
    window.closeEvent(first)
    window.closeEvent(second)

    assert first.ignored and second.ignored
    assert load_activity_history(store) == ()

    release.set()
    qtbot.waitUntil(lambda: window._thread is None)
    records = load_activity_history(store)
    assert len(records) == 1
    assert isinstance(records[0], QuarantineHistoryRecord)
    assert records[0].outcome == "completed"
    assert records[0].moved == 1


def test_candidate_rows_store_candidate_and_thumbnail_icon(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    candidate = _candidate(source_file)
    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )

    item = window.results_list.item(0)

    assert item.data(Qt.ItemDataRole.UserRole) is candidate
    assert not item.icon().isNull()


def test_invalid_thumbnail_bytes_do_not_break_rows(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    candidate = ScanCandidate(
        source_file,
        "screenshot",
        "Visual reason for screenshot.",
        0.9,
        SourceIdentity(0, "a" * 64),
        b"not a png",
        1,
        1,
    )
    window, _ = _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=(candidate,)
    )

    item = window.results_list.item(0)

    assert item.icon().isNull()
    assert str(source_file) in item.text()


def test_scan_live_elapsed_status_and_completed_history_record(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    store = MemoryStore()
    clock = [10.0]
    entered = Event()
    send_progress = Event()
    release = Event()

    def run_scan(folder, config, transport, **kwargs):
        entered.set()
        send_progress.wait(2)
        kwargs["progress"](2, 4)
        release.wait(2)
        return _summary(
            discovered=4,
            analyzed=4,
            ordinary=3,
            uncertain=0,
            failed=0,
        )

    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=FakeTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        monotonic=lambda: clock[0],
        utc_now=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)
    assert window.status_label.text() == (
        "Scanning: preparing the image list. Elapsed: <1 sec."
    )
    assert not window.activity_history_button.isEnabled()

    clock[0] = 11.5
    window._scan_timer.timeout.emit()
    assert window.status_label.text().endswith("Elapsed: 1 sec.")

    send_progress.set()
    qtbot.waitUntil(lambda: "2 of 4 images" in window.status_label.text())
    assert window.status_label.text() == (
        "Scanning: 2 of 4 images processed. Elapsed: 1 sec."
    )

    clock[0] = 12.4
    release.set()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert window.status_label.text().endswith("Elapsed: 2 sec.")
    assert window.activity_history_button.isEnabled()
    assert load_activity_history(store) == (
        ScanHistoryRecord(
            started_at_utc="2026-09-20T12:00:00Z",
            source_folder=str(tmp_path),
            model="vision-model",
            outcome="completed",
            duration_ms=2400,
            discovered=4,
            analyzed=4,
            candidates=0,
            ordinary=3,
            uncertain=0,
            failed=0,
            skipped_directories=0,
        ),
    )


def test_declined_consent_creates_no_history_or_timer(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    store = MemoryStore()
    clock_calls = []
    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        confirm_transfer=lambda *_: False,
        monotonic=lambda: clock_calls.append(True) or 1.0,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()

    assert clock_calls == []
    assert SCAN_HISTORY_KEY not in store.values
    assert not window._scan_timer.isActive()


def test_clock_failure_does_not_prevent_scan_or_history(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    store = MemoryStore()

    def unavailable_clock():
        raise RuntimeError("private clock failure")

    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(
            discovered=1, analyzed=1, ordinary=1
        ),
        confirm_transfer=lambda *_: True,
        monotonic=unavailable_clock,
        utc_now=unavailable_clock,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert window.status_label.text().endswith("Elapsed: <1 sec.")
    assert "private clock" not in window.status_label.text()
    records = load_activity_history(store)
    assert len(records) == 1
    assert records[0].duration_ms == 0
    assert records[0].outcome == "completed"


def test_cancelled_scan_and_retry_create_separate_history_records(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    store = MemoryStore()
    clock = [1.0]
    attempts = 0
    release_retry = Event()

    def run_scan(folder, config, transport, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            kwargs["cancel_event"].wait(2)
            return _summary(ScanState.CANCELLED, discovered=2)
        release_retry.wait(2)
        return _summary(discovered=1, analyzed=1, ordinary=1)

    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=FakeTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        monotonic=lambda: clock[0],
        utc_now=lambda: datetime(2026, 9, 20, 12, attempts, tzinfo=timezone.utc),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.cancel_button.isEnabled())
    clock[0] = 3.0
    window.cancel_button.click()
    assert window.status_label.text() == "Cancelling scan... Elapsed: 2 sec."
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    clock[0] = 10.0
    window.scan_button.click()
    qtbot.waitUntil(lambda: attempts == 2)
    clock[0] = 11.0
    release_retry.set()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    records = load_activity_history(store)
    assert [record.outcome for record in records] == ["cancelled", "completed"]
    assert [record.duration_ms for record in records] == [2000, 1000]


def test_scan_history_write_failure_preserves_results_and_reports_safe_warning(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    store = MemoryStore()
    store.write_error = True
    candidate_path = tmp_path / "candidate.png"
    candidate_path.write_bytes(b"image")
    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(
            candidates=(_candidate(candidate_path),), discovered=1, analyzed=1
        ),
        confirm_transfer=lambda *_: True,
        monotonic=lambda: 5.0,
        utc_now=lambda: datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)

    assert window.scan_button.isEnabled()
    assert window.status_label.text().endswith(
        "Elapsed: <1 sec. Activity history could not be saved."
    )
    assert "private settings" not in window.status_label.text()


def test_history_dialog_shows_newest_first_and_clears_after_confirmation(
    qtbot, monkeypatch
) -> None:
    store = MemoryStore()
    older = ScanHistoryRecord(
        "2026-09-20T10:00:00Z", "/older", "model-a", "completed", 1000,
        2, 2, 1, 1, 0, 0, 0,
    )
    newer = ScanHistoryRecord(
        "2026-09-20T11:00:00Z", "/newer", "model-b", "cancelled", 61000,
        None, None, None, None, None, None, None,
    )
    assert append_activity_history(store, older)
    assert append_activity_history(store, newer)
    dialog = ActivityHistoryDialog(store)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Activity History"
    assert "Scan source folders and model names" in dialog.disclosure_label.text()
    assert dialog.tree.columnCount() == 7
    assert [
        dialog.tree.headerItem().text(index) for index in range(7)
    ] == ["Type", "Started (UTC)", "Source", "Model / Destination", "Result", "Duration", "Counts / Message"]
    assert dialog.tree.topLevelItemCount() == 2
    assert dialog.tree.topLevelItem(0).text(2) == "/newer"
    assert dialog.tree.topLevelItem(0).text(4) == "Cancelled"
    assert dialog.tree.topLevelItem(0).text(5) == "1 min 1 sec"
    assert dialog.tree.topLevelItem(0).text(6) == "Counts unavailable"
    assert not dialog.empty_label.isVisible()
    assert dialog.clear_button.isEnabled()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    dialog.clear_button.click()

    assert load_activity_history(store) == ()
    assert dialog.tree.topLevelItemCount() == 0
    assert not dialog.clear_button.isEnabled()
    assert not dialog.empty_label.isHidden()


def test_activity_history_dialog_shows_quarantine_children(qtbot) -> None:
    store = MemoryStore()
    record = QuarantineHistoryRecord(
        "2026-09-20T12:00:00Z", "/source", "/quarantine", "batch-1",
        "completed_with_failures", 2500, 1, 1, 0,
        (
            window_module.QuarantineFileHistory(
                "/source/a.png", "/quarantine/a.png", "moved", ""
            ),
            window_module.QuarantineFileHistory(
                "/source/b.png", "/quarantine/b.png", "conflict", "Destination exists."
            ),
        ),
    )
    assert append_activity_history(store, record)
    dialog = ActivityHistoryDialog(store)
    qtbot.addWidget(dialog)

    parent = dialog.tree.topLevelItem(0)
    assert [parent.text(index) for index in range(7)] == [
        "Quarantine", "2026-09-20T12:00:00Z", "/source", "/quarantine",
        "Completed with failures", "2 sec", "1 moved, 1 conflict, 0 failed",
    ]
    assert parent.childCount() == 2
    assert [parent.child(1).text(index) for index in range(7)] == [
        "File", "", "/source/b.png", "/quarantine/b.png", "Conflict", "",
        "Destination exists.",
    ]


def test_history_dialog_clear_failure_retains_rows_and_hides_private_error(
    qtbot, monkeypatch
) -> None:
    store = MemoryStore()
    assert append_activity_history(store, ScanHistoryRecord(
        "2026-09-20T10:00:00Z", "/source", "model", "failed", 0,
        None, None, None, None, None, None, None,
    ))
    store.delete_error = True
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args: warnings.append(args[2]),
    )
    dialog = ActivityHistoryDialog(store)
    qtbot.addWidget(dialog)

    dialog.clear_button.click()

    assert dialog.tree.topLevelItemCount() == 1
    assert warnings == ["Activity history could not be cleared."]
    assert "private" not in warnings[0]


# ---------------------------------------------------------------------------
# Automatic candidate selection settings
# ---------------------------------------------------------------------------


def test_candidate_selection_settings_dialog_has_expected_range(qtbot) -> None:
    dialog = CandidateSelectionSettingsDialog(MemoryStore(), 90)
    qtbot.addWidget(dialog)

    assert dialog.threshold_spin.minimum() == 50
    assert dialog.threshold_spin.maximum() == 100
    assert dialog.threshold_spin.value() == 90
    assert dialog.threshold_spin.suffix() == "%"
    assert "future scans" in dialog.explanation_label.text().lower()


def test_candidate_selection_settings_dialog_cancel_writes_nothing(qtbot) -> None:
    store = MemoryStore()
    dialog = CandidateSelectionSettingsDialog(store, 90)
    qtbot.addWidget(dialog)
    dialog.threshold_spin.setValue(50)

    dialog.cancel_button.click()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert store.values == {}


def test_candidate_selection_settings_dialog_save_persists(qtbot) -> None:
    store = MemoryStore()
    dialog = CandidateSelectionSettingsDialog(store, 90)
    qtbot.addWidget(dialog)
    dialog.threshold_spin.setValue(73)

    dialog.save_button.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selected_threshold == 73
    assert store.values[AUTO_SELECT_CONFIDENCE_KEY] == "73"


def test_candidate_selection_settings_dialog_failed_save_stays_open(qtbot) -> None:
    store = MemoryStore()
    store.write_error = True
    dialog = CandidateSelectionSettingsDialog(store, 90)
    qtbot.addWidget(dialog)
    dialog.threshold_spin.setValue(50)

    dialog.save_button.click()

    assert dialog.result() == 0
    assert dialog.selected_threshold == 90
    assert "could not be saved" in dialog.error_label.text().lower()
    assert "private" not in dialog.error_label.text().lower()


def test_settings_button_is_available_while_idle(qtbot) -> None:
    window = MainWindow(settings_store=MemoryStore())
    qtbot.addWidget(window)

    assert window.settings_button.text() == "Settings"
    assert window.settings_button.isEnabled()


def test_saved_threshold_changes_next_scan_not_current_rows(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    candidate = ScanCandidate(
        source_file,
        "screenshot",
        "Visual reason for screenshot.",
        0.8,
        SourceIdentity(0, "a" * 64),
        ONE_PIXEL_PNG,
        1,
        1,
    )
    store = MemoryStore()
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(candidates=(candidate,)),
        confirm_transfer=lambda *_: True,
        settings_store=store,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)
    assert window.results_list.item(0).checkState() == Qt.CheckState.Unchecked

    class AcceptedDialog:
        def __init__(self, settings_store, threshold, parent):
            assert threshold == 90
            assert settings_store is store
            self.selected_threshold = 50
            settings_store.write(AUTO_SELECT_CONFIDENCE_KEY, "50")

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(window_module, "CandidateSelectionSettingsDialog", AcceptedDialog)
    window.settings_button.click()

    assert window.results_list.item(0).checkState() == Qt.CheckState.Unchecked
    window.scan_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked


# ---------------------------------------------------------------------------
# Bulk selection (Select All / Clear All)
# ---------------------------------------------------------------------------


def _bulk_window(qtbot, monkeypatch, tmp_path: Path, candidates):
    return _scanned_candidate_window(
        qtbot, monkeypatch, tmp_path, candidates=candidates
    )


def test_selection_button_starts_disabled_with_select_all(qtbot) -> None:
    window = MainWindow(settings_store=MemoryStore(), initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    assert window.selection_button.text() == "Select All"
    assert not window.selection_button.isEnabled()


def test_empty_completed_scan_leaves_selection_disabled(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(
            discovered=1, analyzed=1, ordinary=1
        ),
        confirm_transfer=lambda *_: True,
        settings_store=MemoryStore(),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: "1 ordinary" in window.status_label.text())

    assert window.results_list.count() == 0
    assert window.selection_button.text() == "Select All"
    assert not window.selection_button.isEnabled()


@pytest.mark.parametrize(
    "state",
    [ScanState.FAILED, ScanState.CANCELLED],
)
def test_terminal_scan_without_rows_leaves_selection_disabled(
    qtbot, monkeypatch, tmp_path: Path, state: ScanState
) -> None:
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(state, discovered=1, failed=1),
        confirm_transfer=lambda *_: True,
        settings_store=MemoryStore(),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert window.results_list.count() == 0
    assert window.selection_button.text() == "Select All"
    assert not window.selection_button.isEnabled()


def test_worker_exception_leaves_selection_disabled(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    def run_scan(*args, **kwargs):
        raise RuntimeError("private failure")

    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        settings_store=MemoryStore(),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert window.results_list.count() == 0
    assert not window.selection_button.isEnabled()
    assert "private failure" not in window.status_label.text()


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (0.0, Qt.CheckState.Unchecked),
        (0.5, Qt.CheckState.Unchecked),
        (0.899999, Qt.CheckState.Unchecked),
        (0.9, Qt.CheckState.Checked),
        (0.900001, Qt.CheckState.Checked),
        (1.0, Qt.CheckState.Checked),
    ],
)
def test_candidates_use_default_auto_select_threshold(
    qtbot, monkeypatch, tmp_path: Path, confidence: float, expected: Qt.CheckState
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    candidate = ScanCandidate(
        source_file,
        "screenshot",
        "Visual reason for screenshot.",
        confidence,
        SourceIdentity(0, "a" * 64),
        ONE_PIXEL_PNG,
        1,
        1,
    )
    window, _ = _bulk_window(qtbot, monkeypatch, tmp_path, (candidate,))

    item = window.results_list.item(0)
    assert item.checkState() == expected
    expected_button = "Clear All" if expected == Qt.CheckState.Checked else "Select All"
    assert window.selection_button.text() == expected_button
    assert window.selection_button.isEnabled()


@pytest.mark.parametrize(
    ("threshold", "confidence", "expected"),
    [
        (50, 0.499999, Qt.CheckState.Unchecked),
        (50, 0.5, Qt.CheckState.Checked),
        (73, 0.729999, Qt.CheckState.Unchecked),
        (73, 0.73, Qt.CheckState.Checked),
        (100, 0.999999, Qt.CheckState.Unchecked),
        (100, 1.0, Qt.CheckState.Checked),
    ],
)
def test_candidates_use_persisted_auto_select_threshold(
    qtbot,
    monkeypatch,
    tmp_path: Path,
    threshold: int,
    confidence: float,
    expected: Qt.CheckState,
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    candidate = ScanCandidate(
        source_file,
        "screenshot",
        "Visual reason for screenshot.",
        confidence,
        SourceIdentity(0, "a" * 64),
        ONE_PIXEL_PNG,
        1,
        1,
    )
    store = MemoryStore()
    store.values[AUTO_SELECT_CONFIDENCE_KEY] = str(threshold)
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(candidates=(candidate,)),
        confirm_transfer=lambda *_: True,
        settings_store=store,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)

    assert window.results_list.item(0).checkState() == expected


def test_mixed_rows_preserve_order_data_and_unchecked_state(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    candidate_a = _candidate(source_a)
    candidate_b = _candidate(source_b, category="image_macro")
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (candidate_a, candidate_b)
    )

    assert window.results_list.count() == 2
    assert window.results_list.item(0).data(Qt.ItemDataRole.UserRole) is candidate_a
    assert window.results_list.item(1).data(Qt.ItemDataRole.UserRole) is candidate_b
    assert window.selection_button.text() == "Select All"
    assert window.selection_button.isEnabled()


def test_manual_check_of_last_row_switches_to_clear_all(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    window, _ = _bulk_window(
        qtbot,
        monkeypatch,
        tmp_path,
        (_candidate(source_a), _candidate(source_b)),
    )

    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert window.selection_button.text() == "Select All"
    assert window.selection_button.isEnabled()

    window.results_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert window.selection_button.text() == "Clear All"
    assert window.selection_button.isEnabled()

    window.results_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert window.selection_button.text() == "Select All"
    assert window.selection_button.isEnabled()


def test_select_all_checks_every_row_and_switches_to_clear_all(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    window, _ = _bulk_window(
        qtbot,
        monkeypatch,
        tmp_path,
        (_candidate(source_a), _candidate(source_b)),
    )

    window.selection_button.click()

    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked
    assert window.results_list.item(1).checkState() == Qt.CheckState.Checked
    assert window.selection_button.text() == "Clear All"


def test_clear_all_unchecks_every_row_and_switches_to_select_all(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    window, _ = _bulk_window(
        qtbot,
        monkeypatch,
        tmp_path,
        (_candidate(source_a), _candidate(source_b)),
    )
    window.selection_button.click()
    assert window.selection_button.text() == "Clear All"

    window.selection_button.click()

    assert window.results_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert window.results_list.item(1).checkState() == Qt.CheckState.Unchecked
    assert window.selection_button.text() == "Select All"


def test_single_row_toggles_in_both_directions(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "a.png"
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (_candidate(source_file),)
    )

    window.selection_button.click()
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked
    assert window.selection_button.text() == "Clear All"

    window.selection_button.click()
    assert window.results_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert window.selection_button.text() == "Select All"


def test_repeated_clicks_preserve_candidate_objects_and_order(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    candidate_a = _candidate(source_a)
    candidate_b = _candidate(source_b, category="image_macro")
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (candidate_a, candidate_b)
    )

    for _ in range(3):
        window.selection_button.click()

    assert window.results_list.count() == 2
    assert window.results_list.item(0).data(Qt.ItemDataRole.UserRole) is candidate_a
    assert window.results_list.item(1).data(Qt.ItemDataRole.UserRole) is candidate_b


def test_clicking_disabled_empty_control_changes_nothing(qtbot) -> None:
    window = MainWindow(settings_store=MemoryStore(), initial_config=READY_CONFIG)
    qtbot.addWidget(window)

    window.selection_button.click()

    assert window.results_list.count() == 0
    assert window.selection_button.text() == "Select All"
    assert not window.selection_button.isEnabled()


def test_bulk_selection_works_without_quarantine_and_keeps_move_disabled(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "a.png"
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (_candidate(source_file),)
    )

    window.selection_button.click()

    assert window.selection_button.text() == "Clear All"
    assert not window.move_quarantine_button.isEnabled()
    assert "No quarantine folder" in window.quarantine_label.text()


def test_bulk_selection_updates_move_readiness_with_quarantine(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "a.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (_candidate(source_file),)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    assert not window.move_quarantine_button.isEnabled()

    window.selection_button.click()
    assert window.selection_button.text() == "Clear All"
    assert window.move_quarantine_button.isEnabled()

    window.selection_button.click()
    assert window.selection_button.text() == "Select All"
    assert not window.move_quarantine_button.isEnabled()


def test_connection_operation_disables_selection_without_changing_checks(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    entered = Event()
    release = Event()

    def discover(config, transport):
        entered.set()
        release.wait(2)
        return KoboldCppInfo("1.0", "model", True, False)

    source_file = tmp_path / "source" / "a.png"
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (_candidate(source_file),)
    )
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert window.selection_button.text() == "Clear All"
    window._discover = discover

    window.test_connection_button.click()
    qtbot.waitUntil(entered.is_set)

    assert not window.selection_button.isEnabled()
    assert window.selection_button.text() == "Clear All"
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked

    release.set()
    qtbot.waitUntil(lambda: window.test_connection_button.isEnabled())

    assert window.selection_button.isEnabled()
    assert window.selection_button.text() == "Clear All"
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked


def test_scan_start_clears_rows_and_disables_selection(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    entered = Event()

    def run_scan(*args, **kwargs):
        entered.set()
        kwargs["cancel_event"].wait(2)
        return _summary(ScanState.CANCELLED)

    source_file = tmp_path / "source" / "a.png"
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (_candidate(source_file),)
    )
    window.selection_button.click()
    assert window.selection_button.text() == "Clear All"
    window._run_scan = run_scan

    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)

    assert window.results_list.count() == 0
    assert window.selection_button.text() == "Select All"
    assert not window.selection_button.isEnabled()

    window.cancel_button.click()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())


def test_rescan_discards_manual_checks_and_starts_unchecked(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "a.png"
    candidate = _candidate(source_file)
    window, _ = _bulk_window(qtbot, monkeypatch, tmp_path, (candidate,))
    window.selection_button.click()
    assert window.selection_button.text() == "Clear All"

    window._run_scan = lambda *args, **kwargs: _summary(
        candidates=(candidate,), discovered=1, analyzed=1
    )
    window.scan_button.click()
    qtbot.waitUntil(
        lambda: window.results_list.count() == 1 and window.scan_button.isEnabled()
    )

    assert window.results_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert window.selection_button.text() == "Select All"
    assert window.selection_button.isEnabled()


def test_review_state_is_not_restored_after_restart(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    store = MemoryStore()
    source_file = tmp_path / "source" / "a.png"
    candidate = _candidate(source_file)
    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
        run_scan=lambda *args, **kwargs: _summary(
            candidates=(candidate,), discovered=1, analyzed=1
        ),
        confirm_transfer=lambda *_: True,
        settings_store=store,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path / "source")
    window.scan_button.click()
    qtbot.waitUntil(lambda: window.results_list.count() == 1)
    window.selection_button.click()
    assert window.selection_button.text() == "Clear All"

    restarted = MainWindow(
        settings_store=store,
        initial_config=READY_CONFIG,
        transport_factory=FakeTransport,
    )
    qtbot.addWidget(restarted)

    assert restarted.results_list.count() == 0
    assert restarted.selection_button.text() == "Select All"
    assert not restarted.selection_button.isEnabled()


def test_bulk_selection_writes_no_settings_history_or_source_changes(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "a.png"
    candidate = _candidate(source_file)
    window, source_dir = _bulk_window(qtbot, monkeypatch, tmp_path, (candidate,))
    store = window._settings_store
    values_before = dict(store.values)
    history_before = load_activity_history(store)
    source_before = source_file.read_bytes()

    window.selection_button.click()
    window.selection_button.click()

    assert dict(store.values) == values_before
    assert load_activity_history(store) == history_before
    assert source_file.read_bytes() == source_before
    assert list(source_dir.iterdir()) == [source_file]


def test_select_all_then_clearing_one_row_excludes_it_from_move(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    window, _ = _bulk_window(
        qtbot,
        monkeypatch,
        tmp_path,
        (_candidate(source_a), _candidate(source_b)),
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.selection_button.click()
    window.results_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    confirmations = []

    def on_confirm(paths, folder):
        confirmations.append((tuple(paths), folder))
        return False

    window._confirm_quarantine = on_confirm
    window.move_quarantine_button.click()

    assert confirmations == [((str(source_a),), str(quarantine))]


def test_clear_all_disables_move_and_prevents_request(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (_candidate(source_a),)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.selection_button.click()
    assert window.move_quarantine_button.isEnabled()

    window.selection_button.click()

    assert window.selection_button.text() == "Select All"
    assert not window.move_quarantine_button.isEnabled()
    runs = []
    window._run_quarantine = lambda *args, **kwargs: runs.append(args)
    window.move_quarantine_button.click()
    assert runs == []


def test_quarantine_start_disables_selection_without_changing_checks(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)
    entered = Event()
    release = Event()

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        entered.set()
        release.wait(2)
        return _move_summary(
            quarantine,
            (
                MoveOutcome(
                    source_file,
                    quarantine / "shot.png",
                    MoveStatus.MOVED,
                    "",
                ),
            ),
            QuarantineState.COMPLETED,
        )

    window, _ = _bulk_window(qtbot, monkeypatch, tmp_path, (candidate,))
    _pick_quarantine(window, monkeypatch, quarantine)
    window.selection_button.click()
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(entered.is_set)

    assert not window.selection_button.isEnabled()
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked

    release.set()
    qtbot.waitUntil(lambda: window._thread is None)

    assert window.results_list.count() == 0
    assert window.selection_button.text() == "Select All"
    assert not window.selection_button.isEnabled()


def test_partial_move_keeps_failed_rows_checked_and_shows_clear_all(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate_a = _candidate(source_a)
    candidate_b = _candidate(source_b, category="image_macro")

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        return _move_summary(
            quarantine,
            (
                MoveOutcome(source_a, quarantine / "a.png", MoveStatus.MOVED, ""),
                MoveOutcome(
                    source_b,
                    quarantine / "b.png",
                    MoveStatus.FAILED,
                    "The source file changed after it was scanned.",
                ),
            ),
            QuarantineState.COMPLETED_WITH_FAILURES,
        )

    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (candidate_a, candidate_b)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.selection_button.click()
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(
        lambda: "Quarantine finished with failures" in window.status_label.text()
    )

    assert window.results_list.count() == 1
    assert window.results_list.item(0).data(Qt.ItemDataRole.UserRole) is candidate_b
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked
    assert window.selection_button.text() == "Clear All"
    assert window.selection_button.isEnabled()


def test_partial_move_with_mixed_remaining_rows_shows_select_all(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_a = tmp_path / "source" / "a.png"
    source_b = tmp_path / "source" / "b.png"
    source_c = tmp_path / "source" / "c.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate_a = _candidate(source_a)
    candidate_b = _candidate(source_b, category="image_macro")
    candidate_c = _candidate(source_c, category="comic")

    def on_move(candidates, source_root, quarantine_root, *, progress=None):
        return _move_summary(
            quarantine,
            (
                MoveOutcome(source_a, quarantine / "a.png", MoveStatus.MOVED, ""),
                MoveOutcome(
                    source_b,
                    quarantine / "b.png",
                    MoveStatus.FAILED,
                    "The source file changed after it was scanned.",
                ),
            ),
            QuarantineState.COMPLETED_WITH_FAILURES,
        )

    window, _ = _bulk_window(
        qtbot, monkeypatch, tmp_path, (candidate_a, candidate_b, candidate_c)
    )
    _pick_quarantine(window, monkeypatch, quarantine)
    window.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    window.results_list.item(1).setCheckState(Qt.CheckState.Checked)
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(
        lambda: "Quarantine finished with failures" in window.status_label.text()
    )

    assert window.results_list.count() == 2
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked
    assert window.results_list.item(1).checkState() == Qt.CheckState.Unchecked
    assert window.selection_button.text() == "Select All"
    assert window.selection_button.isEnabled()


def test_move_worker_error_preserves_rows_and_selection(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "source" / "shot.png"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    candidate = _candidate(source_file)

    def on_move(*args, **kwargs):
        raise RuntimeError("private move failure")

    window, _ = _bulk_window(qtbot, monkeypatch, tmp_path, (candidate,))
    _pick_quarantine(window, monkeypatch, quarantine)
    window.selection_button.click()
    window._confirm_quarantine = lambda *_: True
    window._run_quarantine = on_move

    window.move_quarantine_button.click()
    qtbot.waitUntil(lambda: "could not be completed" in window.status_label.text())

    assert window.results_list.count() == 1
    assert window.results_list.item(0).checkState() == Qt.CheckState.Checked
    assert window.selection_button.text() == "Clear All"
    assert window.selection_button.isEnabled()
    assert "private move failure" not in window.status_label.text()
