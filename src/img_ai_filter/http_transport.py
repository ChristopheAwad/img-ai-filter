"""Bounded standard-library HTTP transport."""

from __future__ import annotations

import http.client
import ssl
import threading
import urllib.parse

from .vision_connection import TransportResponse


class HttpTransportError(RuntimeError):
    """Raised when an HTTP request cannot be completed safely."""


class StandardHttpTransport:
    """Reusable HTTP transport with bounded responses and active cancellation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_connection: http.client.HTTPConnection | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        connect_timeout: float,
        read_timeout: float,
        max_response_bytes: int,
        cancel_event: object | None = None,
    ) -> TransportResponse:
        """Send one request without redirects and return a bounded response."""
        connection: http.client.HTTPConnection | None = None
        response: http.client.HTTPResponse | None = None
        try:
            parsed = urllib.parse.urlsplit(url)
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.netloc
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or bool(parsed.fragment)
            ):
                raise ValueError
            port = parsed.port
            if port is None:
                port = 80 if parsed.scheme.lower() == "http" else 443
            if not 1 <= port <= 65535:
                raise ValueError
            if max_response_bytes < 0:
                raise ValueError

            if parsed.scheme.lower() == "https":
                connection = http.client.HTTPSConnection(
                    parsed.hostname,
                    port,
                    timeout=connect_timeout,
                    context=ssl.create_default_context(),
                )
            else:
                connection = http.client.HTTPConnection(
                    parsed.hostname, port, timeout=connect_timeout
                )

            with self._lock:
                self._active_connection = connection

            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request(method, path, body=body, headers=headers or {})
            if connection.sock is not None:
                connection.sock.settimeout(read_timeout)
            response = connection.getresponse()
            response_body = response.read(max_response_bytes + 1)
            if len(response_body) > max_response_bytes:
                raise HttpTransportError("The HTTP response is too large")
            response_headers = {
                name.lower(): value for name, value in response.getheaders()
            }
            return TransportResponse(response.status, response_headers, response_body)
        except HttpTransportError:
            raise
        except Exception:
            raise HttpTransportError("The HTTP request failed") from None
        finally:
            with self._lock:
                if self._active_connection is connection:
                    self._active_connection = None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def cancel_active(self) -> None:
        """Close the active connection, if any, without waiting on network I/O."""
        with self._lock:
            connection = self._active_connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
