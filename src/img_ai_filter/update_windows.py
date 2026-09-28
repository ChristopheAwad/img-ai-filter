"""Windows update detection, download, staging, and installer helpers."""

from __future__ import annotations

import hashlib
import http.client
import os
from pathlib import Path
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit

import certifi

from .update_install import FileIdentity, InstallError
from .update_release import MAX_WINDOWS_BYTES, UpdateAsset
from .update_transport import UpdateCancelled, UpdateTransportError, VerifiedDownload


RELEASES_TAG_PAGE = "https://github.com/ChristopheAwad/img-ai-filter/releases/tag/v{version}"
_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com"}
_RELEASE_PATH_PREFIX = "/ChristopheAwad/img-ai-filter/releases/download/"
_USER_AGENT = "ImageFilter update checker"
_CHUNK_SIZE = 64 * 1024
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

_REQUIRED_PAYLOAD_FILES = (
    Path("image-filter.exe"),
    Path("_internal/img_ai_filter/resources/io.github.img_ai_filter.ImageFilter.svg"),
    Path("_internal/certifi/cacert.pem"),
    Path("README.txt"),
    Path("THIRD_PARTY_NOTICES.txt"),
)


@dataclass(frozen=True, slots=True)
class WindowsInstallation:
    path: Path
    kind: str
    identity: FileIdentity


def releases_tag_url(version: str) -> str:
    return RELEASES_TAG_PAGE.format(version=version)


def _identity(file_stat: os.stat_result) -> FileIdentity:
    return FileIdentity(
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
        size=file_stat.st_size,
        mtime_ns=file_stat.st_mtime_ns,
    )


def _has_mode_access(file_stat: os.stat_result, mask: int) -> bool:
    return bool(stat.S_IMODE(file_stat.st_mode) & mask)


def detect_windows_installation(
    executable: os.PathLike[str] | str | None = None,
    *,
    platform: str | None = None,
    frozen: bool | None = None,
    environment: Mapping[str, str] | None = None,
) -> WindowsInstallation | None:
    """Return a validated Windows install target without changing files."""
    if platform is None:
        platform = sys.platform
    if platform != "win32":
        return None
    if frozen is None:
        frozen = bool(
            getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)
        )
    if not frozen:
        return None
    if environment is None:
        environment = os.environ
    exe = Path(executable) if executable is not None else Path(sys.executable)
    if not exe.is_absolute():
        return None
    try:
        file_stat = exe.lstat()
        parent_stat = exe.parent.stat()
    except (OSError, ValueError):
        return None
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        return None
    if not stat.S_ISDIR(parent_stat.st_mode):
        return None
    write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    exec_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if not _has_mode_access(parent_stat, write_bits) or not _has_mode_access(
        parent_stat, exec_bits
    ):
        return None
    if not os.access(exe.parent, os.W_OK | os.X_OK):
        return None
    local = environment.get("LOCALAPPDATA", environment.get("LocalAppData", ""))
    kind = "portable"
    if isinstance(local, str) and local.strip():
        try:
            expected = (
                Path(local) / "Programs" / "Image Filter" / "image-filter.exe"
            )
            if str(exe).lower() == str(expected).lower():
                kind = "installed"
        except (OSError, ValueError):
            pass
    return WindowsInstallation(path=exe, kind=kind, identity=_identity(file_stat))


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


def _default_connection_factory(host: str, timeout: float) -> http.client.HTTPSConnection:
    context = ssl.create_default_context(cafile=certifi.where())
    return http.client.HTTPSConnection(host, timeout=timeout, context=context)


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
    if host == "github.com" and not parsed.path.startswith(_RELEASE_PATH_PREFIX):
        raise UpdateTransportError("The download URL is not permitted")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path


def _require_free_space(directory: Path, needed: int) -> None:
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        raise UpdateTransportError("The available storage could not be checked") from None
    if type(needed) is not int or free < needed:
        raise UpdateTransportError("There is not enough free space for the update")


def download_windows_asset(
    asset: UpdateAsset,
    *,
    directory: Path,
    connection_factory: Callable[[str, float], object] = _default_connection_factory,
    timeout: float = 30.0,
    max_redirects: int = 5,
    cancel_event: object | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> VerifiedDownload:
    """Stream an approved Windows asset to a sibling temp file and verify it."""
    if _cancelled(cancel_event):
        raise UpdateCancelled("The download was cancelled")
    if (
        type(asset.size) is not int
        or not 0 < asset.size <= MAX_WINDOWS_BYTES
        or len(asset.sha256) != 64
        or any(c not in "0123456789abcdef" for c in asset.sha256)
        or type(max_redirects) is not int
        or max_redirects < 0
    ):
        raise UpdateTransportError("The download details are invalid")
    if not (asset.name.endswith(".zip") or asset.name.endswith("-setup.exe")):
        raise UpdateTransportError("The download details are invalid")
    current_url = asset.url
    _validated_url(current_url, initial=True)
    _require_free_space(directory, asset.size)
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
            raise UpdateTransportError("The Windows download failed")
        declared = _content_length(response)
        if declared is not None and declared != asset.size:
            raise UpdateTransportError("The Windows download size is incorrect")
        if _cancelled(cancel_event):
            raise UpdateCancelled("The download was cancelled")
        if progress is not None:
            progress(0, asset.size)
        suffix = Path(asset.name).suffix or ".bin"
        descriptor, name = tempfile.mkstemp(
            prefix=".ImageFilter-update-", suffix=suffix, dir=directory
        )
        temporary_path = Path(name)
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
                    raise UpdateTransportError("The Windows download size is incorrect")
                output.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(downloaded, asset.size)
        if downloaded != asset.size:
            raise UpdateTransportError("The Windows download size is incorrect")
        actual_digest = digest.hexdigest()
        if actual_digest != asset.sha256:
            raise UpdateTransportError("The Windows download verification failed")
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
        raise UpdateTransportError("The Windows download failed") from None
    finally:
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass


def _zip_member_target(member: str) -> Path | None:
    cleaned = member.replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or ".." in cleaned.split("/"):
        return None
    return Path(*cleaned.split("/"))


def stage_portable_zip(verified: VerifiedDownload, app_dir: Path) -> Path:
    """Extract a verified portable ZIP to a sibling staging directory."""
    if not isinstance(verified, VerifiedDownload):
        raise InstallError("The update was not verified")
    zip_path = verified.path
    try:
        zip_stat = zip_path.lstat()
    except OSError:
        raise InstallError("The update file is unavailable") from None
    if stat.S_ISLNK(zip_stat.st_mode) or not stat.S_ISREG(zip_stat.st_mode):
        raise InstallError("The update file is not a safe regular file")
    # Re-hash so a post-verification swap of the temp file cannot slip through.
    digest = hashlib.sha256()
    size = 0
    try:
        with zip_path.open("rb") as staged_file:
            for chunk in iter(lambda: staged_file.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError:
        raise InstallError("The update file could not be verified") from None
    if size != verified.size or digest.hexdigest() != verified.sha256:
        raise InstallError("The update failed verification")
    if not app_dir.is_dir() or app_dir.is_symlink():
        raise InstallError("The current installation folder is unsafe")
    staging = app_dir.with_name(app_dir.name + ".update-staging")
    if staging.is_symlink():
        raise InstallError("The staging path is unsafe")
    _require_free_space_for_install(app_dir, verified.size)
    if staging.exists():
        if not staging.is_dir() or staging.is_symlink():
            raise InstallError("The staging path is unsafe")
        shutil.rmtree(staging, ignore_errors=False)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.namelist()
            if not members:
                raise InstallError("The update file is not a safe regular file")
            roots = set()
            for member in members:
                target = _zip_member_target(member)
                if target is None or not target.parts:
                    raise InstallError("The update file is not a safe regular file")
                roots.add(target.parts[0])
            if len(roots) != 1:
                raise InstallError("The update file is not a safe regular file")
            root = next(iter(roots))
            if root.casefold() == app_dir.name.casefold():
                raise InstallError("The update file is not a safe regular file")
            archive.extractall(staging.parent)
            extracted_root = staging.parent / root
            if extracted_root != staging:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                try:
                    extracted_root.rename(staging)
                except OSError:
                    raise InstallError("The update could not be staged") from None
        for required in _REQUIRED_PAYLOAD_FILES:
            if not (staging / required).is_file():
                raise InstallError("The update file is not a safe regular file")
        launcher = staging / "image-filter.exe"
        if launcher.is_symlink() or not launcher.is_file():
            raise InstallError("The update file is not a safe regular file")
    except InstallError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallError("The update could not be staged") from None
    return staging


def _require_free_space_for_install(directory: Path, needed: int) -> None:
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        raise InstallError("The available storage could not be checked") from None
    if type(needed) is not int or free < needed:
        raise InstallError("There is not enough free space for the update")


def _batch_assign(name: str, value: Path | str) -> str:
    """Render a quoted batch assignment safe for folder names with spaces."""
    text = str(value)
    if '"' in text or "\n" in text or "\r" in text:
        raise InstallError("The update could not be staged")
    # Inside a batch file a literal % must be doubled; the quoted form keeps
    # spaces and & | < > ^ safe. Double quotes cannot appear in Windows paths.
    return f'set "{name}={text.replace("%", "%%")}"'


def build_portable_restart_script(
    *,
    app_dir: Path,
    staging_dir: Path,
    script_path: Path,
    pid: int | None = None,
) -> Path:
    """Write a .bat helper that swaps staging into place after exit."""
    if pid is None:
        pid = os.getpid()
    if type(pid) is not int or pid <= 0:
        raise InstallError("The update could not be staged")
    backup = app_dir.with_name(app_dir.name + ".backup")
    lines = [
        "@echo off",
        "rem Image Filter portable update helper: waits for the app to exit,",
        "rem then swaps the staged folder into place and restarts.",
        f"set APP_PID={pid}",
        _batch_assign("APP_DIR", app_dir),
        _batch_assign("STAGING_DIR", staging_dir),
        _batch_assign("BACKUP_DIR", backup),
        ":waitloop",
        'for /f %%p in (\'tasklist /FI "PID eq %APP_PID%" /NH\') do if "%%p"=="%APP_PID%" goto stillrunning',
        "goto doswap",
        ":stillrunning",
        "timeout /t 1 /nobreak >nul",
        "goto waitloop",
        ":doswap",
        'if exist "%BACKUP_DIR%" rmdir /s /q "%BACKUP_DIR%"',
        'move "%APP_DIR%" "%BACKUP_DIR%"',
        'move "%STAGING_DIR%" "%APP_DIR%"',
        'start "" "%APP_DIR%\\image-filter.exe"',
        'del "%~f0"',
    ]
    try:
        script_path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    except OSError:
        raise InstallError("The update could not be staged") from None
    return script_path


def launch_windows_installer(
    setup_exe: Path,
    *,
    launcher: Callable[..., object] = subprocess.Popen,
) -> bool:
    """Launch the verified Inno Setup installer in silent mode."""
    try:
        setup_stat = setup_exe.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(setup_stat.st_mode) or not stat.S_ISREG(setup_stat.st_mode):
        return False
    try:
        launcher([str(setup_exe), "/SILENT"])
    except Exception:
        return False
    return True
