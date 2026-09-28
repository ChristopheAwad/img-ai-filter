"""Nit regression tests (N2/N3). No network, offscreen."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import Qt

from img_ai_filter import window as window_module
from img_ai_filter.image_payload import SourceIdentity
from img_ai_filter.quarantine import MoveOutcome, MoveStatus, QuarantineState, QuarantineSummary
from img_ai_filter.scan_workflow import ScanCandidate, ScanState, ScanSummary
from img_ai_filter.window import MainWindow


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str):
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


ONE_PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001"
    "08060000001f15c4890000000d49444154789c6360606060"
    "000000050001a5f645400000000049454e44ae426082"
)


def _identity(data: bytes) -> SourceIdentity:
    return SourceIdentity(len(data), hashlib.sha256(data).hexdigest())


def _candidate(path: Path) -> ScanCandidate:
    data = path.read_bytes() if path.is_file() else b""
    return ScanCandidate(
        path, "screenshot", "Visual reason.", 0.8, _identity(data),
        ONE_PIXEL_PNG, 1, 1, ONE_PIXEL_PNG, 1, 1,
    )


def _scanned_window(qtbot, monkeypatch, tmp_path: Path, n: int):
    monkeypatch.setattr(window_module, "_QSettingsStore", MemoryStore)
    src = tmp_path / "source"
    src.mkdir(exist_ok=True)
    cands = []
    for i in range(n):
        p = src / f"shot{i}.png"
        p.write_bytes(b"data")
        cands.append(_candidate(p))
    summary = ScanSummary(ScanState.COMPLETED, tuple(cands), discovered=n,
                          analyzed=n, ordinary=0, uncertain=0, failed=0,
                          skipped_directories=(), filtered=0)
    window = MainWindow(settings_store=MemoryStore())
    qtbot.addWidget(window)
    window._finish_scan(summary, None)
    return window, cands


def test_n2_empty_label_visible_after_moving_last_items(qtbot, monkeypatch, tmp_path):
    window, cands = _scanned_window(qtbot, monkeypatch, tmp_path, 2)
    assert window.results_list.count() == 2
    qroot = tmp_path / "quarantine"
    qroot.mkdir(exist_ok=True)
    outcomes = tuple(
        MoveOutcome(c.path, qroot / c.path.name, MoveStatus.MOVED, "") for c in cands
    )
    summary = QuarantineSummary("b", qroot, outcomes, QuarantineState.COMPLETED)
    window._finish_quarantine(summary, None)
    assert window.results_list.count() == 0
    assert not window.results_empty_label.isHidden()


def test_n3_bulk_toggle_single_update_controls(qtbot, monkeypatch, tmp_path):
    window, _ = _scanned_window(qtbot, monkeypatch, tmp_path, 5)
    calls = {"n": 0}
    orig = window._update_controls
    window._update_controls = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), orig(*a, **k))[1]
    window._toggle_selection()
    # Blocked itemChanged signals: at most a few calls, not O(n) per row.
    assert calls["n"] <= 3, f"_update_controls called {calls['n']} times for 5 rows"
