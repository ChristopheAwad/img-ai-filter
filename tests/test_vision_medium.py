"""Payload and transport robustness tests (M6). No network."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import img_ai_filter.http_transport as transport_module
from img_ai_filter.http_transport import StandardHttpTransport
from img_ai_filter.image_payload import ImagePayloadError, prepare_image
from img_ai_filter.vision_client import VisionClientError, classify_image
from img_ai_filter.vision_response import VisionResponseError, parse_vision_content


def _decision(category="screenshot", reason="Flat rectangular capture.", confidence=0.9):
    return {"category": category, "reason": reason, "confidence": confidence}


def test_m6_fenced_json_is_rejected_strict():
    body = "```json\n" + json.dumps(_decision()) + "\n```"
    with pytest.raises(VisionResponseError):
        parse_vision_content(body)


def test_m6_slash_prose_reason_is_rejected_strict():
    # Privacy-first: path-like prose stays invalid (fail closed, counted).
    body = json.dumps(_decision(reason="stacked a/b/c panels"))
    with pytest.raises(VisionResponseError):
        parse_vision_content(body)


def test_m6_huge_data_url_is_rejected_before_decode():
    from img_ai_filter.endpoint import build_vision_endpoint_config

    config = build_vision_endpoint_config(
        "http://192.168.0.239:5001/v1/", model="vision-model"
    )

    calls = []

    class NeverTransport:
        def request(self, *args, **kwargs):
            calls.append(1)
            raise AssertionError("must not send")

    giant = "data:image/png;base64," + "A" * 100_000_000
    with pytest.raises(VisionClientError):
        classify_image(config, giant, NeverTransport())
    assert calls == [], "oversized payload must be rejected before any transport use"


def test_m6_upload_uses_read_timeout_after_explicit_connect(monkeypatch):
    events: list[tuple] = []

    class FakeSocket:
        def settimeout(self, value):
            events.append(("settimeout", value))

    class FakeResponse:
        status = 200

        def getheaders(self):
            return []

        def read(self, size):
            return b"{}"

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, host, port, timeout, **kwargs):
            self.timeout = timeout
            self.sock = FakeSocket()

        def connect(self):
            events.append(("connect", self.timeout))

        def request(self, method, path, body=None, headers=None):
            events.append(("request",))

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(transport_module.http.client, "HTTPConnection", FakeConnection)
    monkeypatch.setattr(transport_module.http.client, "HTTPSConnection", FakeConnection)

    StandardHttpTransport().request(
        "POST", "http://192.168.0.239:5001/v1/chat/completions",
        body=b"x" * 1024, connect_timeout=5.0, read_timeout=180.0,
        max_response_bytes=64,
    )
    assert events[0] == ("connect", 5.0)
    assert events[1] == ("settimeout", 180.0)
    assert events[2] == ("request",)


def test_m6_swapped_symlink_between_check_and_read_is_rejected(tmp_path: Path, monkeypatch):
    from PIL import Image

    real = tmp_path / "real.png"
    Image.new("RGB", (8, 8), "white").save(real)
    victim = tmp_path / "victim.png"
    # A valid image: without the fix, preparation follows the swapped link
    # and happily returns the victim's bytes; with the fix it is rejected.
    Image.new("RGB", (8, 8), "red").save(victim)

    real_is_symlink = Path.is_symlink
    calls = {"n": 0}

    def flaky_is_symlink(self):
        # Swap on the _read_bounded check (second check for this path) so the
        # link appears between that check and the open, the true race window.
        if self == real:
            calls["n"] += 1
            if calls["n"] == 2:
                real.unlink()
                real.symlink_to(victim)
                return False
        return real_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", flaky_is_symlink)
    try:
        with pytest.raises(ImagePayloadError):
            prepare_image(real)
    finally:
        # Restore a real file so tmp cleanup never follows a link.
        if real.is_symlink() or not real.is_file():
            if real.is_symlink() or real.exists():
                real.unlink()
            Image.new("RGB", (8, 8), "white").save(real)
