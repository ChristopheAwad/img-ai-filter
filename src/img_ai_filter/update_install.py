"""Safe local installation and restart helpers for AppImage updates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import subprocess
from typing import Callable, Mapping

from .update_transport import VerifiedDownload


class InstallError(RuntimeError):
    """An AppImage installation failed without exposing internal details."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class AppImageInstallation:
    path: Path
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class InstallResult:
    path: Path
    backup_path: Path


def _identity(file_stat: os.stat_result) -> FileIdentity:
    return FileIdentity(
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
        size=file_stat.st_size,
        mtime_ns=file_stat.st_mtime_ns,
    )


def _has_mode_access(file_stat: os.stat_result, mask: int) -> bool:
    return bool(stat.S_IMODE(file_stat.st_mode) & mask)


def detect_appimage_installation(
    environment: Mapping[str, str] = os.environ,
) -> AppImageInstallation | None:
    """Return a validated self-install target, without modifying the filesystem."""
    value = environment.get("APPIMAGE")
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return None
    if environment.get("APPIMAGE_EXTRACT_AND_RUN"):
        return None

    path = Path(value)
    if not path.is_absolute():
        return None
    try:
        file_stat = path.lstat()
        parent_stat = path.parent.stat()
        filesystem = os.statvfs(path.parent)
    except (OSError, ValueError):
        return None

    write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    execute_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if (
        stat.S_ISLNK(file_stat.st_mode)
        or not stat.S_ISREG(file_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or not _has_mode_access(file_stat, write_bits)
        or not _has_mode_access(file_stat, execute_bits)
        or not _has_mode_access(parent_stat, write_bits)
        or not _has_mode_access(parent_stat, execute_bits)
        or not os.access(path, os.W_OK | os.X_OK)
        or not os.access(path.parent, os.W_OK | os.X_OK)
        or bool(filesystem.f_flag & getattr(os, "ST_RDONLY", 1))
    ):
        return None
    return AppImageInstallation(path=path, identity=_identity(file_stat))


def _regular_identity(path: Path) -> FileIdentity:
    try:
        file_stat = path.lstat()
    except OSError:
        raise InstallError("The update file is unavailable") from None
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise InstallError("The update file is not a safe regular file")
    return _identity(file_stat)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_appimage(
    installation: AppImageInstallation,
    download: VerifiedDownload,
    *,
    replace: Callable[[os.PathLike[str] | str, os.PathLike[str] | str], None] = os.replace,
) -> InstallResult:
    """Install a verified sibling AppImage while retaining one recovery backup."""
    if not isinstance(installation, AppImageInstallation) or not isinstance(
        download, VerifiedDownload
    ):
        raise InstallError("The update was not verified")

    appimage = installation.path
    new_path = download.path
    if appimage.parent != new_path.parent:
        raise InstallError("The verified update must be in the AppImage directory")

    current_identity = _regular_identity(appimage)
    if current_identity != installation.identity:
        raise InstallError("The current AppImage changed before installation")
    new_identity = _regular_identity(new_path)

    digest = hashlib.sha256()
    try:
        with new_path.open("rb") as update_file:
            for chunk in iter(lambda: update_file.read(1024 * 1024), b""):
                digest.update(chunk)
            os.fsync(update_file.fileno())
    except OSError:
        raise InstallError("The update file could not be verified") from None
    if new_identity.size != download.size or digest.hexdigest() != download.sha256:
        raise InstallError("The update failed verification")

    backup = appimage.with_name(appimage.name + ".backup")
    if backup.exists() or backup.is_symlink():
        try:
            backup_stat = backup.lstat()
        except OSError:
            raise InstallError("The AppImage backup path is unsafe") from None
        if stat.S_ISLNK(backup_stat.st_mode) or not stat.S_ISREG(backup_stat.st_mode):
            raise InstallError("The AppImage backup path is unsafe")

    try:
        new_path.chmod(0o755)
        if _regular_identity(appimage) != installation.identity:
            raise InstallError("The current AppImage changed before installation")
        if _regular_identity(new_path) != new_identity:
            raise InstallError("The verified update changed before installation")
        replace(appimage, backup)
    except InstallError:
        raise
    except OSError:
        raise InstallError("The AppImage backup could not be created") from None

    try:
        if _regular_identity(new_path).size != download.size:
            raise OSError("update changed")
        replace(new_path, appimage)
        _fsync_directory(appimage.parent)
    except Exception:
        try:
            replace(backup, appimage)
            _fsync_directory(appimage.parent)
        except Exception:
            raise InstallError(
                f"Recovery failed; keep these surviving files: {backup} and {new_path}"
            ) from None
        raise InstallError("Installation failed and the original AppImage was restored") from None

    return InstallResult(path=appimage, backup_path=backup)


def restart_appimage(
    path: Path,
    *,
    launcher: Callable[..., object] = subprocess.Popen,
) -> bool:
    """Start the exact installed AppImage path in a new process session."""
    try:
        launcher([str(path)], start_new_session=True)
    except Exception:
        return False
    return True
