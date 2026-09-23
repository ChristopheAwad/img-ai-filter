"""Bounded standard-library HTTP transport tests with no real network."""

from __future__ import annotations

from threading import Event, Thread

import pytest

import img_ai_filter.http_transport as transport_module
from img_ai_filter.http_transport import HttpTransportError, StandardHttpTransport


class FakeSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class FakeResponse:
    def __init__(
        self,
        body: bytes = b'{"ok":true}',
        status: int = 200,
        headers: tuple[tuple[str, str], ...] = (("Content-Type", "application/json"),),
    ) -> None:
        self.body = body
        self.status = status
        self.headers = headers
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.body[:size]

    def getheaders(self):
        return self.headers

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    instances: list["FakeConnection"] = []
    next_response = FakeResponse()

    def __init__(self, host: str, port: int, timeout: float, **kwargs) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.kwargs = kwargs
        self.sock = FakeSocket()
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.response = type(self).next_response
        self.closed = False
        type(self).instances.append(self)

    def request(
        self, method: str, path: str, body: bytes | None, headers: dict[str, str]
    ) -> None:
        self.requests.append((method, path, body, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_http(monkeypatch):
    FakeConnection.instances = []
    FakeConnection.next_response = FakeResponse()
    monkeypatch.setattr(transport_module.http.client, "HTTPConnection", FakeConnection)
    monkeypatch.setattr(transport_module.http.client, "HTTPSConnection", FakeConnection)


def test_http_request_uses_exact_destination_path_body_headers_and_timeouts() -> None:
    transport = StandardHttpTransport()

    response = transport.request(
        "POST",
        "http://192.168.0.239:5001/v1/chat/completions?x=1",
        body=b"request-body",
        headers={"Content-Type": "application/json"},
        connect_timeout=5.0,
        read_timeout=180.0,
        max_response_bytes=1024,
    )

    connection = FakeConnection.instances[0]
    assert (connection.host, connection.port, connection.timeout) == (
        "192.168.0.239",
        5001,
        5.0,
    )
    assert connection.requests == [
        (
            "POST",
            "/v1/chat/completions?x=1",
            b"request-body",
            {"Content-Type": "application/json"},
        )
    ]
    assert connection.sock.timeouts == [180.0]
    assert response.status == 200
    assert response.body == b'{"ok":true}'
    assert response.headers == {"content-type": "application/json"}
    assert FakeConnection.next_response.read_sizes == [1025]
    assert connection.closed is True
    assert FakeConnection.next_response.closed is True


def test_https_uses_default_tls_context(monkeypatch) -> None:
    contexts: list[object] = []
    context = object()
    monkeypatch.setattr(
        transport_module.ssl, "create_default_context", lambda: contexts.append(context) or context
    )

    StandardHttpTransport().request(
        "GET",
        "https://[::1]:8443/api/extra/version",
        body=None,
        connect_timeout=1.0,
        read_timeout=2.0,
        max_response_bytes=100,
    )

    connection = FakeConnection.instances[0]
    assert connection.host == "::1"
    assert connection.port == 8443
    assert connection.kwargs == {"context": context}
    assert contexts == [context]


def test_redirect_is_returned_without_following_it() -> None:
    FakeConnection.next_response = FakeResponse(
        b"redirect", 302, (("Location", "http://8.8.8.8/steal"),)
    )

    response = StandardHttpTransport().request(
        "GET",
        "http://127.0.0.1:5001/v1/models",
        connect_timeout=1,
        read_timeout=1,
        max_response_bytes=100,
    )

    assert response.status == 302
    assert len(FakeConnection.instances) == 1


def test_timeout_is_typed_and_redacted_without_retry(monkeypatch) -> None:
    def time_out(self):
        raise TimeoutError("private network detail")

    monkeypatch.setattr(FakeConnection, "getresponse", time_out)
    with pytest.raises(HttpTransportError) as raised:
        StandardHttpTransport().request(
            "POST", "http://127.0.0.1:5001/v1/chat/completions",
            connect_timeout=1, read_timeout=2, max_response_bytes=100,
        )
    assert raised.value.kind == "timeout"
    assert "private network detail" not in str(raised.value)
    assert len(FakeConnection.instances) == 1


def test_rejects_response_one_byte_over_limit_and_closes_resources() -> None:
    FakeConnection.next_response = FakeResponse(b"123456")

    with pytest.raises(HttpTransportError, match="large"):
        StandardHttpTransport().request(
            "GET",
            "http://127.0.0.1:5001/v1/models",
            connect_timeout=1,
            read_timeout=1,
            max_response_bytes=5,
        )

    assert FakeConnection.next_response.read_sizes == [6]
    assert FakeConnection.next_response.closed is True
    assert FakeConnection.instances[0].closed is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "ftp://127.0.0.1/file",
        "http:///missing-host",
        "http://user:pass@127.0.0.1/file",
        "http://127.0.0.1:99999/file",
        "http://127.0.0.1/file#fragment",
    ],
)
def test_rejects_malformed_request_url_before_connection(url: str) -> None:
    with pytest.raises(HttpTransportError, match="request"):
        StandardHttpTransport().request(
            "GET", url, connect_timeout=1, read_timeout=1, max_response_bytes=100
        )

    assert FakeConnection.instances == []


def test_network_exception_is_redacted_and_connection_closes(monkeypatch) -> None:
    private = "private socket and request detail"

    class FailingConnection(FakeConnection):
        def request(self, *args, **kwargs) -> None:
            raise OSError(private)

    monkeypatch.setattr(transport_module.http.client, "HTTPConnection", FailingConnection)

    with pytest.raises(HttpTransportError) as raised:
        StandardHttpTransport().request(
            "GET",
            "http://127.0.0.1:5001/v1/models",
            connect_timeout=1,
            read_timeout=1,
            max_response_bytes=100,
        )

    assert str(raised.value) == "The HTTP request failed"
    assert private not in str(raised.value)
    assert FailingConnection.instances[-1].closed is True


def test_cancel_active_closes_the_current_connection(monkeypatch) -> None:
    entered = Event()
    released = Event()

    class BlockingConnection(FakeConnection):
        def getresponse(self):
            entered.set()
            released.wait(2)
            raise OSError("closed")

        def close(self) -> None:
            super().close()
            released.set()

    monkeypatch.setattr(transport_module.http.client, "HTTPConnection", BlockingConnection)
    transport = StandardHttpTransport()
    errors: list[Exception] = []

    thread = Thread(
        target=lambda: _capture_error(
            errors,
            lambda: transport.request(
                "GET",
                "http://127.0.0.1:5001/v1/models",
                connect_timeout=1,
                read_timeout=1,
                max_response_bytes=100,
            ),
        )
    )
    thread.start()
    assert entered.wait(1)

    transport.cancel_active()
    thread.join(2)

    assert not thread.is_alive()
    assert BlockingConnection.instances[-1].closed is True
    assert isinstance(errors[0], HttpTransportError)


def test_cancelled_request_sends_nothing() -> None:
    cancel = Event()
    cancel.set()

    with pytest.raises(HttpTransportError, match="cancelled"):
        StandardHttpTransport().request(
            "GET",
            "http://127.0.0.1:5001/v1/models",
            connect_timeout=1,
            read_timeout=1,
            max_response_bytes=100,
            cancel_event=cancel,
        )

    assert FakeConnection.instances == []


def test_cancellation_after_connection_creation_sends_nothing() -> None:
    class CancelsBeforeSend:
        def __init__(self) -> None:
            self.checks = 0

        def is_set(self) -> bool:
            self.checks += 1
            return self.checks >= 2

    with pytest.raises(HttpTransportError, match="cancelled"):
        StandardHttpTransport().request(
            "GET",
            "http://127.0.0.1:5001/v1/models",
            connect_timeout=1,
            read_timeout=1,
            max_response_bytes=100,
            cancel_event=CancelsBeforeSend(),
        )

    assert len(FakeConnection.instances) == 1
    assert FakeConnection.instances[0].requests == []
    assert FakeConnection.instances[0].closed is True


def _capture_error(errors: list[Exception], action) -> None:
    try:
        action()
    except Exception as error:
        errors.append(error)
