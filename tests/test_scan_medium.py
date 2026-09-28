"""Scan input validation and error-masking tests (M4). No network."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.http_transport import HttpTransportError, StandardHttpTransport
from img_ai_filter.image_payload import SourceIdentity
from img_ai_filter.scanner import ScanError, ScanResult, scan_images
from img_ai_filter.scan_workflow import ScanState, run_server_scan
from img_ai_filter.vision_client import VisionClientError, classify_image
from img_ai_filter.vision_connection import TransportResponse, VisionConnectionError, discover_koboldcpp
from img_ai_filter.vision_response import VisionDecision


CONFIG = build_vision_endpoint_config(
    "http://192.168.0.239:5001/v1/", model="vision-model"
)
DATA_URL = "data:image/png;base64," + base64.b64encode(b"fakepng").decode()


@dataclass(frozen=True)
class Prepared:
    data_url: str
    identity: SourceIdentity = SourceIdentity(0, "a" * 64)
    thumbnail_png: bytes = b"preview-png"
    thumbnail_width: int = 8
    thumbnail_height: int = 8
    large_preview_png: bytes = b"large-png"
    large_preview_width: int = 16
    large_preview_height: int = 16


class FakeTransport:
    def request(self, *args, **kwargs):
        raise AssertionError("must not be called")


def test_m4_invalid_cancel_event_is_rejected_not_attribute_error(tmp_path):
    with pytest.raises(ValueError, match="cancellation"):
        run_server_scan(tmp_path, CONFIG, FakeTransport(), cancel_event=object())
    with pytest.raises(ValueError, match="cancellation"):
        classify_image(CONFIG, DATA_URL, FakeTransport(), cancel_event=object())
    transport = StandardHttpTransport()
    with pytest.raises(ValueError, match="cancellation"):
        transport.request(
            "GET", "http://127.0.0.1:9/",
            connect_timeout=1.0, read_timeout=1.0,
            max_response_bytes=64, cancel_event=object(),
        )


def test_m4_progress_failure_does_not_lose_scan_results(tmp_path):
    good = tmp_path / "good.png"
    good.write_bytes(b"png-bytes")

    def scan(_folder):
        return ScanResult((good,), ())

    def prepare(path):
        return Prepared("data:image/png;base64,Z29vZA==")

    def classify(_config, _data_url, _transport, *, cancel_event=None):
        return VisionDecision("ordinary", "Visual plain photo.", 0.2)

    def bad_progress(_done, _total):
        raise ZeroDivisionError("progress defect")

    summary = run_server_scan(
        tmp_path, CONFIG, FakeTransport(),
        scan=scan, prepare=prepare, classify=classify, progress=bad_progress,
    )
    assert summary.discovered == 1
    assert summary.analyzed == 1
    assert summary.ordinary == 1
    assert summary.state == ScanState.COMPLETED


def test_m4_http_input_errors_are_value_errors_without_network():
    transport = StandardHttpTransport()
    with pytest.raises(ValueError):
        transport.request(
            "GET", "http://127.0.0.1:9/",
            connect_timeout=1.0, read_timeout=1.0, max_response_bytes=-1,
        )
    with pytest.raises(ValueError):
        transport.request(
            "GET", "http://127.0.0.1:9/",
            connect_timeout=1.0, read_timeout=1.0, max_response_bytes=True,
        )
    # User-supplied URL problems stay transport errors (existing contract).
    with pytest.raises(HttpTransportError):
        transport.request(
            "GET", "not-a-url",
            connect_timeout=1.0, read_timeout=1.0, max_response_bytes=64,
        )


def test_m4_blank_folder_paths_are_rejected(tmp_path, monkeypatch):
    with pytest.raises(ScanError):
        scan_images("")
    with pytest.raises(ScanError):
        scan_images(b"")
    with pytest.raises(ScanError):
        scan_images(12345)  # type: ignore[arg-type]
    # Path("") normalizes to "." at construction, so it means the current
    # folder and cannot be told apart from Path("."): it scans CWD.
    monkeypatch.chdir(tmp_path)
    result = scan_images(Path(""))
    assert result == ScanResult((), (), ())


class _FailingEntry:
    def __init__(self, real):
        self._real = real
        self.path = real.path
        self.name = real.name

    def is_symlink(self):
        raise OSError("stat denied")

    def is_dir(self, *, follow_symlinks=True):
        raise OSError("stat denied")

    def is_file(self, *, follow_symlinks=True):
        raise OSError("stat denied")


class _FakeScandir:
    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return self._entries

    def __exit__(self, *args):
        return False


def test_m4_unreadable_file_is_counted_not_silent(tmp_path, monkeypatch):
    good = tmp_path / "good.png"
    bad = tmp_path / "bad.png"
    good.write_bytes(b"png-bytes")
    bad.write_bytes(b"png-bytes")

    real_scandir = os.scandir

    def failing_scandir(path):
        with real_scandir(path) as entries:
            wrapped = [
                _FailingEntry(e) if Path(e.path).name == "bad.png" else e
                for e in entries
            ]
        return _FakeScandir(wrapped)

    monkeypatch.setattr(os, "scandir", failing_scandir)

    result = scan_images(tmp_path)
    assert result.images == (good,)
    assert result.skipped_files == (bad,)

    def prepare(path):
        return Prepared("data:image/png;base64,Z29vZA==")

    def classify(_config, _data_url, _transport, *, cancel_event=None):
        return VisionDecision("ordinary", "Visual plain photo.", 0.2)

    summary = run_server_scan(
        tmp_path, CONFIG, FakeTransport(), prepare=prepare, classify=classify,
    )
    assert summary.discovered == 1
    assert summary.analyzed == 1
    assert summary.skipped_files == 1
    assert summary.state == ScanState.COMPLETED_WITH_SKIPS


def test_m4_transport_defects_are_not_masked_as_unreachable():
    class BrokenTransport:
        def request(self, *args, **kwargs):
            raise TypeError("transport programming defect")

    with pytest.raises(TypeError, match="programming defect"):
        classify_image(CONFIG, DATA_URL, BrokenTransport())

    with pytest.raises(TypeError, match="programming defect"):
        discover_koboldcpp(CONFIG, BrokenTransport())


def test_m4_malformed_discovery_body_is_invalid_not_type_error():
    class NullBodyTransport:
        def request(self, *args, **kwargs):
            return TransportResponse(200, {}, None)  # type: ignore[arg-type]

    with pytest.raises(VisionConnectionError, match="invalid response"):
        discover_koboldcpp(CONFIG, NullBodyTransport())


def test_m4_scan_summary_text_names_unreadable_files():
    from img_ai_filter.scan_workflow import ScanFailureBreakdown, ScanSummary
    from img_ai_filter.window import MainWindow

    summary = ScanSummary(
        ScanState.COMPLETED_WITH_SKIPS, (), 2, 1, 1, 0, 0, 0,
        ScanFailureBreakdown(), 0, 1,
    )
    text = MainWindow._summary_text(summary)
    assert "1 unreadable file" in text


def test_m5_uncertain_results_are_never_candidates():
    from img_ai_filter.detection import DetectionError, DetectionResult

    with pytest.raises(DetectionError, match="must not be candidates"):
        DetectionResult(
            is_candidate=True,
            category="uncertain",
            reason="Visual evidence is unclear.",
            confidence=0.4,
            default_checked=False,
        )
    ok = DetectionResult(
        is_candidate=False,
        category="uncertain",
        reason="Visual evidence is unclear.",
        confidence=0.4,
        default_checked=False,
    )
    assert ok.category == "uncertain"


def test_m5_auto_select_rule_lives_in_scan_workflow():
    import inspect

    from img_ai_filter import window as window_module
    from img_ai_filter.scan_workflow import initial_check_state

    assert initial_check_state(0.9, 90) is True
    assert initial_check_state(0.899, 90) is False
    assert initial_check_state(1.0, 100) is True
    assert initial_check_state(0.5, 50) is True
    assert initial_check_state(0.49, 50) is False
    src = inspect.getsource(window_module.MainWindow._finish_scan)
    assert "initial_check_state" in src


def test_m5_workflow_leaves_checked_false_for_gui_threshold():
    from img_ai_filter.scan_workflow import ScanCandidate

    with pytest.raises(TypeError):
        ScanCandidate(
            Path("a.png"), "screenshot", "Visual reason.", 1.0,
            SourceIdentity(1, "c" * 64), b"thumb", 8, 8,
            checked=True,  # type: ignore[call-arg]
        )
