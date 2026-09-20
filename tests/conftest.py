"""Global test safeguards."""

from __future__ import annotations

import http.client
import socket
import urllib.request

import pytest


@pytest.fixture(scope="session", autouse=True)
def block_real_network():
    """Fail any network access that a test did not replace with a fake."""

    def blocked(*args, **kwargs):
        raise AssertionError("Automated tests must not use the network")

    patch = pytest.MonkeyPatch()
    patch.setattr(socket, "create_connection", blocked)
    patch.setattr(socket, "getaddrinfo", blocked)
    patch.setattr(socket.socket, "connect", blocked)
    patch.setattr(http.client.HTTPConnection, "connect", blocked)
    patch.setattr(http.client.HTTPSConnection, "connect", blocked)
    patch.setattr(urllib.request, "urlopen", blocked)
    yield
    patch.undo()
