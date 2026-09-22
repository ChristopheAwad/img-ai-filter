from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys

import pytest

import img_ai_filter.update_install as update_install_module
from img_ai_filter.update_install import (
    AppImageInstallation,
    FileIdentity,
    InstallError,
    detect_appimage_installation,
    install_appimage,
    restart_appimage,
)
from img_ai_filter.update_transport import VerifiedDownload

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="AppImage installation is supported only on Linux",
)


def _make_appimage(path: Path, data: bytes = b"old appimage") -> Path:
    path.write_bytes(data)
    path.chmod(0o755)
    return path


def _verified(path: Path, data: bytes = b"new appimage") -> VerifiedDownload:
    path.write_bytes(data)
    path.chmod(0o600)
    return VerifiedDownload(path, len(data), hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize("value", [None, "", " ", "relative.AppImage"])
def test_missing_or_invalid_appimage_environment_is_not_installable(
    tmp_path: Path, value: str | None
) -> None:
    environment = {} if value is None else {"APPIMAGE": value}
    detected = detect_appimage_installation(environment)
    assert detected is None


def test_nonexistent_directory_and_nonregular_paths_are_not_installable(tmp_path: Path) -> None:
    assert detect_appimage_installation({"APPIMAGE": str(tmp_path / "missing")}) is None
    assert detect_appimage_installation({"APPIMAGE": str(tmp_path)}) is None


@LINUX_ONLY
def test_symlinked_appimage_is_not_installable(tmp_path: Path) -> None:
    target = _make_appimage(tmp_path / "real.AppImage")
    link = tmp_path / "link.AppImage"
    link.symlink_to(target)
    assert detect_appimage_installation({"APPIMAGE": str(link)}) is None


def test_extraction_mode_is_not_installable(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    assert (
        detect_appimage_installation(
            {"APPIMAGE": str(appimage), "APPIMAGE_EXTRACT_AND_RUN": "1"}
        )
        is None
    )


def test_non_linux_platform_skips_filesystem_probing(tmp_path: Path, monkeypatch) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    monkeypatch.setattr(update_install_module.sys, "platform", "win32")

    def forbidden_statvfs(*args, **kwargs):
        raise AssertionError("non-Linux detection must not probe the filesystem")

    monkeypatch.setattr(
        update_install_module.os, "statvfs", forbidden_statvfs, raising=False
    )
    assert detect_appimage_installation({"APPIMAGE": str(appimage)}) is None


def test_non_linux_platform_rejects_direct_installation(
    tmp_path: Path, monkeypatch
) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    download = _verified(tmp_path / "new.download")
    file_stat = appimage.stat()
    installation = AppImageInstallation(
        path=appimage,
        identity=FileIdentity(
            device=file_stat.st_dev,
            inode=file_stat.st_ino,
            size=file_stat.st_size,
            mtime_ns=file_stat.st_mtime_ns,
        ),
    )
    monkeypatch.setattr(update_install_module.sys, "platform", "win32")

    with pytest.raises(InstallError, match="Linux"):
        install_appimage(installation, download)
    assert appimage.read_bytes() == b"old appimage"
    assert download.path.read_bytes() == b"new appimage"
    assert not (tmp_path / "ImageFilter.AppImage.backup").exists()


@LINUX_ONLY
def test_valid_appimage_captures_exact_path_and_identity(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    detected = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert detected is not None
    assert detected.path == appimage
    assert detected.identity.size == len(b"old appimage")
    assert detected.identity.device == appimage.stat().st_dev
    assert detected.identity.inode == appimage.stat().st_ino


@LINUX_ONLY
def test_detection_does_not_modify_appimage(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    before = appimage.stat()
    assert detect_appimage_installation({"APPIMAGE": str(appimage)}) is not None
    after = appimage.stat()
    assert (after.st_size, after.st_mtime_ns, appimage.read_bytes()) == (
        before.st_size,
        before.st_mtime_ns,
        b"old appimage",
    )


@LINUX_ONLY
def test_install_rejects_download_outside_appimage_directory(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    download_dir = tmp_path / "downloads"
    app_dir.mkdir()
    download_dir.mkdir()
    appimage = _make_appimage(app_dir / "ImageFilter.AppImage")
    installation = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert installation is not None
    download = _verified(download_dir / "new.download")

    with pytest.raises(InstallError):
        install_appimage(installation, download)
    assert appimage.read_bytes() == b"old appimage"


@LINUX_ONLY
def test_install_rechecks_download_size_and_digest(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    installation = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert installation is not None
    download = _verified(tmp_path / "new.download")
    download.path.write_bytes(b"changed")

    with pytest.raises(InstallError, match="verification"):
        install_appimage(installation, download)
    assert appimage.read_bytes() == b"old appimage"
    assert not (tmp_path / "ImageFilter.AppImage.backup").exists()


@LINUX_ONLY
def test_install_rejects_changed_current_appimage(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    installation = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert installation is not None
    download = _verified(tmp_path / "new.download")
    appimage.write_bytes(b"changed old appimage")

    with pytest.raises(InstallError, match="changed"):
        install_appimage(installation, download)
    assert appimage.read_bytes() == b"changed old appimage"


@LINUX_ONLY
def test_successful_install_replaces_original_and_retains_one_backup(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    installation = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert installation is not None
    download = _verified(tmp_path / "new.download")

    result = install_appimage(installation, download)

    backup = tmp_path / "ImageFilter.AppImage.backup"
    assert result.path == appimage
    assert result.backup_path == backup
    assert appimage.read_bytes() == b"new appimage"
    assert backup.read_bytes() == b"old appimage"
    assert not download.path.exists()
    assert stat.S_IMODE(appimage.stat().st_mode) == 0o755


@LINUX_ONLY
def test_second_install_replaces_only_known_regular_backup(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    first = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert first is not None
    install_appimage(first, _verified(tmp_path / "first.download", b"version two"))
    second = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert second is not None

    install_appimage(second, _verified(tmp_path / "second.download", b"version three"))

    assert appimage.read_bytes() == b"version three"
    assert (tmp_path / "ImageFilter.AppImage.backup").read_bytes() == b"version two"


@LINUX_ONLY
def test_install_refuses_symlink_at_backup_path(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    installation = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert installation is not None
    unrelated = _make_appimage(tmp_path / "unrelated")
    (tmp_path / "ImageFilter.AppImage.backup").symlink_to(unrelated)

    with pytest.raises(InstallError):
        install_appimage(installation, _verified(tmp_path / "new.download"))
    assert appimage.read_bytes() == b"old appimage"
    assert unrelated.read_bytes() == b"old appimage"


@LINUX_ONLY
def test_final_replace_failure_restores_original(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    installation = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert installation is not None
    download = _verified(tmp_path / "new.download")
    real_replace = os.replace
    calls = 0

    def failing_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated final replacement failure")
        real_replace(source, destination)

    with pytest.raises(InstallError, match="restored"):
        install_appimage(installation, download, replace=failing_second_replace)
    assert appimage.read_bytes() == b"old appimage"
    assert download.path.read_bytes() == b"new appimage"


@LINUX_ONLY
def test_recovery_failure_reports_surviving_paths(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")
    installation = detect_appimage_installation({"APPIMAGE": str(appimage)})
    assert installation is not None
    download = _verified(tmp_path / "new.download")
    real_replace = os.replace
    calls = 0

    def failing_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError("simulated failure")
        real_replace(source, destination)

    with pytest.raises(InstallError) as caught:
        install_appimage(installation, download, replace=failing_replace)
    message = str(caught.value)
    assert str(download.path) in message
    assert str(tmp_path / "ImageFilter.AppImage.backup") in message
    assert not appimage.exists()


def test_restart_launches_exact_path_without_shell(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "Image Filter.AppImage")
    calls: list[tuple] = []

    def launcher(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return object()

    assert restart_appimage(appimage, launcher=launcher)
    assert calls == [([str(appimage)], {"start_new_session": True})]


def test_restart_failure_is_redacted(tmp_path: Path) -> None:
    appimage = _make_appimage(tmp_path / "ImageFilter.AppImage")

    def launcher(arguments, **kwargs):
        raise OSError("private process detail")

    assert not restart_appimage(appimage, launcher=launcher)
