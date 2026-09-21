"""KoboldCpp settings, consent, worker, and result GUI tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

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
from img_ai_filter.vision_connection import KoboldCppInfo, VisionConnectionError
from img_ai_filter.window import DEFAULT_SERVER_URL, MainWindow
from img_ai_filter.settings import QUARANTINE_FOLDER_KEY


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

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _identity(data: bytes) -> SourceIdentity:
    return SourceIdentity(len(data), hashlib.sha256(data).hexdigest())


def _candidate(path: Path, category: str = "screenshot") -> ScanCandidate:
    data = path.read_bytes() if path.is_file() else b""
    return ScanCandidate(
        path,
        category,
        f"Visual reason for {category}.",
        0.9,
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
    timer_fired = []
    QTimer.singleShot(0, lambda: timer_fired.append(True))
    qtbot.waitUntil(lambda: timer_fired == [True])
    release.set()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert window.status_label.text() == (
        "Completed with skips: 5 discovered, 4 analyzed, 0 candidates, "
        "1 ordinary, 1 uncertain, 1 failed, 1 unreadable folder."
    )
    assert not window.cancel_button.isEnabled()


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
        "1 uncertain, 0 failed, 0 unreadable folders."
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
    entered = Event()

    def run_scan(folder, config, received_transport, **kwargs):
        entered.set()
        cancel_event = kwargs["cancel_event"]
        while not cancel_event.wait(0.01):
            pass
        return _summary(ScanState.CANCELLED, discovered=2)

    window = MainWindow(
        initial_config=READY_CONFIG,
        transport_factory=lambda: transport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)

    window.cancel_button.click()
    assert window.status_label.text() == "Cancelling scan..."
    qtbot.waitUntil(lambda: window.scan_button.isEnabled())

    assert transport.cancel_calls == 1
    assert window.status_label.text() == (
        "Cancelled: 2 discovered, 0 analyzed, 0 candidates, 0 ordinary, "
        "0 uncertain, 0 failed, 0 unreadable folders."
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
    assert window.status_label.text() == "The scan could not be completed."
    assert private not in window.status_label.text()

    window.scan_button.click()
    qtbot.waitUntil(lambda: window.status_label.text().startswith("Failed:"))
    assert "2 failed" in window.status_label.text()
    assert window.scan_button.isEnabled()


def test_close_during_scan_cancels_transport_and_stops_worker(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    transport = FakeTransport()
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
        transport_factory=lambda: transport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(entered.is_set)

    window.close()
    qtbot.waitUntil(lambda: len(deleted) == 1)

    assert transport.cancel_calls == 1
    assert window._thread is None or not window._thread.isRunning()


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


def test_quarantine_confirm_parts_mention_folder_and_every_path() -> None:
    title, heading, detailed = window_module._quarantine_confirm_parts(
        ("a.png", "b.png"), "/q"
    )
    assert title == "Move checked files to quarantine?"
    assert "2" in heading
    assert "/q" in heading
    assert detailed == "a.png\nb.png"


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
