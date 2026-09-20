"""KoboldCpp settings, consent, worker, and result GUI tests."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.scan_workflow import ScanCandidate, ScanState, ScanSummary
from img_ai_filter.vision_connection import KoboldCppInfo, VisionConnectionError
from img_ai_filter.window import DEFAULT_SERVER_URL, MainWindow


READY_CONFIG = build_vision_endpoint_config(
    "http://192.168.0.239:5001/v1/", model="vision-model"
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value


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
    candidate = ScanCandidate(tmp_path / "old.png", "screenshot", "Interface.", 0.9)
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

    assert transport.cancel_calls == 1
    assert window._thread is None or not window._thread.isRunning()
