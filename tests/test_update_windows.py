from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path

import pytest

from img_ai_filter.update_install import InstallError
from img_ai_filter.update_release import UpdateAsset
from img_ai_filter.update_transport import UpdateCancelled, UpdateTransportError
from img_ai_filter.update_windows import (
    build_portable_restart_script,
    detect_windows_installation,
    download_windows_asset,
    launch_windows_installer,
    releases_tag_url,
    stage_portable_zip,
)
from img_ai_filter.update_transport import VerifiedDownload


def _asset(data: bytes, name: str = "ImageFilter-0.2.0-windows-x86_64.zip") -> UpdateAsset:
    version = "0.2.0"
    return UpdateAsset(
        name=name,
        size=len(data),
        url=f"https://github.com/ChristopheAwad/img-ai-filter/releases/download/v{version}/{name}",
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _frozen_exe(tmp_path: Path, *parts: str) -> Path:
    exe = tmp_path.joinpath(*parts, "image-filter.exe")
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"exe")
    return exe


def test_non_windows_platform_is_none(tmp_path: Path) -> None:
    exe = _frozen_exe(tmp_path, "app")
    assert (
        detect_windows_installation(exe, platform="linux", frozen=True) is None
    )


def test_source_run_is_none(tmp_path: Path) -> None:
    exe = _frozen_exe(tmp_path, "app")
    assert (
        detect_windows_installation(exe, platform="win32", frozen=False) is None
    )


def test_portable_is_detected(tmp_path: Path) -> None:
    exe = _frozen_exe(tmp_path, "Portable")
    found = detect_windows_installation(exe, platform="win32", frozen=True)
    assert found is not None
    assert found.kind == "portable"
    assert found.path == exe


def test_installed_kind_under_local_appdata(tmp_path: Path) -> None:
    local = tmp_path / "Local"
    exe = _frozen_exe(local, "Programs", "Image Filter")
    env = {"LOCALAPPDATA": str(local)}
    found = detect_windows_installation(
        exe, platform="win32", frozen=True, environment=env
    )
    assert found is not None
    assert found.kind == "installed"


def test_symlink_exe_is_none(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("symlink check needs posix in this suite")
    real = _frozen_exe(tmp_path, "real")
    link = tmp_path / "link.exe"
    link.symlink_to(real)
    assert (
        detect_windows_installation(link, platform="win32", frozen=True) is None
    )


def test_missing_exe_is_none(tmp_path: Path) -> None:
    assert (
        detect_windows_installation(
            tmp_path / "missing.exe", platform="win32", frozen=True
        )
        is None
    )


def test_unwritable_parent_is_none(tmp_path: Path, monkeypatch) -> None:
    exe = _frozen_exe(tmp_path, "app")
    monkeypatch.setattr(os, "access", lambda *args, **kwargs: False)
    assert (
        detect_windows_installation(exe, platform="win32", frozen=True) is None
    )


def test_releases_tag_url() -> None:
    assert releases_tag_url("0.2.0") == (
        "https://github.com/ChristopheAwad/img-ai-filter/releases/tag/v0.2.0"
    )


class _FakeResponse:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self._data = data
        self.status = status
        self._pos = 0

    def getheader(self, name: str):
        if name == "Content-Length":
            return str(len(self._data))
        if name == "Location":
            return None
        return None

    def read(self, limit: int) -> bytes:
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + limit]
        self._pos += len(chunk)
        return chunk


class _FakeConnection:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def request(self, *args, **kwargs) -> None:
        return None

    def getresponse(self) -> _FakeResponse:
        return self._response

    def close(self) -> None:
        return None


def _factory(response: _FakeResponse):
    def make(host: str, timeout: float) -> _FakeConnection:
        return _FakeConnection(response)

    return make


def test_download_verifies_size_and_sha(tmp_path: Path) -> None:
    data = b"windows-bytes"
    seen: list[tuple[int, int]] = []
    result = download_windows_asset(
        _asset(data),
        directory=tmp_path,
        connection_factory=_factory(_FakeResponse(data)),
        progress=lambda done, total: seen.append((done, total)),
    )
    assert result.size == len(data)
    assert result.path.read_bytes() == data
    assert seen[0] == (0, len(data))
    assert seen[-1] == (len(data), len(data))


def test_download_size_mismatch_raises_and_cleans(tmp_path: Path) -> None:
    data = b"short"
    asset = UpdateAsset(
        name="ImageFilter-0.2.0-windows-x86_64.zip",
        size=len(data) + 10,
        url="https://github.com/ChristopheAwad/img-ai-filter/releases/download/v0.2.0/ImageFilter-0.2.0-windows-x86_64.zip",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    with pytest.raises(UpdateTransportError):
        download_windows_asset(
            asset, directory=tmp_path, connection_factory=_factory(_FakeResponse(data))
        )
    assert list(tmp_path.glob(".ImageFilter-update-*")) == []


def test_download_digest_mismatch_raises_and_cleans(tmp_path: Path) -> None:
    data = b"windows-bytes"
    asset = UpdateAsset(
        name="ImageFilter-0.2.0-windows-x86_64.zip",
        size=len(data),
        url="https://github.com/ChristopheAwad/img-ai-filter/releases/download/v0.2.0/ImageFilter-0.2.0-windows-x86_64.zip",
        sha256="c" * 64,
    )
    with pytest.raises(UpdateTransportError):
        download_windows_asset(
            asset, directory=tmp_path, connection_factory=_factory(_FakeResponse(data))
        )
    assert list(tmp_path.glob(".ImageFilter-update-*")) == []


def test_download_rejects_non_windows_suffix(tmp_path: Path) -> None:
    data = b"x"
    asset = UpdateAsset(
        name="ImageFilter-0.2.0-x86_64.AppImage",
        size=len(data),
        url="https://github.com/ChristopheAwad/img-ai-filter/releases/download/v0.2.0/ImageFilter-0.2.0-x86_64.AppImage",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    with pytest.raises(UpdateTransportError):
        download_windows_asset(
            asset, directory=tmp_path, connection_factory=_factory(_FakeResponse(data))
        )


def test_download_cancel_deletes_temp(tmp_path: Path) -> None:
    class Cancelled:
        def is_set(self) -> bool:
            return True

    with pytest.raises(UpdateCancelled):
        download_windows_asset(
            _asset(b"data"),
            directory=tmp_path,
            connection_factory=_factory(_FakeResponse(b"data")),
            cancel_event=Cancelled(),
        )


def _payload_zip(path: Path, root: str) -> None:
    files = {
        f"{root}/image-filter.exe": b"exe",
        f"{root}/_internal/img_ai_filter/resources/io.github.img_ai_filter.ImageFilter.svg": b"svg",
        f"{root}/_internal/certifi/cacert.pem": b"pem",
        f"{root}/README.txt": b"readme",
        f"{root}/THIRD_PARTY_NOTICES.txt": b"notices",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_stage_zip_extracts_and_validates(tmp_path: Path) -> None:
    app_dir = tmp_path / "ImageFilter-0.5.0-windows-x86_64"
    app_dir.mkdir()
    (app_dir / "image-filter.exe").write_bytes(b"old")
    zip_path = tmp_path / "update.zip"
    _payload_zip(zip_path, "ImageFilter-0.2.0-windows-x86_64")
    verified = VerifiedDownload(
        zip_path, zip_path.stat().st_size, hashlib.sha256(zip_path.read_bytes()).hexdigest()
    )
    staging = stage_portable_zip(verified, app_dir)
    assert (staging / "image-filter.exe").is_file()
    assert (staging / "README.txt").is_file()


def test_stage_zip_rejects_unsafe_member(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "image-filter.exe").write_bytes(b"old")
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../evil.exe", b"x")
    verified = VerifiedDownload(
        zip_path, zip_path.stat().st_size, hashlib.sha256(zip_path.read_bytes()).hexdigest()
    )
    with pytest.raises(InstallError):
        stage_portable_zip(verified, app_dir)


def test_stage_zip_rejects_missing_exe(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "image-filter.exe").write_bytes(b"old")
    zip_path = tmp_path / "thin.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("root/README.txt", b"x")
    verified = VerifiedDownload(
        zip_path, zip_path.stat().st_size, hashlib.sha256(zip_path.read_bytes()).hexdigest()
    )
    with pytest.raises(InstallError):
        stage_portable_zip(verified, app_dir)


def test_restart_script_swaps_and_restarts(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    staging = tmp_path / "app.update-staging"
    script = tmp_path / "update.bat"
    result = build_portable_restart_script(
        app_dir=app_dir, staging_dir=staging, script_path=script, pid=1234
    )
    text = result.read_text(encoding="ascii")
    assert ".backup" in text
    assert "image-filter.exe" in text
    assert "1234" in text


def test_installer_launch_uses_silent_flag(tmp_path: Path) -> None:
    setup = tmp_path / "setup.exe"
    setup.write_bytes(b"setup")
    calls: list = []

    def launcher(args: list[str]):
        calls.append(args)
        return object()

    assert launch_windows_installer(setup, launcher=launcher) is True
    assert calls == [[str(setup), "/SILENT"]]


def test_installer_launch_failure_is_false(tmp_path: Path) -> None:
    def launcher(args: list[str]):
        raise OSError("blocked")

    assert (
        launch_windows_installer(tmp_path / "setup.exe", launcher=launcher) is False
    )


def test_updater_uses_packaging_windows_names() -> None:
    import json

    from img_ai_filter.packaging import windows_artifact_names
    from img_ai_filter.update_release import select_update

    names = windows_artifact_names("0.2.0", system="Windows", machine="AMD64")
    assert names.portable_zip.endswith(".zip")
    assert names.installer.endswith("-setup.exe")
    document = [
        {
            "id": 7,
            "tag_name": "v0.2.0",
            "draft": False,
            "prerelease": False,
            "body": "notes",
            "assets": [
                {
                    "name": names.portable_zip,
                    "size": 16,
                    "browser_download_url": (
                        "https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
                        f"v0.2.0/{names.portable_zip}"
                    ),
                    "digest": "sha256:" + "d" * 64,
                },
                {
                    "name": names.installer,
                    "size": 16,
                    "browser_download_url": (
                        "https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
                        f"v0.2.0/{names.installer}"
                    ),
                    "digest": "sha256:" + "e" * 64,
                },
            ],
        }
    ]
    result = select_update(
        json.dumps(document).encode(),
        installed_version="0.1.0",
        include_prereleases=False,
        target="windows",
    )
    assert result is not None
    assert result.asset.name == names.portable_zip
    assert result.extra_asset is not None
    assert result.extra_asset.name == names.installer
