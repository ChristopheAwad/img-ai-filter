"""Threading regression tests (H3/H4/M3). No network, offscreen."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QFileDialog

from img_ai_filter import window as window_module
from img_ai_filter.activity_history import load_activity_history
from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.scan_workflow import ScanState, ScanSummary
from img_ai_filter.window import MainWindow


READY_CONFIG = build_vision_endpoint_config(
    "http://192.168.0.239:5001/v1/", model="vision-model"
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str):
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _make_window(**kwargs):
    defaults = dict(settings_store=MemoryStore())
    defaults.update(kwargs)
    return MainWindow(**defaults)


def test_h3_transport_created_on_gui_thread(qtbot, monkeypatch):
    """Transport factory must run on GUI thread, not in OperationThread."""
    monkeypatch.setattr(window_module, "_QSettingsStore", MemoryStore)
    gui_thread = QApplication.instance().thread()
    calls = []

    class T:
        def cancel_active(self):
            pass

    def factory():
        calls.append(QThread.currentThread())
        return T()

    seen = {}

    def fake_discover(config, transport):
        seen["thread"] = QThread.currentThread()
        seen["transport"] = transport
        from img_ai_filter.vision_connection import VisionConnectionInfo
        return VisionConnectionInfo(model="m", vision_capable=True)

    window = _make_window(transport_factory=factory)
    qtbot.addWidget(window)
    window._discover = fake_discover  # type: ignore[method-assign]
    window.server_url_input.setText("http://127.0.0.1:5001/v1/")
    window._test_connection()
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert calls, "factory never called"
    assert calls[0] is gui_thread, "transport factory ran off GUI thread"
    assert seen["transport"] is not None


def test_h4_finished_uses_signal_values_not_thread_fields(qtbot, monkeypatch):
    """_operation_finished must not re-read thread.result/thread.error."""
    import inspect

    monkeypatch.setattr(window_module, "_QSettingsStore", MemoryStore)
    src = inspect.getsource(MainWindow._operation_finished)
    assert "thread.result" not in src, "still reads thread.result"
    assert "thread.error" not in src, "still reads thread.error"
    src_close = inspect.getsource(MainWindow.closeEvent)
    assert "thread.result" not in src_close, "closeEvent still reads thread.result"


def _select(window, monkeypatch, folder: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: str(folder)
    )
    window.select_button.click()


def test_m3_close_defers_when_worker_ignores_cancel(qtbot, monkeypatch, tmp_path):
    """Uncooperative scan worker + transport without cancel_active defers close."""
    monkeypatch.setattr(window_module, "_QSettingsStore", MemoryStore)
    entered = Event()
    release = Event()
    store = MemoryStore()
    monkeypatch.setattr(
        window_module.OperationThread,
        "deleteLater",
        lambda thread: None,
    )

    class BareTransport:
        pass

    def run_scan(*args, **kwargs):
        entered.set()
        release.wait(5)
        return ScanSummary(ScanState.CANCELLED, (), 2, 0, 0, 0, 0, ())

    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=BareTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        monotonic=lambda: 10.0,
        utc_now=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(entered.is_set, timeout=5000)
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

    event = CloseEvent()
    window.closeEvent(event)

    assert event.ignored and not event.accepted
    assert window._thread is not None  # still owned, no use-after-free
    release.set()
    # Deferred close fires via singleShot after the worker finishes.
    qtbot.waitUntil(lambda: window._thread is None, timeout=10000)
    records = load_activity_history(store)
    assert len(records) == 1
    assert records[0].outcome == "cancelled"


def test_m3_close_during_scan_records_cancelled_history(qtbot, monkeypatch, tmp_path):
    """Closing mid-scan stores exactly one cancelled scan record (pin)."""
    monkeypatch.setattr(window_module, "_QSettingsStore", MemoryStore)
    entered = Event()
    store = MemoryStore()
    deleted = []
    monkeypatch.setattr(
        window_module.OperationThread,
        "deleteLater",
        lambda thread: deleted.append(thread),
    )

    class BareTransport:
        pass

    def run_scan(*args, **kwargs):
        entered.set()
        kwargs["cancel_event"].wait(5)
        return ScanSummary(ScanState.CANCELLED, (), 2, 0, 0, 0, 0, ())

    window = MainWindow(
        initial_config=READY_CONFIG,
        settings_store=store,
        transport_factory=BareTransport,
        run_scan=run_scan,
        confirm_transfer=lambda *_: True,
        monotonic=lambda: 10.0,
        utc_now=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    qtbot.addWidget(window)
    _select(window, monkeypatch, tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(entered.is_set, timeout=5000)

    window.close()
    qtbot.waitUntil(lambda: window._thread is None, timeout=10000)

    records = load_activity_history(store)
    assert len(records) == 1
    assert records[0].outcome == "cancelled"
