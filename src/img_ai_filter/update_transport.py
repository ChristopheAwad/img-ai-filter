"""Restricted HTTPS transport for GitHub update metadata and AppImages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import os
from pathlib import Path
import ssl
import tempfile
from typing import Callable
from urllib.parse import urljoin, urlsplit

import certifi

from .update_release import MAX_APPIMAGE_BYTES, MAX_METADATA_BYTES, UpdateAsset


METADATA_URL = (
    "https://api.github.com/repos/ChristopheAwad/img-ai-filter/releases?per_page=30"
)
_METADATA_PATH = "/repos/ChristopheAwad/img-ai-filter/releases?per_page=30"
_USER_AGENT = "ImageFilter update checker"
_CHUNK_SIZE = 64 * 1024
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com"}
_RELEASE_PATH_PREFIX = "/ChristopheAwad/img-ai-filter/releases/download/"

ConnectionFactory = Callable[[str, float], object]


class UpdateTransportError(RuntimeError):
    """An update request failed without exposing sensitive transport details."""


class UpdateCancelled(UpdateTransportError):
    """The user cancelled an update request."""


@dataclass(frozen=True, slots=True)
class VerifiedDownload:
    """A complete AppImage whose size and SHA-256 digest were verified."""

    path: Path
    size: int
    sha256: str


def _default_connection_factory(host: str, timeout: float) -> http.client.HTTPSConnection:
    context = ssl.create_default_context(cafile=certifi.where())
    return http.client.HTTPSConnection(host, timeout=timeout, context=context)


def _cancelled(cancel_event: object | None) -> bool:
    return cancel_event is not None and bool(getattr(cancel_event, "is_set")())


def _content_length(response: object) -> int | None:
    value = response.getheader("Content-Length")
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError):
        raise UpdateTransportError("The server returned an invalid response") from None
    if length < 0 or str(length) != value.strip():
        raise UpdateTransportError("The server returned an invalid response")
    return length


def fetch_release_metadata(
    *,
    connection_factory: ConnectionFactory = _default_connection_factory,
    timeout: float = 15.0,
    max_bytes: int = MAX_METADATA_BYTES,
    cancel_event: object | None = None,
) -> bytes:
    """Fetch the fixed GitHub releases endpoint with a hard response limit."""
    if _cancelled(cancel_event):
        raise UpdateCancelled("The update check was cancelled")
    if type(max_bytes) is not int or max_bytes < 0:
        raise UpdateTransportError("The metadata size limit is invalid")

    connection = None
    try:
        connection = connection_factory("api.github.com", timeout)
        if _cancelled(cancel_event):
            raise UpdateCancelled("The update check was cancelled")
        connection.request(
            "GET",
            _METADATA_PATH,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": _USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        if response.status in {403, 429}:
            raise UpdateTransportError("GitHub rate limit prevented the update check")
        if response.status != 200:
            raise UpdateTransportError("GitHub returned an unsuccessful response")
        declared = _content_length(response)
        if declared is not None and declared > max_bytes:
            raise UpdateTransportError("Release information is too large")

        body = bytearray()
        while True:
            if _cancelled(cancel_event):
                raise UpdateCancelled("The update check was cancelled")
            chunk = response.read(min(_CHUNK_SIZE, max_bytes - len(body) + 1))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > max_bytes:
                raise UpdateTransportError("Release information is too large")
        return bytes(body)
    except (UpdateCancelled, UpdateTransportError):
        raise
    except Exception:
        raise UpdateTransportError("GitHub could not be reached") from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _validated_url(url: str, *, initial: bool) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise UpdateTransportError("The download URL is not permitted") from None
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or bool(parsed.fragment)
        or host not in _DOWNLOAD_HOSTS
    ):
        raise UpdateTransportError("The download URL is not permitted")
    if initial and (host != "github.com" or not parsed.path.startswith(_RELEASE_PATH_PREFIX)):
        raise UpdateTransportError("The download URL is not permitted")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path


def download_appimage(
    asset: UpdateAsset,
    *,
    directory: Path,
    connection_factory: ConnectionFactory = _default_connection_factory,
    timeout: float = 30.0,
    max_redirects: int = 5,
    cancel_event: object | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> VerifiedDownload:
    """Stream an approved AppImage to a sibling temporary file and verify it."""
    if _cancelled(cancel_event):
        raise UpdateCancelled("The download was cancelled")
    if (
        type(asset.size) is not int
        or not 0 < asset.size <= MAX_APPIMAGE_BYTES
        or len(asset.sha256) != 64
        or any(character not in "0123456789abcdef" for character in asset.sha256)
        or type(max_redirects) is not int
        or max_redirects < 0
    ):
        raise UpdateTransportError("The download details are invalid")
    current_url = asset.url
    _validated_url(current_url, initial=True)
    connections: list[object] = []
    temporary_path: Path | None = None

    try:
        response = None
        for redirect_count in range(max_redirects + 1):
            if _cancelled(cancel_event):
                raise UpdateCancelled("The download was cancelled")
            host, path = _validated_url(current_url, initial=redirect_count == 0)
            connection = connection_factory(host, timeout)
            connections.append(connection)
            connection.request(
                "GET",
                path,
                headers={"Accept": "application/octet-stream", "User-Agent": _USER_AGENT},
            )
            response = connection.getresponse()
            if response.status not in _REDIRECT_STATUSES:
                break
            location = response.getheader("Location")
            if not isinstance(location, str) or not location:
                raise UpdateTransportError("The download redirect is invalid")
            if redirect_count >= max_redirects:
                raise UpdateTransportError("The download used too many redirects")
            current_url = urljoin(current_url, location)
            _validated_url(current_url, initial=False)
        else:  # pragma: no cover - loop always exits or raises at its bound
            raise UpdateTransportError("The download used too many redirects")

        if response is None or response.status != 200:
            raise UpdateTransportError("The AppImage download failed")
        declared = _content_length(response)
        if declared is not None and declared != asset.size:
            raise UpdateTransportError("The AppImage download size is incorrect")
        if _cancelled(cancel_event):
            raise UpdateCancelled("The download was cancelled")

        if progress is not None:
            progress(0, asset.size)
        descriptor, name = tempfile.mkstemp(prefix=".ImageFilter-update-", dir=directory)
        temporary_path = Path(name)
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            try:
                fchmod(descriptor, 0o600)
            except Exception:
                os.close(descriptor)
                raise
        digest = hashlib.sha256()
        downloaded = 0
        with os.fdopen(descriptor, "wb") as output:
            while True:
                if _cancelled(cancel_event):
                    raise UpdateCancelled("The download was cancelled")
                chunk = response.read(min(_CHUNK_SIZE, asset.size - downloaded + 1))
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > asset.size:
                    raise UpdateTransportError("The AppImage download size is incorrect")
                output.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(downloaded, asset.size)

        if downloaded != asset.size:
            raise UpdateTransportError("The AppImage download size is incorrect")
        actual_digest = digest.hexdigest()
        if actual_digest != asset.sha256:
            raise UpdateTransportError("The AppImage download verification failed")
        return VerifiedDownload(temporary_path, downloaded, actual_digest)
    except (UpdateCancelled, UpdateTransportError):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise UpdateTransportError("The AppImage download failed") from None
    finally:
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
