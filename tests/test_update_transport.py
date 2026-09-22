from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
import ssl
import sys
from threading import Event
import types

import pytest

import img_ai_filter.update_transport as update_transport_module
from img_ai_filter.update_release import UpdateAsset
from img_ai_filter.update_transport import (
    METADATA_URL,
    UpdateCancelled,
    UpdateTransportError,
    download_appimage,
    fetch_release_metadata,
)


class FakeResponse:
    def __init__(
        self,
        body: bytes = b"",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        chunk_size: int | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._offset = 0
        self._headers = {key.lower(): value for key, value in (headers or {}).items()}
        self._chunk_size = chunk_size
        self.read_sizes: list[int] = []

    def getheader(self, name: str, default=None):
        return self._headers.get(name.lower(), default)

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self._offset >= len(self._body):
            return b""
        requested = len(self._body) if size < 0 else size
        if self._chunk_size is not None:
            requested = min(requested, self._chunk_size)
        chunk = self._body[self._offset : self._offset + requested]
        self._offset += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response: FakeResponse, records: list[tuple]) -> None:
        self.response = response
        self.records = records

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        self.records.append(("request", method, path, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.records.append(("close",))


class ConnectionFactory:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.records: list[tuple] = []

    def __call__(self, host: str, timeout: float) -> FakeConnection:
        self.records.append(("connect", host, timeout))
        if not self.responses:
            raise AssertionError("unexpected connection")
        return FakeConnection(self.responses.pop(0), self.records)


def _asset(data: bytes, *, url: str | None = None, size: int | None = None) -> UpdateAsset:
    return UpdateAsset(
        name="ImageFilter-0.2.0-x86_64.AppImage",
        size=len(data) if size is None else size,
        url=url
        or (
            "https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
            "v0.2.0/ImageFilter-0.2.0-x86_64.AppImage"
        ),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_metadata_request_is_fixed_bounded_and_has_no_sensitive_headers() -> None:
    body = b"[]"
    response = FakeResponse(body, headers={"Content-Length": str(len(body))})
    factory = ConnectionFactory([response])

    assert fetch_release_metadata(connection_factory=factory) == body

    assert METADATA_URL.startswith("https://api.github.com/repos/")
    connect, request, close = factory.records
    assert connect[0:2] == ("connect", "api.github.com")
    assert request[0:3] == (
        "request",
        "GET",
        "/repos/ChristopheAwad/img-ai-filter/releases?per_page=30",
    )
    headers = request[3]
    assert headers["Accept"] == "application/vnd.github+json"
    assert "ImageFilter" in headers["User-Agent"]
    assert "Authorization" not in headers
    assert close == ("close",)


@pytest.mark.parametrize("status", [204, 301, 302, 400, 404, 500, 503])
def test_metadata_rejects_non_success_status(status: int) -> None:
    factory = ConnectionFactory([FakeResponse(status=status)])
    with pytest.raises(UpdateTransportError):
        fetch_release_metadata(connection_factory=factory)


@pytest.mark.parametrize("status", [403, 429])
def test_metadata_reports_rate_limit(status: int) -> None:
    factory = ConnectionFactory([FakeResponse(status=status)])
    with pytest.raises(UpdateTransportError, match="rate limit"):
        fetch_release_metadata(connection_factory=factory)


def test_metadata_declared_oversize_is_rejected_without_body_read() -> None:
    response = FakeResponse(b"ignored", headers={"Content-Length": "1001"})
    with pytest.raises(UpdateTransportError):
        fetch_release_metadata(connection_factory=ConnectionFactory([response]), max_bytes=1000)
    assert response.read_sizes == []


def test_metadata_stream_limit_rejects_lying_or_missing_length() -> None:
    response = FakeResponse(b"x" * 1001, headers={"Content-Length": "1"}, chunk_size=200)
    with pytest.raises(UpdateTransportError):
        fetch_release_metadata(connection_factory=ConnectionFactory([response]), max_bytes=1000)
    assert all(size <= 1001 for size in response.read_sizes)


def test_metadata_cancellation_before_request_opens_no_connection() -> None:
    cancelled = Event()
    cancelled.set()
    factory = ConnectionFactory([])
    with pytest.raises(UpdateCancelled):
        fetch_release_metadata(connection_factory=factory, cancel_event=cancelled)
    assert factory.records == []


def test_metadata_connection_errors_are_redacted() -> None:
    def failing_factory(host: str, timeout: float):
        raise OSError("secret machine detail")

    with pytest.raises(UpdateTransportError) as caught:
        fetch_release_metadata(connection_factory=failing_factory)
    assert str(caught.value) == "GitHub could not be reached"
    assert "secret machine detail" not in str(caught.value)


def _install_fake_certifi(monkeypatch: pytest.MonkeyPatch, where) -> None:
    fake_certifi = types.SimpleNamespace(where=where)
    monkeypatch.setitem(sys.modules, "certifi", fake_certifi)
    monkeypatch.setattr(update_transport_module, "certifi", fake_certifi, raising=False)


def test_default_connection_factory_uses_bundled_verified_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    fake_context = object()

    class RecordingHTTPS:
        def __init__(self, host, *, timeout=None, context=None):
            calls.append({"host": host, "timeout": timeout, "context": context})

    def fake_create_default_context(*, cafile=None, **kwargs):
        calls.append({"create_context": True, "cafile": cafile, **kwargs})
        return fake_context

    _install_fake_certifi(monkeypatch, lambda: "/bundled/cacert.pem")
    monkeypatch.setattr(
        update_transport_module.http.client, "HTTPSConnection", RecordingHTTPS
    )
    monkeypatch.setattr("ssl.create_default_context", fake_create_default_context)

    connection = update_transport_module._default_connection_factory(
        "api.github.com", 15.0
    )

    assert len(calls) == 2
    context_call, connect_call = calls
    assert context_call["create_context"] is True
    assert context_call["cafile"] == "/bundled/cacert.pem"
    assert context_call.get("verify_mode") != ssl.CERT_NONE
    assert context_call.get("check_hostname") is not False
    assert connect_call == {
        "host": "api.github.com",
        "timeout": 15.0,
        "context": fake_context,
    }
    assert isinstance(connection, RecordingHTTPS)


def test_missing_ca_bundle_fails_closed_without_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    where_calls: list[str] = []
    connect_calls: list[tuple] = []

    def broken_where() -> str:
        where_calls.append("called")
        raise FileNotFoundError("/bundled/cacert.pem: missing CA bundle")

    def recording_https(host, *, timeout=None, context=None):
        connect_calls.append((host, timeout, context))
        raise AssertionError("must not construct HTTPS connection")

    _install_fake_certifi(monkeypatch, broken_where)
    monkeypatch.setattr(
        update_transport_module.http.client, "HTTPSConnection", recording_https
    )

    with pytest.raises(UpdateTransportError) as caught:
        fetch_release_metadata()

    assert str(caught.value) == "GitHub could not be reached"
    assert "/bundled/cacert.pem" not in str(caught.value)
    assert "missing CA bundle" not in str(caught.value)
    assert where_calls == ["called"]
    assert connect_calls == []


class StageFailureResponse:
    def __init__(self, stage: str) -> None:
        self.status = 200
        self.stage = stage

    def getheader(self, name, default=None):
        return {"Content-Length": "2"}.get(name, default)

    def read(self, size: int = -1) -> bytes:
        if self.stage == "read":
            raise OSError("secret read detail")
        return b"[]"


class StageFailureConnection:
    def __init__(self, stage: str, records: list[tuple]) -> None:
        self.stage = stage
        self.records = records

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        if self.stage == "request":
            raise OSError("secret request detail")
        self.records.append(("request", method, path, headers))

    def getresponse(self) -> StageFailureResponse:
        if self.stage == "getresponse":
            raise OSError("secret response detail")
        return StageFailureResponse(self.stage)

    def close(self) -> None:
        self.records.append(("close",))


@pytest.mark.parametrize("stage", ["request", "getresponse", "read"])
def test_metadata_operation_failures_stay_sanitized(stage: str) -> None:
    records: list[tuple] = []

    def factory(host: str, timeout: float):
        records.append(("connect", host, timeout))
        return StageFailureConnection(stage, records)

    with pytest.raises(UpdateTransportError) as caught:
        fetch_release_metadata(connection_factory=factory)

    assert str(caught.value) == "GitHub could not be reached"
    assert "secret" not in str(caught.value)
    assert records[0][0:2] == ("connect", "api.github.com")
    assert ("close",) in records


def test_metadata_and_download_use_same_default_connection_factory() -> None:
    metadata_default = inspect.signature(fetch_release_metadata).parameters[
        "connection_factory"
    ].default
    download_default = inspect.signature(download_appimage).parameters[
        "connection_factory"
    ].default

    assert metadata_default is download_default
    assert metadata_default is update_transport_module._default_connection_factory


def test_download_streams_verifies_and_reports_monotonic_progress(tmp_path: Path) -> None:
    data = b"appimage-data" * 100_000
    response = FakeResponse(
        data,
        headers={"Content-Length": str(len(data))},
        chunk_size=32_000,
    )
    factory = ConnectionFactory([response])
    progress: list[tuple[int, int]] = []

    verified = download_appimage(
        _asset(data),
        directory=tmp_path,
        connection_factory=factory,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert verified.path.read_bytes() == data
    assert verified.size == len(data)
    assert verified.sha256 == hashlib.sha256(data).hexdigest()
    assert verified.path.parent == tmp_path
    assert verified.path.name.startswith(".ImageFilter-update-")
    assert progress[0] == (0, len(data))
    assert progress[-1] == (len(data), len(data))
    assert [done for done, _ in progress] == sorted(done for done, _ in progress)
    assert max(response.read_sizes) < len(data)


def test_download_follows_only_approved_https_redirect(tmp_path: Path) -> None:
    data = b"appimage"
    redirect = FakeResponse(
        status=302,
        headers={"Location": "https://release-assets.githubusercontent.com/file-token"},
    )
    payload = FakeResponse(data, headers={"Content-Length": str(len(data))})
    factory = ConnectionFactory([redirect, payload])

    verified = download_appimage(
        _asset(data), directory=tmp_path, connection_factory=factory
    )

    assert verified.path.read_bytes() == data
    assert [record[1] for record in factory.records if record[0] == "connect"] == [
        "github.com",
        "release-assets.githubusercontent.com",
    ]


@pytest.mark.parametrize(
    "location",
    [
        "http://release-assets.githubusercontent.com/file",
        "https://example.com/file",
        "https://user@release-assets.githubusercontent.com/file",
        "https://127.0.0.1/file",
        "https://release-assets.githubusercontent.com/file#fragment",
    ],
)
def test_download_rejects_unsafe_redirect_and_leaves_no_file(
    tmp_path: Path, location: str
) -> None:
    redirect = FakeResponse(status=302, headers={"Location": location})
    factory = ConnectionFactory([redirect])
    with pytest.raises(UpdateTransportError):
        download_appimage(
            _asset(b"appimage"), directory=tmp_path, connection_factory=factory
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("response", "asset_size"),
    [
        (FakeResponse(b"", headers={"Content-Length": "0"}), 8),
        (FakeResponse(b"short", headers={"Content-Length": "5"}), 8),
        (FakeResponse(b"too long!", headers={"Content-Length": "9"}), 8),
        (FakeResponse(b"12345678", headers={"Content-Length": "7"}), 8),
    ],
)
def test_download_rejects_size_failures_and_cleans_partial_file(
    tmp_path: Path, response: FakeResponse, asset_size: int
) -> None:
    with pytest.raises(UpdateTransportError):
        download_appimage(
            _asset(b"12345678", size=asset_size),
            directory=tmp_path,
            connection_factory=ConnectionFactory([response]),
        )
    assert list(tmp_path.iterdir()) == []


def test_download_digest_mismatch_removes_untrusted_file(tmp_path: Path) -> None:
    data = b"different"
    asset = _asset(b"expected", size=len(data))
    response = FakeResponse(data, headers={"Content-Length": str(len(data))})
    with pytest.raises(UpdateTransportError, match="verification"):
        download_appimage(
            asset,
            directory=tmp_path,
            connection_factory=ConnectionFactory([response]),
        )
    assert list(tmp_path.iterdir()) == []


def test_download_cancellation_removes_partial_file(tmp_path: Path) -> None:
    data = b"x" * 100
    cancelled = Event()

    class CancellingResponse(FakeResponse):
        def read(self, size: int = -1) -> bytes:
            chunk = super().read(10)
            cancelled.set()
            return chunk

    response = CancellingResponse(data, headers={"Content-Length": str(len(data))})
    with pytest.raises(UpdateCancelled):
        download_appimage(
            _asset(data),
            directory=tmp_path,
            connection_factory=ConnectionFactory([response]),
            cancel_event=cancelled,
        )
    assert list(tmp_path.iterdir()) == []


def test_download_rejects_unapproved_initial_url(tmp_path: Path) -> None:
    with pytest.raises(UpdateTransportError):
        download_appimage(
            _asset(b"x", url="https://example.com/file"),
            directory=tmp_path,
            connection_factory=ConnectionFactory([]),
        )
    assert list(tmp_path.iterdir()) == []


def test_download_succeeds_without_fchmod(tmp_path: Path, monkeypatch) -> None:
    data = b"appimage-data"
    response = FakeResponse(data, headers={"Content-Length": str(len(data))})
    factory = ConnectionFactory([response])
    monkeypatch.delattr(update_transport_module.os, "fchmod", raising=False)

    verified = download_appimage(
        _asset(data), directory=tmp_path, connection_factory=factory
    )

    assert verified.path.read_bytes() == data
    assert verified.size == len(data)
    assert verified.sha256 == hashlib.sha256(data).hexdigest()
    assert verified.path.parent == tmp_path
    assert verified.path.name.startswith(".ImageFilter-update-")
    assert [record[0] for record in factory.records if record[0] == "close"] == ["close"]
