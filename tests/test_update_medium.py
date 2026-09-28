"""Update reliability tests (M7). No network; fake transports only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from img_ai_filter.update_release import UpdateMetadataError, select_update
from img_ai_filter.update_transport import (
    UpdateTransportError,
    download_appimage,
)


def _release_doc(version, name=None, url=None, digest=None, size=1024):
    name = name or f"ImageFilter-{version}-x86_64.AppImage"
    url = url or (
        "https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
        f"v{version}/{name}"
    )
    return {
        "id": 1,
        "draft": False,
        "prerelease": False,
        "tag_name": f"v{version}",
        "body": "Notes.",
        "assets": [{
            "name": name,
            "size": size,
            "browser_download_url": url,
            "digest": digest or ("sha256:" + "a" * 64),
        }],
    }


def test_m7_asset_url_must_name_the_expected_file():
    evil_url = (
        "https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
        "v0.2.0/entirely-different-file.bin"
    )
    body = json.dumps([_release_doc("0.2.0", url=evil_url)]).encode()
    with pytest.raises(UpdateMetadataError, match="no usable releases|URL is invalid"):
        select_update(body, installed_version="0.1.0", include_prereleases=False)


def test_m7_uppercase_digest_is_accepted_and_normalized():
    digest = "sha256:" + "B" * 64
    body = json.dumps([_release_doc("0.2.0", digest=digest)]).encode()
    release = select_update(body, installed_version="0.1.0", include_prereleases=False)
    assert release is not None
    assert release.asset.sha256 == "b" * 64


def test_m7_github_to_arbitrary_github_redirect_is_rejected(tmp_path):
    import img_ai_filter.update_transport as transport_module

    asset_url = (
        "https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
        "v0.2.0/ImageFilter-0.2.0-x86_64.AppImage"
    )

    class FakeResponse:
        def __init__(self, status=302, headers=None, body=b""):
            self.status = status
            self._headers = headers or {}
            self._body = body

        def getheader(self, name):
            return self._headers.get(name)

        def read(self, size=-1):
            chunk, self._body = self._body[:size], self._body[size:]
            return chunk

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, host, timeout):
            self.host = host

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return FakeResponse(
                302, {"Location": "https://github.com/attacker/unrelated"}
            )

        def close(self):
            pass

    from img_ai_filter.update_release import UpdateAsset

    asset = UpdateAsset(
        name="ImageFilter-0.2.0-x86_64.AppImage",
        size=8,
        url=asset_url,
        sha256="a" * 64,
    )
    with pytest.raises(UpdateTransportError, match="not permitted"):
        download_appimage(
            asset,
            directory=tmp_path,
            connection_factory=lambda host, timeout: FakeConnection(host, timeout),
        )
    assert list(tmp_path.iterdir()) == []


def test_m7_download_needs_free_space_before_network(tmp_path, monkeypatch):
    import shutil

    import img_ai_filter.update_transport as transport_module
    from img_ai_filter.update_release import UpdateAsset

    calls = []

    class Usage:
        free = 0

    def fake_usage(path):
        calls.append(path)
        return Usage()

    monkeypatch.setattr(transport_module.shutil, "disk_usage", fake_usage)

    asset = UpdateAsset(
        name="ImageFilter-0.2.0-x86_64.AppImage",
        size=10**9,
        url=("https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
             "v0.2.0/ImageFilter-0.2.0-x86_64.AppImage"),
        sha256="a" * 64,
    )
    with pytest.raises(UpdateTransportError, match="space"):
        download_appimage(
            asset,
            directory=tmp_path,
            connection_factory=lambda host, timeout: (_ for _ in ()).throw(
                AssertionError("no network on full disk")
            ),
        )
    assert list(tmp_path.iterdir()) == []


def test_m7_install_needs_free_space_and_keeps_files(tmp_path, monkeypatch):
    import img_ai_filter.update_install as install_module
    from img_ai_filter.update_install import (
        AppImageInstallation,
        FileIdentity,
        InstallError,
        install_appimage,
    )
    from img_ai_filter.update_transport import VerifiedDownload

    appimage = tmp_path / "ImageFilter.AppImage"
    appimage.write_bytes(b"old-appimage")
    appimage.chmod(0o755)
    new_file = tmp_path / ".ImageFilter-update-new"
    new_file.write_bytes(b"new-appimage")
    st = appimage.lstat()

    installation = AppImageInstallation(
        path=appimage,
        identity=FileIdentity(st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns),
    )
    download = VerifiedDownload(
        new_file, len(b"new-appimage"), hashlib.sha256(b"new-appimage").hexdigest()
    )

    class Usage:
        free = 0

    # Module imports shutil directly; patch that reference (auto-undone).
    monkeypatch.setattr(install_module.shutil, "disk_usage", lambda path: Usage())

    with pytest.raises(InstallError, match="space"):
        install_appimage(installation, download)
    assert appimage.read_bytes() == b"old-appimage"
    assert new_file.read_bytes() == b"new-appimage"


def test_m7_install_rehashes_after_chmod_and_syncs_backup(tmp_path):
    import img_ai_filter.update_install as install_module
    from img_ai_filter.update_install import (
        AppImageInstallation,
        FileIdentity,
        InstallError,
        install_appimage,
    )
    from img_ai_filter.update_transport import VerifiedDownload

    appimage = tmp_path / "ImageFilter.AppImage"
    appimage.write_bytes(b"old-appimage")
    appimage.chmod(0o755)
    new_file = tmp_path / ".ImageFilter-update-new"
    new_file.write_bytes(b"new-appimage")
    st = appimage.lstat()
    installation = AppImageInstallation(
        path=appimage,
        identity=FileIdentity(st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns),
    )
    download = VerifiedDownload(
        new_file, len(b"new-appimage"), hashlib.sha256(b"new-appimage").hexdigest()
    )

    real_chmod = Path.chmod
    swapped = {"done": False}

    def swapping_chmod(self, *args, **kwargs):
        if self == new_file and not swapped["done"]:
            swapped["done"] = True
            before = os.stat(new_file)
            real_chmod(self, *args, **kwargs)
            # Same size, restored timestamps: identity alone cannot see this.
            new_file.write_bytes(b"evil-appim!!")
            os.utime(new_file, ns=(before.st_atime_ns, before.st_mtime_ns))
            return None
        return real_chmod(self, *args, **kwargs)

    import sys
    assert sys.platform == "linux"
    from pathlib import Path as P
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(P, "chmod", swapping_chmod)
    try:
        with pytest.raises(InstallError, match="verification|changed"):
            install_appimage(installation, download)
    finally:
        monkeypatch.undo()
    assert swapped["done"]


def test_m7_corrupt_majority_with_old_valid_reports_up_to_date_pin():
    docs = [{"id": i, "draft": False, "broken": True} for i in range(29)]
    docs.append(_release_doc("0.1.0"))
    body = json.dumps(docs).encode()
    # Pinned robustness behavior: corrupt entries never hide, but an old valid
    # release alone still means "no update", not an error.
    assert select_update(body, installed_version="0.2.0", include_prereleases=False) is None


def test_m7_scan_transport_adds_certifi_bundle(monkeypatch):
    import img_ai_filter.http_transport as transport_module

    seen = {}

    class FakeContext:
        def load_verify_locations(self, *, cafile=None):
            seen["cafile"] = cafile

    contexts = []
    real_create = transport_module.ssl.create_default_context
    monkeypatch.setattr(
        transport_module.ssl, "create_default_context",
        lambda: contexts.append(FakeContext()) or contexts[-1],
    )

    import certifi

    class FakeSocket:
        def settimeout(self, value):
            pass

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
            self.sock = FakeSocket()

        def connect(self):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(transport_module.http.client, "HTTPConnection", FakeConnection)
    monkeypatch.setattr(transport_module.http.client, "HTTPSConnection", FakeConnection)

    from img_ai_filter.http_transport import StandardHttpTransport
    StandardHttpTransport().request(
        "GET", "https://127.0.0.1:8443/v1/models",
        connect_timeout=1.0, read_timeout=2.0, max_response_bytes=64,
    )
    assert seen.get("cafile") == certifi.where()


def test_m7_failed_install_removes_stale_download(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    import img_ai_filter.window as window_module
    from img_ai_filter.update_install import InstallError
    from img_ai_filter.update_transport import VerifiedDownload
    from img_ai_filter.window import MainWindow

    monkeypatch.setattr(window_module, "_QSettingsStore", _M7Store)
    monkeypatch.setattr(
        window_module.OperationThread, "deleteLater", lambda thread: None
    )
    monkeypatch.setattr(
        QMessageBox, "exec", lambda box: QMessageBox.StandardButton.Ok
    )

    temp = tmp_path / ".ImageFilter-update-stale"
    temp.write_bytes(b"stale-bytes")
    download = VerifiedDownload(
        temp, len(b"stale-bytes"), hashlib.sha256(b"stale-bytes").hexdigest()
    )

    def fail_install(installation, download_arg):
        raise InstallError("The AppImage backup could not be created")

    window = MainWindow(
        settings_store=_M7Store(),
        application_version="0.1.0",
        install_update=fail_install,
    )
    qtbot.addWidget(window)
    window._verified_update = download
    window._update_installation = object()
    window._start_update_operation(
        "install", lambda progress: fail_install(None, download)
    )
    qtbot.waitUntil(lambda: window._update_thread is None, timeout=10000)

    assert not temp.exists()
    assert window._verified_update is None
    assert "could not be created" in window.status_label.text()


class _M7Store:
    def __init__(self):
        self.values = {}

    def read(self, key):
        return self.values.get(key)

    def write(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)
